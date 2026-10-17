import json
import os
import queue
import threading
import tkinter as tk
from pathlib import Path
from common.paths import DATA_DIR, prepare_data_dir
from tkinter import ttk, filedialog, messagebox
from services.engine import run
from common.settings_store import AutoSettings, read_settings, variable_value

BASE = DATA_DIR


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('扫雷工具箱')
        self.geometry('1080x780')
        self.minsize(900, 660)
        self.events = queue.Queue()
        self.stop = threading.Event()
        self.running = False
        self.latest = ''
        self.upload_panel = None
        self.gsc_panel = None
        self.csv_merge_panel = None
        self.output = tk.StringVar()
        self.recursive = tk.BooleanVar(value=True)
        self.rename = tk.BooleanVar(value=True)
        self.check_completion = tk.BooleanVar(value=False)
        self.workers = tk.IntVar(value=4)
        style = ttk.Style(self)
        style.theme_use('clam')
        style.configure('TFrame', background='#f2f5fa')
        style.configure('TLabel', background='#f2f5fa', font=('Microsoft YaHei UI', 10))
        style.configure('Title.TLabel', font=('Microsoft YaHei UI', 22, 'bold'), foreground='#163955')
        style.configure('TButton', padding=7, font=('Microsoft YaHei UI', 10))
        style.configure('TCheckbutton', background='#f2f5fa', font=('Microsoft YaHei UI', 10))
        style.configure('TNotebook.Tab', font=('Microsoft YaHei UI', 11), padding=(22, 10))
        self.settings_status = tk.StringVar(value='输入及选项自动保存')
        ttk.Label(self, textvariable=self.settings_status).pack(side='bottom', fill='x', padx=15, pady=(0, 4))
        self.navigation = ttk.Notebook(self)
        self.navigation.pack(fill='both', expand=True, padx=12, pady=12)
        self.pb_page = ttk.Frame(self.navigation)
        self.navigation.add(self.pb_page, text='PB/TOP5')
        outer = ttk.Frame(self.pb_page, padding=12)
        outer.pack(fill='both', expand=True)
        ttk.Label(outer, text='PB/TOP5', style='Title.TLabel').pack(anchor='w')
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
        self.settings = AutoSettings(self, BASE / 'settings.json', self.settings_snapshot, self.settings_status.set)
        self.settings.watch(self.input_paths, self.output, self.recursive, self.rename, self.workers, self.check_completion)
        from ui.upload_ui import UploadPanel
        self.upload_panel = UploadPanel(self.navigation, self)
        self.navigation.add(self.upload_panel, text='自动上传录像')
        from ui.gsc_ui import GscPanel
        self.gsc_panel = GscPanel(self.navigation, self)
        self.navigation.add(self.gsc_panel, text='金羊杯文件筛选及成绩计算')
        from ui.csv_merge_ui import CsvMergePanel
        self.csv_merge_panel = CsvMergePanel(self.navigation, self)
        self.navigation.add(self.csv_merge_panel, text='CSV合并')
        prefs = read_settings(BASE / 'app_settings.json')
        tab = prefs.get('selected_tab', 0)
        if isinstance(tab, int) and 0 <= tab < len(self.navigation.tabs()):
            self.navigation.select(tab)
        self.app_settings = AutoSettings(self, BASE / 'app_settings.json',
            lambda: dict(selected_tab=self.navigation.index(self.navigation.select())), self.settings_status.set)
        self.navigation.bind('<<NotebookTabChanged>>', self.app_settings.changed)
        self.protocol('WM_DELETE_WINDOW', self.close)
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
            for key in ('output', 'recursive', 'rename', 'workers', 'check_completion'):
                if key in c:
                    getattr(self, key).set(c[key])
        except (OSError, ValueError):
            pass

    def settings_snapshot(self):
        return dict(inputs=list(self.inputs.get(0, 'end')),
            **{k: variable_value(getattr(self, k)) for k in ('output', 'recursive', 'rename', 'workers', 'check_completion')})

    def start(self):
        if self.other_task_running(self):
            messagebox.showerror('请稍候', '其他功能仍在运行，请等待结束后再整理。')
            return
        inputs = list(self.inputs.get(0, 'end'))
        try:
            if not inputs or not self.output.get().strip():
                raise ValueError('请添加输入文件夹，并选择输出文件夹。')
            workers = self.workers.get()
            if not 1 <= workers <= 16:
                raise ValueError('解析线程数应为 1–16')
            c = dict(inputs=inputs, **{k: getattr(self, k).get() for k in ('output', 'recursive', 'rename', 'workers', 'check_completion')})
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
                             check_completion=c['check_completion'])
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
            if s['phase'] != '扫描录像':
                self.bar.stop()
                self.bar.configure(mode='determinate')
                value = 10 + 65 * s['processed'] / max(1, s['total'])
                if s['phase'] == '复制 PB':
                    value = 75 + 15 * s['pb_copied'] / max(1, s['pb'])
                if s['phase'] == '复制 Top5':
                    value = 90 + 10 * s['top_checked'] / max(1, s['top_total'])
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

    def open_upload(self):
        self.navigation.select(self.upload_panel)

    def other_task_running(self, current):
        return any(p is not current and p is not None and p.running
                   for p in (self, self.upload_panel, self.gsc_panel, self.csv_merge_panel))

    def close(self):
        try:
            for settings in (self.settings, self.upload_panel.settings, self.gsc_panel.settings,
                             self.csv_merge_panel.settings, self.app_settings):
                settings.flush()
        except (OSError, ValueError, tk.TclError) as ex:
            messagebox.showerror('设置保存失败', str(ex), parent=self)
            return
        if self.csv_merge_panel and self.csv_merge_panel.running:
            self.csv_merge_panel.cancel_task()
            return
        if self.gsc_panel and self.gsc_panel.running:
            self.gsc_panel.cancel_task()
            return
        if self.upload_panel and self.upload_panel.running:
            self.upload_panel.cancel_task()
            return
        if self.running:
            self.stop.set()
            self.phase.set('正在取消，请等待当前文件处理完成后再关闭窗口…')
            return
        self.destroy()


def launch():
    try:
        prepare_data_dir()
    except (OSError, ValueError) as ex:
        messagebox.showerror('无法准备数据目录', str(ex))
        return
    App().mainloop()


if __name__ == '__main__':
    launch()
