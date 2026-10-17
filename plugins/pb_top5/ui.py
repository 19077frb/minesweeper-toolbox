import json
import os
import queue
import threading
import tkinter as tk
from pathlib import Path
from common.paths import DATA_DIR
from tkinter import ttk, filedialog, messagebox
from plugins.pb_top5.engine import run
from common.settings_store import AutoSettings, read_settings, variable_value
from ui.tutorial import add_tool_header
from .tutorial import SECTIONS

BASE = DATA_DIR


class PbTop5Panel(ttk.Frame):
    def __init__(self, master, parent):
        super().__init__(master)
        self.parent = parent
        self.events = queue.Queue()
        self.stop = threading.Event()
        self.running = False
        self.latest = ''
        self.output = tk.StringVar()
        self.recursive = tk.BooleanVar(value=True)
        self.rename = tk.BooleanVar(value=True)
        self.check_completion = tk.BooleanVar(value=False)
        self.flat_export = tk.BooleanVar(value=False)
        self.workers = tk.IntVar(value=4)
        outer = ttk.Frame(self, padding=12)
        outer.pack(fill='both', expand=True)
        self.tutorial_button = add_tool_header(outer, self, 'PB/TOP5', SECTIONS)
        ttk.Label(outer, text='FL / NF / ALL 独立统计  ·  默认完成度 100%，可选择校验  ·  无需 Excel').pack(anchor='w', pady=(5, 18))
        ttk.Label(outer, text='① 输入文件夹（可多次添加，重叠路径自动去重）').pack(anchor='w')
        folders = ttk.Frame(outer)
        folders.pack(fill='x', pady=6)
        self.input_paths = tk.Variable(value=())
        self.inputs = tk.Listbox(folders, listvariable=self.input_paths, height=6, selectmode='extended', font=('Microsoft YaHei UI', 10), relief='flat')
        self.inputs.pack(side='left', fill='x', expand=True)
        actions = ttk.Frame(folders, padding=(10, 0))
        actions.pack(side='left', fill='y')
        ttk.Button(actions, text='添加文件夹', command=self.add_folder).pack(fill='x')
        ttk.Button(actions, text='移除选中', command=self.remove_folder).pack(fill='x', pady=7)
        ttk.Label(outer, text='② 输出文件夹（每次运行创建独立结果目录）').pack(anchor='w', pady=(10, 4))
        row = ttk.Frame(outer)
        row.pack(fill='x')
        self.output_entry = ttk.Entry(row, textvariable=self.output)
        self.output_entry.pack(side='left', fill='x', expand=True)
        ttk.Button(row, text='选择文件夹…', command=self.choose_output).pack(side='left', padx=(10, 0))
        options = ttk.Frame(outer)
        options.pack(fill='x', pady=15)
        ttk.Checkbutton(options, text='递归子文件夹', variable=self.recursive).pack(side='left')
        ttk.Checkbutton(options, text='重命名输入录像（加入 STNB）', variable=self.rename).pack(side='left', padx=20)
        ttk.Checkbutton(options, text='校验完成度', variable=self.check_completion).pack(side='left')
        ttk.Label(options, text='解析线程').pack(side='left', padx=(20, 5))
        ttk.Spinbox(options, from_=1, to=16, width=3, textvariable=self.workers).pack(side='left')
        ttk.Checkbutton(outer, text='额外复制 ALL 文件夹（三级别合并，方便批量导入）',
                        variable=self.flat_export).pack(anchor='w', pady=(0, 5))
        ttk.Label(outer, text='PB：同级别 + 同 3BV 的最快录像；Top5：Time、3BV/s、STNB，初级要求 3BV ≥ 10。').pack(anchor='w')
        ttk.Label(outer, text='只读录像内容：仅改文件名及原样复制；STNB 不写入录像。自定义局 STNB 标记 NA。').pack(anchor='w', pady=4)
        controls = ttk.Frame(outer)
        controls.pack(fill='x', pady=12)
        self.start_button = ttk.Button(controls, text='开始整理', command=self.start)
        self.start_button.pack(side='left')
        self.cancel_button = ttk.Button(controls, text='取消', command=self.stop.set, state='disabled')
        self.cancel_button.pack(side='left', padx=10)
        ttk.Button(controls, text='打开结果文件夹', command=self.open_result).pack(side='right')
        self.phase = tk.StringVar(value='等待开始')
        ttk.Label(outer, textvariable=self.phase).pack(anchor='w')
        self.bar = ttk.Progressbar(outer, maximum=100)
        self.bar.pack(fill='x', pady=8)
        self.counts = tk.StringVar(value='录像 0 / 0    已重命名 0    3BV 分组 0    PB 0    Top5 0 / 0')
        ttk.Label(outer, textvariable=self.counts, wraplength=1000).pack(anchor='w', pady=4)
        self.log = tk.Text(outer, height=9, font=('Microsoft YaHei UI', 9), wrap='word', state='disabled', relief='flat')
        self.log.pack(fill='both', expand=True, pady=(10, 0))
        self.log.tag_configure('warning', foreground='#a64e08')
        self.load_config()
        self.settings = AutoSettings(self, BASE / 'settings.json', self.settings_snapshot, parent.settings_status.set)
        self.settings.watch(self.input_paths, self.output, self.recursive, self.rename, self.workers, self.check_completion, self.flat_export)
        self.after(100, self.poll)

    def add_folder(self):
        if not self.running:
            p = filedialog.askdirectory()
            if p and p not in self.inputs.get(0, 'end'):
                self.inputs.insert('end', p)

    def remove_folder(self):
        if not self.running:
            for i in reversed(self.inputs.curselection()):
                self.inputs.delete(i)

    def choose_output(self):
        if not self.running:
            p = filedialog.askdirectory()
            if p:
                self.output.set(p)

    def load_config(self):
        try:
            c = json.loads((BASE / 'settings.json').read_text(encoding='utf-8'))
            for p in c.get('inputs', []):
                self.inputs.insert('end', p)
            for key in ('output', 'recursive', 'rename', 'workers', 'check_completion', 'flat_export'):
                if key in c:
                    getattr(self, key).set(c[key])
        except (OSError, ValueError):
            pass

    def settings_snapshot(self):
        return dict(inputs=list(self.inputs.get(0, 'end')),
            **{k: variable_value(getattr(self, k)) for k in ('output', 'recursive', 'rename', 'workers', 'check_completion', 'flat_export')})

    def start(self):
        if self.parent.other_task_running(self):
            messagebox.showerror('请稍候', '其他功能仍在运行，请等待结束后再整理。')
            return
        inputs = list(self.inputs.get(0, 'end'))
        try:
            if not inputs or not self.output.get().strip():
                raise ValueError('请添加输入文件夹，并选择输出文件夹。')
            workers = self.workers.get()
            if not 1 <= workers <= 16:
                raise ValueError('解析线程数应为 1–16')
            c = dict(inputs=inputs, **{k: getattr(self, k).get() for k in ('output', 'recursive', 'rename', 'workers', 'check_completion', 'flat_export')})
            self.settings.flush()
        except (OSError, ValueError, tk.TclError) as ex:
            messagebox.showerror('配置错误', str(ex))
            return
        self.running = True
        self.stop.clear()
        self.start_button.configure(state='disabled')
        self.cancel_button.configure(state='normal')
        self.output_entry.configure(state='disabled')
        self.log.configure(state='normal')
        self.log.delete('1.0', 'end')
        self.log.configure(state='disabled')
        self.phase.set('准备扫描…')
        self.bar.configure(mode='indeterminate')
        self.bar.start(15)
        def work():
            try:
                result = run(inputs, c['output'], lambda k, v: self.events.put((k, v)),
                             self.stop, c['recursive'], c['rename'], workers,
                             check_completion=c['check_completion'], flat_export=c['flat_export'])
                self.events.put(('done', str(result[0])))
            except Exception as ex:
                self.events.put(('error', str(ex)))
        threading.Thread(target=work, daemon=True).start()

    def poll(self):
        logs, progress, terminal = [], None, None
        for _ in range(1500):
            try:
                kind, value = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == 'log':
                logs.append(value)
            elif kind == 'progress':
                progress = value
            else:
                terminal = (kind, value)
        if logs:
            self.log.configure(state='normal')
            self.log.insert('end', '\n'.join(logs) + '\n', 'warning')
            if int(self.log.index('end-1c').split('.')[0]) > 1500:
                self.log.delete('1.0', '501.0')
            self.log.see('end')
            self.log.configure(state='disabled')
        if progress:
            s = progress
            self.latest = s['directory']
            rate = s['processed'] / max(.001, s['seconds'])
            self.phase.set(f"{s['phase']} · 耗时 {s['seconds']:.1f} 秒 · {rate:.0f} 录像/秒")
            self.counts.set(f"录像 {s['processed']:,} / {s['total']:,}   已重命名 {s['renamed']:,}   无需改名/仅解析 {s['unchanged']:,}   缓存命中 {s['cached']:,}\n"
                f"3BV 分组 {s['bv']}   PB {s['pb']}（已复制 {s['pb_copied']}）   Top5 {s['top_found']} / {s['top_total']}   完成状态待核验 {s['unverified']}   无效 {s['failed']}   警告 {s['warnings']}")
            if s.get('flat_export'):
                self.counts.set(self.counts.get() + f"\nALL 合集 {s['flat_copied']} / {s['flat_total']}（已处理 {s['flat_checked']}）")
            if s['phase'] != '扫描录像':
                self.bar.stop()
                self.bar.configure(mode='determinate')
                value = 10 + 65 * s['processed'] / max(1, s['total'])
                if s['phase'] == '复制 PB':
                    value = 75 + (10 if s.get('flat_export') else 15) * s['pb_copied'] / max(1, s['pb'])
                if s['phase'] == '复制 Top5':
                    value = (85 if s.get('flat_export') else 90) + 10 * s['top_checked'] / max(1, s['top_total'])
                if s['phase'] == '复制 ALL 合集':
                    value = 95 + 5 * s['flat_checked'] / max(1, s['flat_total'])
                if s['phase'] == '完成':
                    value = 100
                self.bar['value'] = value
        if terminal:
            self.running = False
            self.bar.stop()
            self.start_button.configure(state='normal')
            self.cancel_button.configure(state='disabled')
            self.output_entry.configure(state='normal')
            if terminal[0] == 'error':
                self.phase.set('任务失败')
                messagebox.showerror('任务失败', terminal[1])
            else:
                self.latest = terminal[1]
        self.after(100, self.poll)

    def open_result(self):
        p = self.latest or self.output.get()
        if p and Path(p).is_dir():
            os.startfile(p)

    def cancel_task(self):
        if self.running:
            self.stop.set()
            self.phase.set('正在取消，请等待当前文件处理完成…')
