"""Golden Sheep Cup selection and scores; reference: GSC_calc_1.0.4.exe.
Reconstructed get_sorted_data/calc_grid rules, without executing the executable.
"""
import configparser
import csv
import hashlib
from services.gsc_display import render_html
import json
import math
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from fractions import Fraction
from pathlib import Path
from common.paths import PROJECT_ROOT

from common.core import parse_avf, Cancelled
from services.engine import copy_replay

BASE = PROJECT_ROOT
COUNTS = {'Beg': 20, 'Int': 12, 'Exp': 5}
BV_LIMITS = {'Beg': 10, 'Int': 30, 'Exp': 100}
SELECTION_BV_LIMITS = {'Beg': 0, 'Int': 30, 'Exp': 100}
TIME_PADDING = {'Beg': 10, 'Int': 60, 'Exp': 240}
DEFAULT_BASELINE = {'Beg': [1.355, 9.245, 230.0], 'Int': [8.371, 6.128, 177.9],
                    'Exp': [34.08, 4.860, 157.9]}
METRICS = ('time', 'bvs', 'stnb')


def reference_settings():
    config = configparser.ConfigParser()
    config.read(BASE.parent / 'gsc_calc_1.0.ini', encoding='utf-8-sig')
    baseline = {level: [config.getfloat('nt20.5', prefix + k, fallback=v)
                for k, v in zip(('t', 'b', 's'), values)]
                for (level, values), prefix in zip(DEFAULT_BASELINE.items(), ('b', 'i', 'e'))}
    return dict(start=config.get('datetime', 'start_time', fallback=''),
                end=config.get('datetime', 'end_time', fallback=''), baseline=baseline)


def parse_datetime(text):
    try:
        value = datetime.fromisoformat(text.strip().replace('/', '-'))
    except ValueError:
        raise ValueError('时间格式应为 YYYY-MM-DD HH:MM:SS，例如 2026-10-12 12:00:00') from None
    if value.tzinfo:
        raise ValueError('请输入录像所在电脑的本地时间，不带时区')
    return value


def validate(inputs, output, edition, start, end, suffix, baseline, time_basis):
    if not inputs or any(not Path(p).is_dir() for p in inputs):
        raise ValueError('请添加有效的输入文件夹')
    if not str(output).strip():
        raise ValueError('请选择输出文件夹')
    if not re.fullmatch(r'[0-9]{1,4}', str(edition).strip()) or int(edition) < 1:
        raise ValueError('金羊杯届数应为1–9999的整数')
    start, end = parse_datetime(start), parse_datetime(end)
    if start > end:
        raise ValueError('开始时间不能晚于结束时间')
    if not suffix.strip():
        raise ValueError('请输入录像内标识的后缀')
    if time_basis not in ('recorded', 'modified'):
        raise ValueError('无效的时间依据')
    for level in COUNTS:
        if len(baseline[level]) != 3 or any(not math.isfinite(float(v)) or float(v) <= 0 for v in baseline[level]):
            raise ValueError('NT20.5基准必须为正数')
    output = Path(output).resolve()
    roots = list(dict.fromkeys(Path(p).resolve() for p in inputs))
    if any(p == output or p.is_relative_to(output) for p in roots):
        raise ValueError('输入文件夹不能等于输出文件夹或位于输出文件夹内')
    return roots, output, start, end


def rank_and_score(records, baseline):
    rankings, scores = {}, {}
    for level, n in COUNTS.items():
        selected = [v for v in records if v['replay'].level == level]
        candidates = [v for v in selected if v['replay'].bv >= BV_LIMITS[level]]
        totals, averages = {}, {}
        for metric in METRICS:
            def key(v):
                r = v['replay']
                value = r.cs if metric == 'time' else -Fraction(r.bv * 100, r.cs) if metric == 'bvs' else -r.stnb
                return value, str(v['path']).casefold()
            top = sorted(candidates, key=key)[:n]
            rankings[level, metric] = top
            values = [v['replay'].cs / 100 if metric == 'time' else
                      v['replay'].bv * 100 / v['replay'].cs if metric == 'bvs' else v['replay'].stnb for v in top]
            # Original clear_data pads missing slots with 10/60/240 seconds,
            # and zero bvs/stnb. Denominators remain fixed at 20/12/5.
            total = math.fsum(values) + (n - len(top)) * (TIME_PADDING[level] if metric == 'time' else 0)
            totals[metric], averages[metric] = total, total / n
        scores[level] = dict(selected=len(selected), available=len(candidates), required=n, complete=len(candidates) >= n,
                             totals=totals, averages=averages)
    ep = baseline['Exp'][1] * baseline['Exp'][2] / baseline['Exp'][0]
    points = {}
    for level in COUNTS:
        a = scores[level]['averages']
        raw = a['bvs'] * a['stnb'] / a['time'] if a['time'] else 0
        norm = baseline[level][1] * baseline[level][2] / baseline[level][0]
        points[level] = raw / norm * ep if level != 'Exp' else raw
        scores[level]['points'] = points[level]
    combined = dict(T37=sum(s['totals']['time'] for s in scores.values()),
                    B37=sum(s['totals']['bvs'] for s in scores.values()),
                    PPP37=(points['Beg'] * points['Int'] * points['Exp']) ** (1 / 3),
                    complete=all(s['complete'] for s in scores.values()))
    return rankings, scores, combined


def run_gsc(inputs, output, edition, start, end, suffix, emit, stop, recursive=True,
            check_completion=False, time_basis='recorded', baseline=None, workers=4):
    baseline = baseline or reference_settings()['baseline']
    roots, output, begin, finish = validate(inputs, output, edition, start, end, suffix, baseline, time_basis)
    suffix = suffix.strip()
    dest = output / f'金羊杯{int(edition)}' / datetime.now().strftime('计算_%Y%m%d_%H%M%S_%f')
    dest.mkdir(parents=True)
    started = time.monotonic()
    stats = dict(total=0, processed=0, matched=0, duplicates=0, outside_time=0,
                 wrong_suffix=0, low_bv=0, beginner_below10=0, unverified=0, unsupported=0, failed=0,
                 selected_copied=0, top_total=0, top_copied=0, warnings=0)
    warnings, records, top_report, selected_report = [], [], [], []
    scores, combined = {}, {}
    status = 'failed'

    def check():
        if stop.is_set():
            raise Cancelled()

    def progress(phase):
        emit('gsc_progress', dict(stats, phase=phase, directory=str(dest), seconds=time.monotonic() - started))

    def warn(message):
        warnings.append(message)
        stats['warnings'] = len(warnings)
        emit('log', 'WARNING: ' + message)

    def write_csv(name, rows, fields):
        with (dest / name).open('w', encoding='utf-8-sig', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore')
            writer.writeheader()
            writer.writerows(rows)

    try:
        files, stack, visited = [], list(roots), set()
        tick = time.monotonic()
        progress('扫描录像')
        while stack:
            check()
            folder = stack.pop()
            if folder in visited or folder.is_relative_to(output):
                continue
            visited.add(folder)
            try:
                with os.scandir(folder) as entries:
                    for entry in entries:
                        check()
                        if entry.is_file(follow_symlinks=False) and entry.name.lower().endswith('.avf'):
                            files.append(Path(entry.path))
                        elif recursive and entry.is_dir(follow_symlinks=False) and not Path(entry.path).is_junction():
                            stack.append(Path(entry.path))
                        if time.monotonic() - tick > .2:
                            stats['total'] = len(files)
                            progress('扫描录像')
                            tick = time.monotonic()
            except OSError as ex:
                warn(f'无法扫描 {folder}: {ex}')
        files.sort(key=lambda p: str(p).casefold())
        stats['total'] = len(files)
        progress('筛选参赛录像')
        seen = set()

        def parse(path):
            try:
                r = parse_avf(path, check_completion=check_completion)
                at = parse_datetime(r.recorded_at) if time_basis == 'recorded' else datetime.fromtimestamp(path.stat().st_mtime)
                return path, r, at, None
            except BaseException as ex:
                if isinstance(ex, (KeyboardInterrupt, SystemExit)):
                    raise
                return path, None, None, str(ex)

        with ThreadPoolExecutor(max_workers=max(1, min(16, workers))) as pool:
            for offset in range(0, len(files), 128):
                check()
                for path, r, at, error in pool.map(parse, files[offset:offset + 128]):
                    check()
                    stats['processed'] += 1
                    if error:
                        stats['failed'] += 1
                        warn(f'{path}: {error}')
                    elif r.level not in COUNTS:
                        stats['unsupported'] += 1
                    elif not begin <= at.replace(microsecond=0) <= finish:
                        stats['outside_time'] += 1
                    elif not r.player.endswith(suffix):
                        stats['wrong_suffix'] += 1
                    elif r.bv < SELECTION_BV_LIMITS[r.level]:
                        stats['low_bv'] += 1
                    elif not r.completed:
                        stats['unverified'] += 1
                        warn(f'完成状态待核验，未纳入: {path}')
                    else:
                        digest = hashlib.sha256(path.read_bytes()).digest()
                        if digest in seen:
                            stats['duplicates'] += 1
                        else:
                            seen.add(digest)
                            records.append(dict(path=path, replay=r, at=at, digest=digest))
                            stats['matched'] += 1
                            if r.level == 'Beg' and r.bv < 10:
                                stats['beginner_below10'] += 1
                    if stats['processed'] % 64 == 0 or time.monotonic() - tick > .2:
                        progress('筛选参赛录像')
                        tick = time.monotonic()
        rankings, scores, combined = rank_and_score(records, baseline)
        stats['top_total'] = sum(len(v) for v in rankings.values())
        for level, s in scores.items():
            if not s['complete']:
                warn(f'{level} 仅 {s["available"]} 份有效录像，不足 Top{s["required"]}；按原工具补位规则生成暂定成绩')
        if not records:
            warn('没有符合筛选条件的参赛录像')

        def export(v, folder, prefix=''):
            check()
            r, path = v['replay'], v['path']
            folder.mkdir(parents=True, exist_ok=True)
            target = folder / (prefix + r.filename)
            # Different recordings can have the same metadata and canonical name.
            from common.core import available_name
            target = available_name(target)
            row = dict(level=r.level, time=r.cs / 100, bv=r.bv, bvs=r.bv * 100 / r.cs,
                stnb=r.stnb, player=r.player, recorded_at=r.recorded_at,
                filter_time=v['at'].isoformat(), ranking_eligible=r.bv >= BV_LIMITS[r.level],
                sha256=v['digest'].hex(), source=str(path), output=str(target), status='copied')
            try:
                copy_replay(path, target, v['digest'])
            except OSError as ex:
                row['status'] = 'failed'
                warn(f'复制失败 {path}: {ex}')
            return row

        for v in records:
            row = export(v, dest / '参赛录像' / v['replay'].level)
            selected_report.append(row)
            stats['selected_copied'] += int(row['status'] == 'copied')
            progress('复制参赛录像')
        for (level, metric), top in rankings.items():
            for rank, v in enumerate(top, 1):
                row = export(v, dest / 'TopX' / level / metric, f'{rank:02d}_')
                row.update(metric=metric, rank=rank)
                top_report.append(row)
                stats['top_copied'] += int(row['status'] == 'copied')
                progress('复制 TopX')
        status = 'completed'
    except Cancelled:
        status = 'cancelled'
        warn('已取消；已完成的复制和报告保留')
    except Exception as ex:
        warn(f'任务中止: {ex}')
        raise
    finally:
        fields = ['level', 'time', 'bv', 'bvs', 'stnb', 'player', 'recorded_at', 'filter_time', 'ranking_eligible', 'sha256', 'source', 'output', 'status']
        write_csv('参赛录像.csv', selected_report, fields)
        write_csv('TopX.csv', top_report, ['metric', 'rank'] + fields)
        score_rows = [dict(level=level, metric=m, required=s['required'], available=s['available'],
            total=s['totals'][m], average=s['averages'][m], complete=s['complete'])
            for level, s in scores.items() for m in METRICS]
        write_csv('成绩.csv', score_rows, ['level', 'metric', 'required', 'available', 'total', 'average', 'complete'])
        combined_rows = [dict(item={'Beg': 'BPP20', 'Int': 'IPP12', 'Exp': 'EPP5'}[level],
                             value=s['points']) for level, s in scores.items()]
        combined_rows += [dict(item=k, value=v) for k, v in combined.items() if k != 'complete']
        write_csv('综合成绩.csv', combined_rows, ['item', 'value'])
        summary = dict(stats, status=status, edition=int(edition), start=begin.isoformat(), end=finish.isoformat(),
            suffix=suffix, time_basis=time_basis, check_completion=check_completion, bv_limits=BV_LIMITS,
            selection_bv_limits=SELECTION_BV_LIMITS,
            baseline=baseline, scores=scores, combined=combined, seconds=time.monotonic() - started)
        (dest / '成绩.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
        display_result = dict(summary, top_rows=top_report)
        page = render_html(display_result)
        (dest / '成绩.html').write_text(page, encoding='utf-8')
        (dest / 'warnings.txt').write_text('\n'.join(warnings), encoding='utf-8-sig')
        emit('gsc_scores', display_result)
        progress({'completed': '完成', 'cancelled': '已取消', 'failed': '失败'}[status])
    return dest, summary
