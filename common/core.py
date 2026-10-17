"""PB-master compatible AVF parsing and linear-time PB selection."""
from __future__ import annotations
import re
import json
import hashlib
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, ROUND_DOWN
from pathlib import Path
from common.paths import DATA_DIR
import math
import ms_toollib as ms

LEVELS = ('Beg', 'Int', 'Exp', 'Cus')


@dataclass(frozen=True)
class Replay:
    level: str
    style: str
    cs: int
    bv: int
    player: str
    day: str
    completion: float = 1.0
    completed: bool = True
    verification: str = 'simulated'
    recorded_at: str = ''

    @property
    def stnb(self):
        if not self.completed:
            return None
        constant = {'Beg': 36, 'Int': 162, 'Exp': 435}.get(self.level)
        if constant is None:
            return None
        return math.sqrt(self.completion) * constant * self.bv / (self.cs / 100) ** 1.7

    @property
    def filename(self):
        speed = (Decimal(self.bv * 100) / self.cs).quantize(Decimal('.01'), rounding=ROUND_DOWN)
        player = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', self.player).strip(' .')[:110] or 'Unknown'
        stnb = f'{self.stnb:.3f}' if self.stnb is not None else 'NA'
        return f'{self.level}_{self.style}_{self.cs / 100:06.2f}_3BV={self.bv}_3BVs={speed}_STNB={stnb}_{player}.avf'


def parse_avf(path: Path, check_completion=True) -> Replay:
    d = path.read_bytes()
    if len(d) < 30 or d[5] not in (3, 4, 5, 6):
        raise ValueError('无效或不支持的 AVF 文件头')
    mode = d[5] - 2
    mines = (10, 40, 99, 0)[mode - 1]
    offset = 6
    if mode == 4:
        mines = int.from_bytes(d[8:10], 'big')
        offset = 10
    offset += mines * 2
    pat = rb'\[' + str(mode - 1).encode() + rb'\|([^\]]{1,180})\|B(\d+)T(\d+\.\d+)\]'
    match = re.search(pat, d[offset:offset + 4096])
    if not match:
        raise ValueError('未找到完整时间/3BV 信息（可能是失败录像）')
    cs = int((Decimal(match[3].decode()) - 1) * 100)
    bv = int(match[2])
    if cs <= 0 or bv <= 0:
        raise ValueError('时间或 3BV 非正数')
    stamp = match[1].split(b'|')[0].decode('ascii', errors='replace')
    dt = re.match(r'(\d{1,2})\.(\d{1,2})\.(\d{4})\.', stamp)
    if not dt:
        raise ValueError(f'无法识别录像日期: {stamp}')
    day = datetime(int(dt[3]), int(dt[2]), int(dt[1])).date().isoformat()
    clock = re.match(r'\d{1,2}\.\d{1,2}\.\d{4}\.(\d{1,2}):(\d{1,2}):(\d{1,2})(?::(\d+))?', stamp)
    recorded_at = ''
    if clock:
        # Arbiter's four-digit subsecond field contains an extra leading digit;
        # retain the final three milliseconds, as its timestamp reader does.
        ms_part = int((clock[4] or '0')[-3:])
        recorded_at = datetime(int(dt[3]), int(dt[2]), int(dt[1]), int(clock[1]),
            int(clock[2]), int(clock[3]), ms_part * 1000).isoformat(timespec='milliseconds')
    pos = offset + match.end()
    # Identical event alignment and NF/FL criteria to rename.c.
    start = next((i - 2 for i in range(pos + 2, len(d)) if d[i] == 1 and d[i - 1] <= 1), None)
    if start is None:
        raise ValueError('缺少鼠标事件')
    fl, events, pos = False, 0, start
    while pos + 8 <= len(d):
        block = d[pos:pos + 8]
        if block[6] * 256 + block[2] - 1 < 0:
            break
        fl |= block[0] not in (1, 3, 5, 21)
        events += 1
        pos += 8
    else:
        raise ValueError('鼠标事件未正常结束')
    checksum = d.find(b'cs=', pos)
    if checksum < 0:
        raise ValueError('缺少录像校验尾部')
    pos = checksum + 3
    if d[0] == 0:
        pos += events + 17
        end = d.find(b'\r', pos)
        if end < 0:
            raise ValueError('不完整的 Freesweeper 尾部')
        pos = end + 1
    else:
        pos += 17
    player = None
    for line in d[pos:].split(b'\r'):
        if b'<' in line:
            player = line.split(b'<', 1)[0]
            break
        if b':' not in line:
            player = line
            break
    if not player:
        raise ValueError('缺少玩家名称')
    for enc in ('utf-8', 'gb18030', 'cp1252'):
        try:
            name = player.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if not check_completion:
        return Replay(LEVELS[mode - 1], 'FL' if fl else 'NF', cs, bv, name, day,
                      1.0, True, 'assumed_complete', recorded_at)
    video = ms.AvfVideo(str(path))
    video.parse()
    video.analyse()
    video.current_time = video.video_end_time
    completed = video.is_completed
    verification = 'simulated' if completed else 'unverified'
    # A failure to reproduce the game is not proof the recorded game failed.
    # Explicit user confirmations are keyed by content hash, never by filename.
    if not completed:
        try:
            manifest = json.loads((DATA_DIR / 'confirmed_completed.json').read_text(encoding='utf-8'))
        except FileNotFoundError:
            manifest = {}
        if hashlib.sha256(d).hexdigest() in manifest:
            completed = True
            verification = 'user_confirmed'
    completion = 1.0 if completed else 0.0
    return Replay(LEVELS[mode - 1], 'FL' if fl else 'NF', cs, bv, name, day,
                  completion, completed, verification, recorded_at)


class Cancelled(Exception):
    pass


def available_name(path, source=None):
    base, i = path, 0
    while path.exists():
        if source is not None and path == source:
            return path
        i += 1
        path = base.with_name(f'{base.stem}_({i:03d}){base.suffix}')
    return path
