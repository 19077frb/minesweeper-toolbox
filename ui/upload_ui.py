import json
import os
import queue
import threading
import tkinter as tk
from pathlib import Path
from common.paths import DATA_DIR
from tkinter import ttk, filedialog, messagebox
from services.uploader import upload_directory
from common.settings_store import AutoSettings

BASE = DATA_DIR


class UploadPanel(ttk.Frame):
    def __init__(self, master, parent):
        super().__init__(master)
        self.parent = parent
        self.running = False
        self.stop = threading.Event()
        self.events = queue.Queue()
        self.latest = ''
        self.directory = tk.StringVar(value=parent.latest)
        self.username = tk.StringVar()
        self.password = tk.StringVar()
        self.recursive = tk.BooleanVar(value=True)
        self.skip = tk.BooleanVar(value=True)
        self.phase = tk.StringVar(value='选择输入文件夹，填写账号密码后，点击“开始上传”')
        self.counts = tk.StringVar(value='录像 0 / 0    上传成功 0    网站已存在 0    跳过 0    失败 0    待确认 0')
        outer = ttk.Frame(self, padding=12)
        outer.pack(fill='both', expand=True)
        ttk.Label(outer, text='自动上传录像', style='Title.TLabel').pack(anchor='w')
        ttk.Label(outer, text='上传目标：www.saolei.wang（与旧工具相同的 HTTP 接口；传输未加密）').pack(anchor='w', pady=8)
        ttk.Label(outer, text='只读取 AVF 原始字节，不改内容、不重命名；输入及选项（含账号密码）自动保存到本机 JSON。').pack(anchor='w')
        ttk.Label(outer, text='输入文件夹（上传其中的 AVF 录像）').pack(anchor='w', pady=(16, 5))
        row = ttk.Frame(outer)
        row.pack(fill='x')
        self.path_entry = ttk.Entry(row, textvariable=self.directory)
        self.path_entry.pack(side='left', fill='x', expand=True)
        ttk.Button(row, text='选择文件夹…', command=self.choose).pack(side='left', padx=(8, 0))
        ttk.Button(row, text='使用本次整理结果', command=self.use_pb_result).pack(side='left', padx=(8, 0))
        login = ttk.Frame(outer)
        login.pack(fill='x', pady=15)
        ttk.Label(login, text='雷网账号').pack(side='left')
        self.user_entry = ttk.Entry(login, textvariable=self.username, width=24)
        self.user_entry.pack(side='left', padx=8)
        ttk.Label(login, text='密码').pack(side='left', padx=(15, 0))
        self.pass_entry = ttk.Entry(login, textvariable=self.password, show='●', width=24)
        self.pass_entry.pack(side='left', padx=8)
        opts = ttk.Frame(outer)
        opts.pack(fill='x')
        ttk.Checkbutton(opts, text='递归子文件夹', variable=self.recursive).pack(side='left')
        ttk.Checkbutton(opts, text='跳过本机记录中该账号已上传成功的录像', variable=self.skip).pack(side='left', padx=20)
        ttk.Label(outer, text='相同内容的副本每批只提交一次。无法确认的服务器响应会标记“待确认”，不自动重试。').pack(anchor='w', pady=8)
        controls = ttk.Frame(outer)
        controls.pack(fill='x', pady=10)
        self.go = ttk.Button(controls, text='开始上传', command=self.start)
        self.go.pack(side='left')
        self.cancel = ttk.Button(controls, text='取消', command=self.stop.set, state='disabled')
        self.cancel.pack(side='left', padx=10)
        ttk.Button(controls, text='打开报告文件夹', command=self.open_report).pack(side='right')
        ttk.Label(outer, textvariable=self.phase, wraplength=900).pack(anchor='w')
        self.bar = ttk.Progressbar(outer, maximum=100)
        self.bar.pack(fill='x', pady=8)
        ttk.Label(outer, textvariable=self.counts, wraplength=900).pack(anchor='w')
        self.log = tk.Text(outer, wrap='word', height=10, state='disabled', font=('Microsoft YaHei UI', 9))
        self.log.pack(fill='both', expand=True, pady=(10, 0))
        try:
            c = json.loads((BASE / 'upload_settings.json').read_text(encoding='utf-8'))
            self.username.set(c.get('username', ''))
            self.password.set(c.get('password', ''))
            if not self.directory.get():
                self.directory.set(c.get('directory', ''))
            self.recursive.set(c.get('recursive', True))
            self.skip.set(c.get('skip', True))
        except (OSError, ValueError):
            pass
        self.settings = AutoSettings(self, BASE / 'upload_settings.json', self.settings_snapshot, parent.settings_status.set)
        self.settings.watch(self.directory, self.username, self.password, self.recursive, self.skip)
        self.after(100, self.poll)

    def settings_snapshot(self):
        return dict(directory=self.directory.get(), username=self.username.get(), password=self.password.get(),
                    recursive=self.recursive.get(), skip=self.skip.get())

    def choose(self):
        if not self.running:
            p = filedialog.askdirectory(parent=self)
            if p:
                self.directory.set(p)

    def use_pb_result(self):
        if self.running:
            return
        if self.parent.latest and Path(self.parent.latest).is_dir():
            self.directory.set(self.parent.latest)
        else:
            messagebox.showinfo('暂无整理结果', '请先在 PB/TOP5 中完成一次整理，或自行选择输入文件夹。', parent=self)

    def start(self):
        if self.parent.other_task_running(self):
            messagebox.showerror('请稍候', '其他功能仍在运行，请等待结束后再上传。', parent=self)
            return
        directory, user, password = self.directory.get().strip(), self.username.get().strip(), self.password.get()
        if not directory or not Path(directory).is_dir() or not user or not password:
            messagebox.showerror('配置错误', '请选择有效的输入文件夹，并填写账号密码。', parent=self)
            return
        recursive, skip = self.recursive.get(), self.skip.get()
        try:
            self.settings.flush()
        except OSError as ex:
            messagebox.showerror('配置错误', str(ex), parent=self)
            return
        self.running = True
        self.stop.clear()
        self.go.configure(state='disabled')
        self.cancel.configure(state='normal')
        for entry in (self.path_entry, self.user_entry, self.pass_entry):
            entry.configure(state='disabled')
        self.log.configure(state='normal')
        self.log.delete('1.0', 'end')
        self.log.configure(state='disabled')
        self.phase.set('准备上传…')
        self.bar.configure(mode='indeterminate')
        self.bar.start(15)
        def work():
            try:
                dest, _ = upload_directory(directory, user, password,
                    lambda k, v: self.events.put((k, v)), self.stop, recursive, skip)
                self.events.put(('done', str(dest)))
            except Exception as ex:
                self.events.put(('error', str(ex).replace(password, '[密码已隐藏]')))
        threading.Thread(target=work, daemon=True).start()

    def poll(self):
        logs, progress, terminal = [], None, None
        for _ in range(1000):
            try:
                kind, data = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == 'log':
                logs.append(data)
            elif kind == 'upload_progress':
                progress = data
            else:
                terminal = (kind, data)
        if logs:
            self.log.configure(state='normal')
            self.log.insert('end', '\n'.join(logs) + '\n')
            if int(self.log.index('end-1c').split('.')[0]) > 1500:
                self.log.delete('1.0', '501.0')
            self.log.see('end')
            self.log.configure(state='disabled')
        if progress:
            s = progress
            self.latest = s['directory']
            self.phase.set(f"{s['phase']} · 耗时 {s['seconds']:.1f} 秒")
            self.counts.set(f"录像 {s['processed']} / {s['total']}    上传成功 {s['uploaded']}    网站已存在 {s['existing']}    跳过 {s['skipped']}    失败 {s['failed']}    待确认 {s['uncertain']}")
            if s['phase'] != '扫描上传目录':
                self.bar.stop()
                self.bar.configure(mode='determinate')
                self.bar['value'] = 100 * s['processed'] / max(1, s['total'])
        if terminal:
            self.running = False
            self.bar.stop()
            self.go.configure(state='normal')
            self.cancel.configure(state='disabled')
            for entry in (self.path_entry, self.user_entry, self.pass_entry):
                entry.configure(state='normal')
            if terminal[0] == 'error':
                messagebox.showerror('上传停止', terminal[1], parent=self)
            else:
                self.latest = terminal[1]
        self.after(100, self.poll)

    def open_report(self):
        if self.latest and Path(self.latest).is_dir():
            os.startfile(self.latest)

    def cancel_task(self):
        if self.running:
            self.stop.set()
            self.phase.set('正在取消，等待当前请求结束（超时上限25秒）…')
