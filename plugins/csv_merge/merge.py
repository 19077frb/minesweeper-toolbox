"""Arbiter stats CSV merge, matching merge_csv/main.py's core rules."""
import csv
import json
import os
import shutil
import tempfile
import time
from datetime import datetime
from pathlib import Path

from common.core import Cancelled
from common.paths import DATA_DIR

FIRST_COLUMNS = ['Day', 'Month', 'Year', 'Hour', 'Min', 'Sec', 'mode']
REPORT_DIR = DATA_DIR / 'csv_merge_reports'


def resolve_backup_dir(output, backup_dir=None):
    value = str(backup_dir or 'CSV_backup').strip().strip('"') or 'CSV_backup'
    folder = Path(value).expanduser()
    if not folder.is_absolute():
        folder = Path(output).resolve().parent / folder
    return folder.resolve()


def validate(inputs, output, encoding, backup_dir=None):
    if len(inputs) < 2:
        raise ValueError('请添加至少两个输入 CSV 文件')
    paths = list(dict.fromkeys(Path(p).resolve() for p in inputs))
    if len(paths) < 2:
        raise ValueError('请添加至少两个不同的 CSV 文件')
    for path in paths:
        if not path.is_file() or path.suffix.lower() != '.csv':
            raise ValueError(f'无效的输入 CSV 文件: {path}')
    if not str(output).strip() or Path(output).suffix.lower() != '.csv':
        raise ValueError('请选择有效的输出 CSV 文件路径')
    if encoding not in ('utf-8', 'utf-8-sig'):
        raise ValueError('无效的输出编码')
    folder = resolve_backup_dir(output, backup_dir)
    if folder.exists() and not folder.is_dir():
        raise ValueError(f'备份位置必须是文件夹: {folder}')
    return paths, Path(output).resolve()


def create_backup_session(folder):
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    candidate = folder / f'CSV_{stamp}'
    number = 0
    while True:
        try:
            candidate.mkdir()
            return candidate
        except FileExistsError:
            number += 1
            candidate = folder / f'CSV_{stamp}_{number:03d}'


def backup_file(output, folder):
    folder.mkdir(parents=True, exist_ok=True)
    candidate = folder / output.name
    number = 0
    while True:
        created = False
        try:
            with candidate.open('xb') as dest:
                created = True
                with output.open('rb') as source:
                    shutil.copyfileobj(source, dest)
            shutil.copystat(output, candidate)
            return candidate
        except FileExistsError:
            number += 1
            candidate = folder / f'同名文件_{number:03d}' / output.name
            candidate.parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            if created:
                candidate.unlink(missing_ok=True)
            raise


def merge_csv(inputs, output, emit, stop, encoding='utf-8', backup_dir=None):
    paths, output = validate(inputs, output, encoding, backup_dir)
    backup_dir = resolve_backup_dir(output, backup_dir)
    begun = time.monotonic()
    stats = dict(files_total=len(paths), files_read=0, input_rows=0, output_rows=0,
                 duplicates_removed=0, rows_written=0, unknown_modes=0,
                 backups_total=0, backups_completed=0)
    output.parent.mkdir(parents=True, exist_ok=True)
    signature = lambda p: (p.stat().st_size, p.stat().st_mtime_ns) if p.exists() else None
    original_output = signature(output)
    input_signatures = {path: signature(path) for path in paths}
    backup_sources = list(dict.fromkeys(paths + ([output] if original_output is not None else [])))
    stats['backups_total'] = len(backup_sources)
    backups = []
    backup_session = None
    temporary, backup = None, None
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report = REPORT_DIR / f'{output.stem}_merge_report_{datetime.now():%Y%m%d_%H%M%S_%f}.json'
    status = 'failed'

    def check():
        if stop.is_set():
            raise Cancelled()

    def progress(phase):
        emit('merge_progress', dict(stats, phase=phase, seconds=time.monotonic() - begun,
                                    output=str(output), report=str(report)))

    try:
        check()
        backup_session = create_backup_session(backup_dir)
        emit('log', f'本次备份目录: {backup_session}')
        for source in backup_sources:
            check()
            expected = original_output if source == output else input_signatures[source]
            if signature(source) != expected:
                raise ValueError(f'备份前文件已被外部修改，已停止合并: {source}')
            progress('备份 CSV 文件')
            copied = backup_file(source, backup_session)
            backups.append(dict(source=str(source), backup=str(copied)))
            stats['backups_completed'] += 1
            if source == output:
                backup = copied
            if signature(source) != expected:
                raise ValueError(f'备份期间文件已被外部修改，已停止合并: {source}')
            emit('log', f'已备份 {source} → {copied}')
            progress('备份 CSV 文件')
        check()
        progress('加载 CSV 处理组件')
        import pandas as pd
        frames = []
        for path in paths:
            check()
            progress('读取 CSV')
            before = input_signatures[path]
            if signature(path) != before:
                raise ValueError(f'备份后输入文件被外部修改，已停止合并: {path}')
            # UTF-8 with or without BOM is accepted, as in pandas' original reader.
            with path.open('r', encoding='utf-8-sig', newline='') as header_file:
                header = next(csv.reader(header_file), [])
            if header[:7] != FIRST_COLUMNS or len(set(header)) != len(header):
                raise ValueError(f'{path.name}: 预期前七列为 Day,Month,Year,Hour,Min,Sec,mode，且列名不可重复')
            frame = pd.read_csv(path, encoding='utf-8-sig')
            if signature(path) != before:
                raise ValueError(f'读取过程中输入文件被外部修改: {path}')
            frames.append(frame)
            stats['files_read'] += 1
            stats['input_rows'] += len(frame)
            emit('log', f'已读取 {path.name}: {len(frame):,} 行')
            progress('读取 CSV')
        check()
        progress('合并 CSV')
        merged = pd.concat(frames, ignore_index=True, sort=False)
        check()
        progress('整行去重')
        before = len(merged)
        merged = merged.drop_duplicates(keep='first')
        stats['duplicates_removed'] = before - len(merged)
        stats['output_rows'] = len(merged)
        check()
        progress('按级别、录像时间排序')
        keys = pd.DataFrame(index=merged.index)
        keys['level'] = merged['mode'].map({'BEG': 0, 'INT': 1, 'EXP': 2}).fillna(3)
        stats['unknown_modes'] = int((keys['level'] == 3).sum())
        if stats['unknown_modes']:
            emit('log', f'WARNING: {stats["unknown_modes"]} 行级别不属于 BEG/INT/EXP，保留原值并排在最后')
        for column in ('Year', 'Month', 'Day', 'Hour', 'Min', 'Sec'):
            keys[column] = pd.to_numeric(merged[column], errors='raise')
        order = keys.sort_values(list(keys.columns), kind='stable', na_position='last').index
        merged = merged.loc[order]
        check()
        progress('写入合并结果')
        with tempfile.NamedTemporaryFile(mode='w', encoding=encoding, newline='', dir=output.parent,
                                         prefix='.csv-merge-', suffix='.tmp', delete=False) as f:
            temporary = Path(f.name)
            if merged.empty:
                merged.to_csv(f, index=False)
            for start in range(0, len(merged), 50000):
                check()
                chunk = merged.iloc[start:start + 50000]
                chunk.to_csv(f, index=False, header=start == 0)
                stats['rows_written'] += len(chunk)
                progress('写入合并结果')
            f.flush()
            os.fsync(f.fileno())
        check()
        if signature(output) != original_output:
            raise ValueError('输出文件已被外部修改，已停止替换，原文件保留')
        for path in paths:
            if signature(path) != input_signatures[path]:
                raise ValueError(f'合并期间输入文件被外部修改，已停止替换: {path}')
        os.replace(temporary, output)
        status = 'completed'
        emit('log', f'合并完成: {output}，共 {len(merged):,} 行，去重 {stats["duplicates_removed"]:,} 行')
    except Cancelled:
        status = 'cancelled'
        emit('log', '已取消；未替换输出文件')
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        summary = dict(stats, status=status, inputs=[str(p) for p in paths], output=str(output), report=str(report),
            backup=str(backup) if backup else '', backups=backups,
            backup_dir=str(backup_dir), backup_session=str(backup_session) if backup_session else '',
            deduplicate=True, sort=True,
            encoding=encoding, seconds=time.monotonic() - begun)
        report.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
        progress({'completed': '完成', 'cancelled': '已取消', 'failed': '失败'}[status])
    return output, summary
