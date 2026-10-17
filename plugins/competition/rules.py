"""Shared competition parameters used for ranking and score displays."""
import re

DEFAULT_TOP_COUNTS = {'Beg': 20, 'Int': 12, 'Exp': 5}
MAX_TOP_COUNT = 1000


def validate_name(value):
    name = str(value).strip()
    if not name or name in ('.', '..') or name.endswith('.'):
        raise ValueError('请输入有效的比赛名称')
    if re.search(r'[<>:"/\\|?*\x00-\x1f]', name):
        raise ValueError('比赛名称不能包含文件夹名称不允许的字符：<>:"/\\|?*')
    reserved = {'CON','PRN','AUX','NUL'} | {f'{prefix}{i}' for prefix in ('COM','LPT') for i in range(1,10)}
    if name.split('.')[0].upper() in reserved:
        raise ValueError('比赛名称不能使用Windows保留名称')
    return name


def normalize_counts(values=None):
    values = DEFAULT_TOP_COUNTS if values is None else values
    counts = {}
    for level in DEFAULT_TOP_COUNTS:
        raw = values.get(level, '')
        if not re.fullmatch(r'[1-9][0-9]*', str(raw).strip()) or not 1 <= int(raw) <= MAX_TOP_COUNT:
            raise ValueError(f'{level}的Top数量应为1–{MAX_TOP_COUNT}的整数')
        counts[level] = int(raw)
    return counts


def result_counts(summary):
    scores = summary.get('scores', {})
    return normalize_counts(summary.get('top_counts') or {
        level: scores.get(level, {}).get('required', default)
        for level, default in DEFAULT_TOP_COUNTS.items()})
