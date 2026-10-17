"""Concurrent scanning, persistent metadata cache, PB/Top5 export."""
import csv
import hashlib
import json
import os
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
from datetime import datetime
from pathlib import Path
from common.paths import DATA_DIR, prepare_data_dir

from common.core import Replay, parse_avf, available_name, Cancelled
from common.replay_files import copy_replay, export_flat_collections

CACHE_VERSION = '4'



def run(inputs, output, emit, stop, recursive=True, rename=True, workers=4, cache_path=None,
        check_completion=False, flat_export=False):
    started = time.perf_counter()
    output = Path(output).resolve()
    roots = list(dict.fromkeys(Path(p).resolve() for p in inputs))
    if not roots:
        raise ValueError('请添加输入目录')
    for p in roots:
        if not p.is_dir():
            raise ValueError(f'输入目录不存在: {p}')
        if p == output or p.is_relative_to(output):
            raise ValueError('输入目录不能等于输出目录或位于输出目录内')
    output.mkdir(parents=True, exist_ok=True)
    dest = output / datetime.now().strftime('PB_%Y%m%d_%H%M%S_%f')
    dest.mkdir()
    for category in ('FL', 'NF', 'ALL'):
        for kind in ('PB', 'Top5'):
            (dest / category / kind).mkdir(parents=True)
    stats = dict(total=0, processed=0, renamed=0, unchanged=0, failed=0, unverified=0,
                 bv=0, pb=0, pb_copied=0, top_total=0, top_found=0, top_checked=0,
                 warnings=0, cached=0, flat_total=0, flat_copied=0, flat_checked=0)
    warnings, pb_rows, top_rows, review_rows = [], [], [], []
    if cache_path is None:
        prepare_data_dir()
    cache = sqlite3.connect(cache_path or DATA_DIR / 'metadata.sqlite3')
    cache.execute('CREATE TABLE IF NOT EXISTS replay (path TEXT PRIMARY KEY, size INTEGER, mtime INTEGER, version TEXT, data TEXT)')
    # Previously reproduced wins remain valid; all previous negative judgments
    # must be rechecked under the new confirmation/unknown-state policy.
    cache.execute("UPDATE replay SET version=? WHERE version='3' AND json_extract(data, '$.completed')=1", (CACHE_VERSION,))
    cache.commit()
    mode_version = CACHE_VERSION if check_completion else CACHE_VERSION + ':assumed'

    def check():
        if stop.is_set():
            raise Cancelled()

    def warn(msg):
        warnings.append(msg)
        stats['warnings'] = len(warnings)
        emit('log', 'WARNING: ' + msg)

    def progress(phase):
        emit('progress', dict(stats, flat_export=flat_export, phase=phase, seconds=time.perf_counter() - started, directory=str(dest)))

    def remember(path, r):
        st = path.stat()
        cache.execute('INSERT OR REPLACE INTO replay VALUES (?,?,?,?,?)',
                      (str(path), st.st_size, st.st_mtime_ns, mode_version, json.dumps(asdict(r))))

    def csv_report(name, rows, fields):
        with (dest / name).open('w', encoding='utf-8-sig', newline='') as f:
            w = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore')
            w.writeheader()
            w.writerows(rows)

    status = 'failed'
    try:
        progress('扫描录像')
        files, visited, stack = [], set(), list(roots)
        last_update = time.monotonic()
        while stack:
            check()
            folder = stack.pop()
            if folder in visited or folder.is_relative_to(output):
                continue
            visited.add(folder)
            try:
                with os.scandir(folder) as entries:
                    for e in entries:
                        check()
                        if e.is_file(follow_symlinks=False) and e.name.lower().endswith('.avf'):
                            files.append(Path(e.path))
                        elif recursive and e.is_dir(follow_symlinks=False) and not Path(e.path).is_junction():
                            stack.append(Path(e.path))
                        if time.monotonic() - last_update > .2:
                            stats['total'] = len(files)
                            progress('扫描录像')
                            last_update = time.monotonic()
            except OSError as ex:
                warn(f'无法扫描 {folder}: {ex}')
        files.sort(key=lambda p: str(p).casefold())
        stats['total'] = len(files)
        progress('解析与重命名')
        if not files:
            warn('所选目录中没有找到 .avf 录像')
        best, tops, fingerprints, source_digests = {}, {}, {}, {}

        def parse(item):
            path, cached = item
            if cached:
                replay = Replay(**json.loads(cached))
                if not check_completion:
                    replay = replace(replay, completion=1.0, completed=True, verification='assumed_complete')
                return path, replay, None, True
            try:
                replay = parse_avf(path) if check_completion else parse_avf(path, check_completion=False)
                return path, replay, None, False
            except BaseException as ex:
                # Rust parser may raise PanicException (a BaseException subclass).
                if isinstance(ex, (KeyboardInterrupt, SystemExit)):
                    raise
                return path, None, f'{type(ex).__name__}: {ex}', False

        with (dest / 'rename_log.csv').open('w', encoding='utf-8-sig', newline='') as journal:
            writer = csv.DictWriter(journal, fieldnames=['old', 'new', 'status'])
            writer.writeheader()
            with ThreadPoolExecutor(max_workers=max(1, min(workers, 16))) as pool:
                for offset in range(0, len(files), 128):
                    check()
                    batch = []
                    for p in files[offset:offset + 128]:
                        try:
                            st = p.stat()
                            valid_versions = (CACHE_VERSION, CACHE_VERSION) if check_completion else (CACHE_VERSION, mode_version)
                            row = cache.execute('SELECT data FROM replay WHERE path=? AND size=? AND mtime=? AND version IN (?,?)',
                                                (str(p), st.st_size, st.st_mtime_ns, *valid_versions)).fetchone()
                            batch.append((p, row[0] if row else None))
                        except OSError as ex:
                            warn(f'{p}: {ex}')
                            stats['processed'] += 1
                            stats['failed'] += 1
                    for p, r, error, cached in pool.map(parse, batch):
                        check()
                        stats['processed'] += 1
                        if error:
                            stats['failed'] += 1
                            warn(f'{p}: {error}')
                        else:
                            stats['cached'] += int(cached)
                            if rename:
                                try:
                                    target = available_name(p.with_name(r.filename), p)
                                    if target != p:
                                        # Journal intent before rename; record completion separately.
                                        writer.writerow(dict(old=str(p), new=str(target), status='planned'))
                                        journal.flush()
                                        p.rename(target)
                                        writer.writerow(dict(old=str(p), new=str(target), status='done'))
                                        journal.flush()
                                        p = target
                                        stats['renamed'] += 1
                                    else:
                                        stats['unchanged'] += 1
                                except OSError as ex:
                                    warn(f'重命名失败 {p}: {ex}')
                            else:
                                stats['unchanged'] += 1
                            remember(p, r)
                            if not r.completed:
                                stats['unverified'] += 1
                                review_rows.append(dict(path=str(p), level=r.level, bv=r.bv,
                                    time=r.cs / 100, day=r.day, status='unverified'))
                                warn(f'完成状态待核验（不是判定未完成）: {p}；解析器未能复现胜利，暂不纳入榜单')
                            else:
                                # SHA256 removes duplicate videos across overlapping collections.
                                digest = hashlib.sha256(p.read_bytes()).digest()
                                if digest not in fingerprints:
                                    fingerprints[digest] = p
                                    source_digests[p] = digest
                                    for cat in (r.style, 'ALL'):
                                        key = (cat, r.level, r.bv)
                                        if key not in best or r.cs < best[key][1].cs:
                                            best[key] = (p, r)
                                        for metric in ('time', 'bvs', 'stnb'):
                                            if r.level == 'Beg' and r.bv < 10:
                                                continue
                                            if metric == 'stnb' and r.stnb is None:
                                                continue
                                            k = (cat, r.level, metric)
                                            rows = tops.setdefault(k, [])
                                            rows.append((p, r))
                                            rows.sort(key=lambda v: (
                                                v[1].cs if metric == 'time' else
                                                -v[1].bv / (v[1].cs / 100) if metric == 'bvs' else -v[1].stnb,
                                                str(v[0]).casefold()))
                                            del rows[5:]
                            stats['bv'] = len({(level, bv) for _, level, bv in best})
                            stats['pb'] = len(best)
                        if stats['processed'] % 32 == 0 or time.monotonic() - last_update > .2:
                            progress('解析与重命名')
                            last_update = time.monotonic()
                    cache.commit()
        stats['top_total'] = sum(len(v) for v in tops.values())
        progress('复制 PB')
        for (cat, level, bv), (p, r) in sorted(best.items()):
            check()
            folder = dest / cat / 'PB' / level
            folder.mkdir(parents=True, exist_ok=True)
            target = folder / r.filename
            try:
                copy_replay(p, target, source_digests[p])
                stats['pb_copied'] += 1
                pb_rows.append(dict(category=cat, level=level, bv=bv, time=r.cs / 100,
                    stnb=r.stnb, source=str(p), output=str(target)))
            except OSError as ex:
                warn(f'PB 复制失败 {p}: {ex}')
            progress('复制 PB')
        for (cat, level, metric), rows in sorted(tops.items()):
            if len(rows) < 5:
                warn(f'{cat}/{level}/{metric} 仅 {len(rows)} 个不同的成功录像，不足 Top5')
            folder = dest / cat / 'Top5' / level / metric
            folder.mkdir(parents=True, exist_ok=True)
            for rank, (p, r) in enumerate(rows, 1):
                check()
                target = folder / f'{rank:02d}_{r.filename}'
                row = dict(category=cat, level=level, metric=metric, rank=rank,
                    bv=r.bv, time=r.cs / 100, bvs=r.bv / (r.cs / 100), stnb=r.stnb,
                    source=str(p), output=str(target), status='found')
                try:
                    copy_replay(p, target, source_digests[p])
                    stats['top_found'] += 1
                except OSError as ex:
                    row['status'] = 'missing'
                    warn(f'Top5 文件不可用 {p}: {ex}')
                stats['top_checked'] += 1
                top_rows.append(row)
                progress('复制 Top5')
        if flat_export:
            collections = {Path(cat) / kind: [] for cat in ('FL','NF','ALL') for kind in ('PB','Top5')}
            for (cat, level, bv), (p, r) in sorted(best.items()):
                collections[Path(cat) / 'PB'].append((p, r, source_digests[p]))
            for (cat, level, metric), items in sorted(tops.items()):
                collections[Path(cat) / 'Top5'].extend((p, r, source_digests[p]) for p, r in items)
            export_flat_collections(collections, dest, stats, check, warn, progress)
        status = 'completed'
    except Cancelled:
        status = 'cancelled'
        warn('用户已取消；已完成的重命名和复制保留，详见日志')
    except Exception as ex:
        warn(f'任务中止: {ex}')
        raise
    finally:
        cache.commit()
        cache.close()
        csv_report('pb.csv', pb_rows, ['category', 'level', 'bv', 'time', 'stnb', 'source', 'output'])
        csv_report('top5.csv', top_rows, ['category', 'level', 'metric', 'rank', 'bv', 'time', 'bvs', 'stnb', 'source', 'output', 'status'])
        csv_report('needs_review.csv', review_rows, ['path', 'level', 'bv', 'time', 'day', 'status'])
        (dest / 'warnings.txt').write_text('\n'.join(warnings), encoding='utf-8-sig')
        summary = dict(stats, status=status, check_completion=check_completion, flat_export=flat_export,
                       seconds=round(time.perf_counter() - started, 3))
        (dest / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
        progress({'completed': '完成', 'cancelled': '已取消', 'failed': '失败'}[status])
    return dest, stats
