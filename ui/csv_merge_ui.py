import os
import queue
import threading
import tkinter as tk
from pathlib import Path
from common.paths import PROJECT_ROOT, DATA_DIR
from tkinter import ttk, filedialog, messagebox

from services.csv_merge import merge_csv, validate
from common.settings_store import AutoSettings, read_settings

BASE = DATA_DIR


class CsvMergePanel(ttk.Frame):
    def __init__(self, master, parent):
        super().__init__(master)
        self.parent = parent
        self.running = False
        self.stop = threading.Event()
        self.events = queue.Queue()
        self.latest = ''
        self.output = tk.StringVar()
        self.deduplicate = tk.BooleanVar(value=True)
        self.sort = tk.BooleanVar(value=True)
        self.encoding = tk.StringVar(value='UTF-8（原工具）')
        self.phase = tk.StringVar(value='等待开始')
        self.counts = tk.StringVar(value='文件 0 / 0    输入 0 行    去重 0 行    输出 0 行')
        self.input_paths = tk.Variable(value=())
        outer = ttk.Frame(self, padding=12)
        outer.pack(fill='both', expand=True)
        ttk.Label(outer, text='CSV合并', style='Title.TLabel').pack(anchor='w')
        ttk.Label(outer, text='合并 Arbiter stats_csv；按整行去重，再按 BEG → INT → EXP 和录像时间升序排列。').pack(anchor='w', pady=(5, 16))
        ttk.Label(outer, text='输入 CSV 文件（至少两个，按列表顺序合并）').pack(anchor='w')
        row = ttk.Frame(outer)
        row.pack(fill='x', pady=6)
        self.inputs = tk.Listbox(row, listvariable=self.input_paths, selectmode='extended',
                                 height=7, font=('Microsoft YaHei UI', 10), relief='flat')
        self.inputs.pack(side='left', fill='x', expand=True)
        actions = ttk.Frame(row)
        actions.pack(side='left', padx=(10, 0))
        ttk.Button(actions, text='添加CSV文件…', command=self.add_files).pack(fill='x')
        ttk.Button(actions, text='移除选中', command=self.remove_files).pack(fill='x', pady=6)
        ttk.Label(outer, text='输出 CSV 文件').pack(anchor='w', pady=(12, 5))
        row = ttk.Frame(outer)
        row.pack(fill='x')
        ttk.Entry(row, textvariable=self.output).pack(side='left', fill='x', expand=True)
        ttk.Button(row, text='选择CSV文件…', command=self.choose_output).pack(side='left', padx=(10, 0))
        opts = ttk.Frame(outer)
        opts.pack(fill='x', pady=16)
        ttk.Checkbutton(opts, text='整行去重', variable=self.deduplicate).pack(side='left')
        ttk.Checkbutton(opts, text='按级别、录像时间排序', variable=self.sort).pack(side='left', padx=20)
        ttk.Label(opts, text='输出编码').pack(side='left')
        ttk.Combobox(opts, textvariable=self.encoding, values=['UTF-8（原工具）', 'UTF-8 BOM（Excel）'],
                     state='readonly', width=22).pack(side='left', padx=8)
        ttk.Label(outer, text='输出可以与某个输入文件相同。已有输出文件会自动备份，已有备份保留。').pack(anchor='w')
        controls = ttk.Frame(outer)
        controls.pack(fill='x', pady=14)
        self.go = ttk.Button(controls, text='开始合并', command=self.start)
        self.go.pack(side='left')
        self.cancel = ttk.Button(controls, text='取消', command=self.stop.set, state='disabled')
        self.cancel.pack(side='left', padx=10)
        ttk.Button(controls, text='打开结果文件夹', command=self.open_result).pack(side='right')
        ttk.Label(outer, textvariable=self.phase).pack(anchor='w')
        self.bar = ttk.Progressbar(outer, maximum=100)
        self.bar.pack(fill='x', pady=8)
        ttk.Label(outer, textvariable=self.counts).pack(anchor='w')
        self.log = tk.Text(outer, height=8, wrap='word', state='disabled', font=('Microsoft YaHei UI', 9))
        self.log.pack(fill='both', expand=True, pady=(10, 0))
        config = read_settings(BASE / 'csv_merge_settings.json')
        if config:
            for p in config.get('inputs', []):
                self.inputs.insert('end', p)
            for key in ('output', 'deduplicate', 'sort', 'encoding'):
                if key in config:
                    getattr(self, key).set(config[key])
        else:
            for name in ('stats_csv.csv', 'stats_csv_PC.csv'):
                path = PROJECT_ROOT.parent / name
                if path.is_file():
                    self.inputs.insert('end', str(path))
            self.output.set(str(PROJECT_ROOT.parent / 'stats_csv.csv'))
        self.settings = AutoSettings(self, BASE / 'csv_merge_settings.json', self.settings_snapshot,
                                     parent.settings_status.set)
        self.settings.watch(self.input_paths, self.output, self.deduplicate, self.sort, self.encoding)
        self.after(100, self.poll)

    def settings_snapshot(self):
        return dict(inputs=list(self.inputs.get(0, 'end')), output=self.output.get(),
                    deduplicate=self.deduplicate.get(), sort=self.sort.get(), encoding=self.encoding.get())

    def add_files(self):
        if not self.running:
            for p in filedialog.askopenfilenames(parent=self, filetypes=[('CSV 文件', '*.csv')]):
                if p not in self.inputs.get(0, 'end'):
                    self.inputs.insert('end', p)

    def remove_files(self):
        if not self.running:
            for i in reversed(self.inputs.curselection()):
                self.inputs.delete(i)

    def choose_output(self):
        if not self.running:
            p = filedialog.asksaveasfilename(parent=self, filetypes=[('CSV 文件', '*.csv')],
                defaultextension='.csv', initialfile='stats_csv.csv', confirmoverwrite=False)
            if p:
                self.output.set(p)

    def start(self):
        if self.parent.other_task_running(self):
            messagebox.showerror('请稍候', '其他功能仍在运行，请等待结束后再开始。', parent=self)
            return
        config = self.settings_snapshot()
        encoding = 'utf-8-sig' if config['encoding'] == 'UTF-8 BOM（Excel）' else 'utf-8'
        try:
            validate(config['inputs'], config['output'], encoding)
            self.settings.flush()
        except (ValueError, OSError) as ex:
            messagebox.showerror('配置错误', str(ex), parent=self)
            return
        self.running = True
        self.stop.clear()
        self.go.configure(state='disabled')
        self.cancel.configure(state='normal')
        self.log.configure(state='normal')
        self.log.delete('1.0', 'end')
        self.log.configure(state='disabled')
        self.phase.set('准备合并…')
        self.bar.configure(mode='indeterminate')
        self.bar.start(15)
        def work():
            try:
                output, _ = merge_csv(config['inputs'], config['output'],
                    lambda k, v: self.events.put((k, v)), self.stop,
                    config['deduplicate'], config['sort'], encoding)
                self.events.put(('done', str(output)))
            except Exception as ex:
                self.events.put(('error', str(ex)))
        threading.Thread(target=work, daemon=True).start()

    def poll(self):
        logs, progress, terminal = [], None, None
        for _ in range(1000):
            try:
                kind, value = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == 'log':
                logs.append(value)
            elif kind == 'merge_progress':
                progress = value
            else:
                terminal = (kind, value)
        if logs:
            self.log.configure(state='normal')
            self.log.insert('end', '\n'.join(logs) + '\n')
            self.log.see('end')
            self.log.configure(state='disabled')
        if progress:
            s = progress
            self.latest = s['output']
            self.phase.set(f"{s['phase']} · 耗时 {s['seconds']:.1f} 秒")
            self.counts.set(f"文件 {s['files_read']} / {s['files_total']}    输入 {s['input_rows']:,} 行    去重 {s['duplicates_removed']:,} 行    输出 {s['output_rows']:,} 行（已写入 {s['rows_written']:,}）")
            self.bar.stop()
            self.bar.configure(mode='determinate')
            value = 40 * s['files_read'] / max(1, s['files_total'])
            if s['phase'] in ('整行去重', '按级别、录像时间排序'):
                value = 55 if s['phase'] == '整行去重' else 65
            if s['phase'] in ('写入合并结果', '备份已有输出文件'):
                value = 75 + 20 * s['rows_written'] / max(1, s['output_rows'])
            self.bar['value'] = 100 if s['phase'] == '完成' else value
        if terminal:
            self.running = False
            self.bar.stop()
            self.go.configure(state='normal')
            self.cancel.configure(state='disabled')
            if terminal[0] == 'error':
                messagebox.showerror('合并失败', terminal[1], parent=self)
            else:
                self.latest = terminal[1]
        self.after(100, self.poll)

    def open_result(self):
        if self.latest and Path(self.latest).parent.is_dir():
            os.startfile(Path(self.latest).parent)

    def cancel_task(self):
        self.stop.set()
        self.phase.set('正在取消，请等待当前操作完成…')
