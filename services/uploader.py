"""saolei.wang protocol recovered from 自动上传/upload.jar (App.post/postUpload).
Only opens source replays for reading. No real upload happens on import.
"""
import csv
import hashlib
import html
import http.cookiejar
import json
import os
import re
import sqlite3
import time
import uuid
from datetime import datetime
from pathlib import Path
from common.paths import DATA_DIR, prepare_data_dir
from urllib.parse import urlencode, urlsplit
from urllib.request import build_opener, HTTPCookieProcessor, Request, HTTPRedirectHandler

from common.core import parse_avf, Cancelled

SITE = 'http://www.saolei.wang'
BASE = DATA_DIR


def response_text(data):
    try:
        return data.decode('utf-8')
    except UnicodeDecodeError:
        return data.decode('gb18030', errors='replace')


def plain(text):
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', text))).strip()[:1500]


def classify(text):
    # A 200 response alone never means the site accepted a replay.
    compact = re.sub(r'\s+', '', plain(text))
    if any(s in compact for s in ('上传失败', '上传不成功', '上传未成功', '上传没有成功', '密码错误', '请先登录', '尚未登录')):
        return 'failed'
    if any(s in compact for s in ('已经存在', '已存在', '重复上传', '已经上传', '已上传过')):
        return 'existing'
    # The live ASP endpoint signals success by JavaScript redirect, without
    # any Chinese success message: parent.location.href='/Video/Upload_OK.asp';
    if re.search(r'''location(?:\.href)?\s*=\s*["'](?:https?://www\.saolei\.wang)?/Video/Upload_OK\.asp(?:[?#][^"']*)?["']''',
                 html.unescape(text), re.IGNORECASE):
        return 'uploaded'
    if any(s in compact for s in ('上传成功', '上传录像成功', '录像上传成功', '上传完成')):
        return 'uploaded'
    return 'uncertain'


class SameSiteRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        old, new = urlsplit(req.full_url), urlsplit(newurl)
        if (old.scheme, old.netloc) != (new.scheme, new.netloc):
            raise ValueError('拒绝跨站点重定向')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class SiteClient:
    def __init__(self, site=SITE, timeout=25):
        self.site = site.rstrip('/')
        self.timeout = timeout
        self.opener = build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()), SameSiteRedirect())

    def request(self, path, body=None, content_type=None, referer=None):
        headers = {'User-Agent': 'Mozilla/5.0 MinesweeperPBTool/0.1', 'Accept-Language': 'zh-CN'}
        if content_type:
            headers['Content-Type'] = content_type
        if referer:
            headers['Referer'] = self.site + referer
        request = Request(self.site + path, data=body, headers=headers)
        with self.opener.open(request, timeout=self.timeout) as response:
            # Refuse login/upload redirects to another host.
            if not response.geturl().startswith(self.site + '/'):
                raise ValueError('网站重定向至其他站点，已停止')
            return response_text(response.read(2 * 1024 * 1024))

    def login(self, username, password):
        body = urlencode({'Player_Name': username, 'Player_Password': password}).encode('utf-8')
        text = self.request('/player/Action/Login_Action.asp', body,
                            'application/x-www-form-urlencoded')
        if any(s in text for s in ('密码错误', '密码不正确', '登录失败', '用户名不存在', '用户不存在')):
            raise ValueError('雷网登录失败，请检查账号密码')
        # Confirm the authenticated upload form instead of assuming a cookie means success.
        page = self.request('/Video/Upload_Input.asp?Model=Beg')
        if 'Video_3BV' not in page or not re.search(r'(?i)name\s*=\s*[\"\x27]?Video(?:[\"\x27\s>])', page):
            raise ValueError('未取得已登录的上传表单；请检查账号密码或网站是否变更')

    def upload(self, data, replay):
        boundary = '----PBTool' + uuid.uuid4().hex
        fields = {'Video_3BV': str(replay.bv), 'Video_Score': f'{replay.cs / 100:.2f}',
                  'Video_IsNoFrag': '1' if replay.style == 'NF' else '',
                  'Video_Model': replay.level, 'Video_Id': '0'}
        parts = []
        for key, value in fields.items():
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode('ascii'))
        # ASCII transport filename avoids old ASP multipart filename encoding issues.
        # The raw AVF byte sequence below is never transformed.
        filename = f'{replay.level}_{replay.cs}_{replay.bv}.avf'
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="Video"; filename="{filename}"\r\nContent-Type: application/octet-stream\r\n\r\n'.encode('ascii'))
        parts += [data, f'\r\n--{boundary}--\r\n'.encode('ascii')]
        return self.request('/Video/Action/Upload_Action.asp', b''.join(parts),
                            f'multipart/form-data; boundary={boundary}',
                            '/Video/Upload_Input.asp?Model=' + replay.level)


class AuthenticationError(RuntimeError):
    pass


def upload_directory(directory, username, password, emit, stop, recursive=True,
                     skip_uploaded=True, report_root=None, history_path=None, client_factory=SiteClient):
    directory = Path(directory).resolve()
    if not directory.is_dir():
        raise ValueError('上传目录不存在')
    if not username.strip() or not password:
        raise ValueError('请输入雷网账号和密码')
    username = username.strip()
    if report_root is None or history_path is None:
        prepare_data_dir()
    started = time.perf_counter()
    report_root = Path(report_root or BASE / 'upload_reports')
    dest = report_root / datetime.now().strftime('Upload_%Y%m%d_%H%M%S_%f')
    if dest == directory or directory.is_relative_to(report_root.resolve()):
        raise ValueError('上传目录不能放在上传报告目录内')
    dest.mkdir(parents=True)
    stats = dict(total=0, processed=0, uploaded=0, existing=0, skipped=0, failed=0, uncertain=0)
    db = sqlite3.connect(history_path or BASE / 'upload_history.sqlite3')
    db.execute('CREATE TABLE IF NOT EXISTS uploads (account TEXT, digest TEXT, status TEXT, at TEXT, PRIMARY KEY(account,digest))')
    rows, seen, client = [], set(), None
    status = 'failed'

    def check():
        if stop.is_set():
            raise Cancelled()

    def progress(phase):
        emit('upload_progress', dict(stats, phase=phase, directory=str(dest), seconds=time.perf_counter() - started))

    def redact(value):
        return str(value).replace(password, '[密码已隐藏]')

    try:
        progress('扫描上传目录')
        files, stack = [], [directory]
        tick = time.monotonic()
        while stack:
            check()
            folder = stack.pop()
            if folder.is_relative_to(report_root.resolve()):
                continue
            with os.scandir(folder) as entries:
                for entry in entries:
                    check()
                    if entry.is_file(follow_symlinks=False) and entry.name.lower().endswith('.avf'):
                        files.append(Path(entry.path))
                    elif recursive and entry.is_dir(follow_symlinks=False) and not Path(entry.path).is_junction():
                        stack.append(Path(entry.path))
                    stats['total'] = len(files)
                    if time.monotonic() - tick > .2:
                        progress('扫描上传目录')
                        tick = time.monotonic()
        files.sort(key=lambda p: str(p).casefold())
        if not files:
            emit('log', '上传目录中没有 AVF 录像')
        for path in files:
            check()
            row = dict(path=str(path), sha256='', status='', message='')
            try:
                data = path.read_bytes()
                digest = hashlib.sha256(data).hexdigest()
                row['sha256'] = digest
                previous = db.execute('SELECT status FROM uploads WHERE account=? AND digest=?', (username, digest)).fetchone()
                if digest in seen or skip_uploaded and previous and previous[0] in ('uploaded', 'existing'):
                    row.update(status='skipped', message='本次内容重复或该账号已有成功/已存在记录')
                else:
                    seen.add(digest)
                    try:
                        replay = parse_avf(path, check_completion=False)
                    except BaseException as ex:
                        if isinstance(ex, (KeyboardInterrupt, SystemExit)):
                            raise
                        raise ValueError('录像解析失败: ' + type(ex).__name__ + ': ' + str(ex)) from None
                    if path.read_bytes() != data:
                        raise ValueError('源录像被外部更改，已跳过')
                    if replay.level == 'Cus':
                        row.update(status='skipped', message='与原上传工具一致，仅支持标准初/中/高级录像')
                    else:
                        if client is None:
                            progress('登录雷网')
                            client = client_factory()
                            # A login failure aborts the batch, avoiding one failure per file.
                            try:
                                client.login(username, password)
                            except Exception:
                                client = None
                                raise AuthenticationError('登录失败：请检查账号密码或雷网连接；未上传录像') from None
                        check()
                        progress('正在上传')
                        try:
                            text = client.upload(data, replay)
                            row.update(status=classify(text), message=redact(plain(text)))
                        except Exception as ex:
                            row.update(status='uncertain', message='请求中断，服务器是否收录未知（不自动重试）: ' + redact(ex))
                        if row['status'] in ('uploaded', 'existing'):
                            db.execute('INSERT OR REPLACE INTO uploads VALUES (?,?,?,?)',
                                       (username, digest, row['status'], datetime.now().isoformat()))
                            db.commit()
                stats[row['status']] += 1
            except AuthenticationError:
                raise
            except Cancelled:
                raise
            except Exception as ex:
                row.update(status='failed', message=redact(ex))
                stats['failed'] += 1
            rows.append(row)
            stats['processed'] += 1
            emit('log', f"{row['status']}: {path.name} {row['message'][:300]}")
            progress('正在上传')
            if row['status'] in ('uploaded', 'existing', 'uncertain'):
                stop.wait(.3)
        status = 'completed'
    except Cancelled:
        status = 'cancelled'
    except Exception as ex:
        emit('log', '上传停止: ' + redact(ex))
        raise
    finally:
        db.close()
        with (dest / 'upload.csv').open('w', encoding='utf-8-sig', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=['path', 'sha256', 'status', 'message'])
            writer.writeheader()
            writer.writerows(rows)
        (dest / 'summary.json').write_text(json.dumps(dict(stats, status=status,
            account=username, site=SITE), ensure_ascii=False, indent=2), encoding='utf-8')
        progress({'completed': '上传结束', 'cancelled': '上传已取消', 'failed': '上传失败'}[status])
    return dest, stats
