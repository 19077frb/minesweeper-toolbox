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

FIRST_COLUMNS = ['Day', 'Month', 'Year', 'Hour', 'Min', 'Sec', 'mode']


def validate(inputs, output, encoding):
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
    return paths, Path(output).resolve()


def backup_output(output):
    candidate = output.with_name(output.stem + '_before.csv')
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
            candidate = output.with_name(f'{output.stem}_before_{datetime.now():%Y%m%d_%H%M%S}_{number:03d}.csv')
        except Exception:
            if created:
                candidate.unlink(missing_ok=True)
            raise


def merge_csv(inputs, output, emit, stop, deduplicate=True, sort=True, encoding='utf-8'):
    paths, output = validate(inputs, output, encoding)
    begun = time.monotonic()
    stats = dict(files_total=len(paths), files_read=0, input_rows=0, output_rows=0,
                 duplicates_removed=0, rows_written=0, unknown_modes=0)
    output.parent.mkdir(parents=True, exist_ok=True)
    signature = lambda p: (p.stat().st_size, p.stat().st_mtime_ns) if p.exists() else None
    original_output = signature(output)
    temporary, backup = None, None
    report = output.with_name(f'{output.stem}_merge_report_{datetime.now():%Y%m%d_%H%M%S_%f}.json')
    status = 'failed'

    def check():
        if stop.is_set():
            raise Cancelled()

    def progress(phase):
        emit('merge_progress', dict(stats, phase=phase, seconds=time.monotonic() - begun,
                                    output=str(output), report=str(report)))

    try:
        check()
        progress('加载 CSV 处理组件')
        import pandas as pd
        frames = []
        for path in paths:
            check()
            progress('读取 CSV')
            before = signature(path)
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
        if deduplicate:
            check()
            progress('整行去重')
            before = len(merged)
            merged = merged.drop_duplicates(keep='first')
            stats['duplicates_removed'] = before - len(merged)
        stats['output_rows'] = len(merged)
        if sort:
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
        if original_output is not None:
            progress('备份已有输出文件')
            backup = backup_output(output)
            emit('log', f'旧文件已备份: {backup}')
        check()
        if signature(output) != original_output:
            raise ValueError('备份期间输出文件已被外部修改，已停止替换')
        os.replace(temporary, output)
        status = 'completed'
        emit('log', f'合并完成: {output}，共 {len(merged):,} 行，去重 {stats["duplicates_removed"]:,} 行')
    except Cancelled:
        status = 'cancelled'
        emit('log', '已取消；未替换输出文件')
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        summary = dict(stats, status=status, inputs=[str(p) for p in paths], output=str(output),
            backup=str(backup) if backup else '', deduplicate=deduplicate, sort=sort,
            encoding=encoding, seconds=time.monotonic() - begun)
        report.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
        progress({'completed': '完成', 'cancelled': '已取消', 'failed': '失败'}[status])
    return output, summary
