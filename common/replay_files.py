"""Shared byte-preserving replay copy operation."""
import hashlib
import shutil
import csv
from common.core import available_name


def copy_replay(source, target, expected_digest):
    """Only create a new destination; source is always opened read-only."""
    digest = hashlib.sha256()
    with source.open('rb') as reader, target.open('xb') as writer:
        while chunk := reader.read(1024 * 1024):
            writer.write(chunk)
            digest.update(chunk)
    if digest.digest() != expected_digest:
        raise OSError('复制期间源录像发生外部变化，副本哈希与扫描时不一致')
    shutil.copystat(source, target)


def export_flat_collections(collections, root, stats, check, warn, progress):
    """Create each group's ALL directory, deduplicated across levels/metrics."""
    groups = {}
    for group, candidates in collections.items():
        unique = {}
        for source, replay, digest in candidates:
            if replay.level in ('Beg', 'Int', 'Exp'):
                unique.setdefault(digest, (source, replay))
        groups[group] = unique
    stats['flat_total'] = sum(len(items) for items in groups.values())
    rows = []
    try:
        progress('复制 ALL 合集')
        for group, items in groups.items():
            check()
            folder = root / group / 'ALL'
            folder.mkdir(parents=True, exist_ok=True)
            for digest, (source, replay) in items.items():
                check()
                target = available_name(folder / replay.filename)
                row = dict(group=str(group), level=replay.level, sha256=digest.hex(),
                           source=str(source), output=str(target), status='copied', message='')
                try:
                    copy_replay(source, target, digest)
                    stats['flat_copied'] += 1
                except OSError as ex:
                    row.update(status='failed', message=str(ex))
                    warn(f'ALL 合集复制失败 {source}: {ex}')
                rows.append(row)
                stats['flat_checked'] += 1
                progress('复制 ALL 合集')
    finally:
        with (root / 'all_export.csv').open('w', encoding='utf-8-sig', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=['group','level','sha256','source','output','status','message'])
            writer.writeheader()
            writer.writerows(rows)
