import json
import os
import queue
import threading
import tkinter as tk
from pathlib import Path
from common.paths import DATA_DIR
from tkinter import ttk, filedialog, messagebox
from services.gsc import run_gsc, reference_settings, validate
from common.settings_store import AutoSettings
from services.gsc_display import load_result
from ui.gsc_scoreboard import ScoreboardView

BASE = DATA_DIR


class GscPanel(ttk.Frame):
    def __init__(self, master, parent):
        super().__init__(master)
        self.parent = parent
        self.running = False
        self.stop = threading.Event()
        self.events = queue.Queue()
        self.latest = ''
        defaults = reference_settings()
        self.baseline = defaults['baseline']
        self.output = tk.StringVar()
        self.edition = tk.StringVar()
        self.suffix = tk.StringVar()
        self.start_time = tk.StringVar(value=defaults['start'].replace('/', '-'))
        self.end_time = tk.StringVar(value=defaults['end'].replace('/', '-'))
        self.recursive = tk.BooleanVar(value=True)
        self.check_completion = tk.BooleanVar(value=False)
        self.time_basis = tk.StringVar(value='录像内记录时间')
        self.display_scale = tk.StringVar(value='100')
        self.phase = tk.StringVar(value='等待开始')
        self.counts = tk.StringVar(value='录像 0 / 0    符合条件 0    TopX 0 / 0')
        self.views = ttk.Notebook(self)
        self.views.pack(fill='both', expand=True)
        outer = ttk.Frame(self.views, padding=12)
        records_page = ttk.Frame(self.views, padding=12)
        self.views.add(outer, text='筛选设置')
        self.views.add(records_page, text='成绩记录')
        toolbar = ttk.Frame(records_page)
        toolbar.pack(fill='x', pady=(0,8))
        ttk.Button(toolbar, text='打开已有成绩…', command=self.choose_scores).pack(side='left')
        ttk.Button(toolbar, text='查看最近成绩', command=self.open_scores).pack(side='left', padx=8)
        ttk.Label(toolbar, text='显示比例 %').pack(side='left', padx=(12,5))
        ttk.Combobox(toolbar, textvariable=self.display_scale, values=('75','100','125','150'),
                     state='readonly', width=5).pack(side='left')
        ttk.Button(toolbar, text='打开HTML报告', command=self.open_html).pack(side='right')
        self.scoreboard = ScoreboardView(records_page, self.display_scale)
        self.scoreboard.pack(fill='both', expand=True)
        ttk.Label(outer, text='金羊杯文件筛选及成绩计算', style='Title.TLabel').pack(anchor='w')
        ttk.Label(outer, text='计分规则：初级 Top20 / 3BV ≥ 10    中级 Top12 / 3BV ≥ 30    高级 Top5 / 3BV ≥ 100；FL、NF 合并统计').pack(anchor='w', pady=(4, 8))
        ttk.Label(outer, text='输入文件夹（可多次添加）').pack(anchor='w')
        folders = ttk.Frame(outer)
        folders.pack(fill='x', pady=4)
        self.input_paths = tk.Variable(value=())
        self.inputs = tk.Listbox(folders, listvariable=self.input_paths, height=3, selectmode='extended', font=('Microsoft YaHei UI', 10), relief='flat')
        self.inputs.pack(side='left', fill='x', expand=True)
        actions = ttk.Frame(folders)
        actions.pack(side='left', padx=(10, 0))
        ttk.Button(actions, text='添加文件夹', command=self.add_folder).pack(fill='x')
        ttk.Button(actions, text='移除选中', command=self.remove_folder).pack(fill='x', pady=3)
        path_row = ttk.Frame(outer)
        path_row.pack(fill='x', pady=5)
        ttk.Label(path_row, text='输出文件夹').pack(side='left')
        ttk.Entry(path_row, textvariable=self.output).pack(side='left', fill='x', expand=True, padx=8)
        ttk.Button(path_row, text='选择文件夹…', command=self.choose_output).pack(side='left')
        edition_row = ttk.Frame(outer)
        edition_row.pack(fill='x', pady=5)
        ttk.Label(edition_row, text='金羊杯届数').pack(side='left')
        ttk.Entry(edition_row, textvariable=self.edition, width=8).pack(side='left', padx=8)
        ttk.Label(edition_row, text='标识后缀（从录像内标识末尾匹配，区分大小写）').pack(side='left', padx=(15, 5))
        ttk.Entry(edition_row, textvariable=self.suffix, width=24).pack(side='left', fill='x', expand=True)
        times = ttk.Frame(outer)
        times.pack(fill='x', pady=5)
        ttk.Label(times, text='开始时间').pack(side='left')
        ttk.Entry(times, textvariable=self.start_time, width=23).pack(side='left', padx=8)
        ttk.Label(times, text='结束时间').pack(side='left', padx=(10, 0))
        ttk.Entry(times, textvariable=self.end_time, width=23).pack(side='left', padx=8)
        ttk.Label(times, text='YYYY-MM-DD HH:MM:SS').pack(side='left')
        opts = ttk.Frame(outer)
        opts.pack(fill='x', pady=5)
        ttk.Checkbutton(opts, text='递归子文件夹', variable=self.recursive).pack(side='left')
        ttk.Checkbutton(opts, text='校验完成度', variable=self.check_completion).pack(side='left', padx=18)
        ttk.Label(opts, text='时间依据').pack(side='left')
        ttk.Combobox(opts, textvariable=self.time_basis, values=['录像内记录时间', '文件修改时间（原工具）'],
                     state='readonly', width=23).pack(side='left', padx=8)
        ttk.Label(outer, text='初级参赛录像不设3BV门槛，BV<10也会原样导出；仅Top20计分要求BV≥10。默认按100%完成度计算。').pack(anchor='w', pady=3)
        controls = ttk.Frame(outer)
        controls.pack(fill='x', pady=7)
        self.go = ttk.Button(controls, text='开始筛选及计算', command=self.start)
        self.go.pack(side='left')
        self.cancel = ttk.Button(controls, text='取消', command=self.stop.set, state='disabled')
        self.cancel.pack(side='left', padx=10)
        ttk.Button(controls, text='查看成绩', command=self.open_scores).pack(side='right')
        ttk.Button(controls, text='打开结果文件夹', command=self.open_result).pack(side='right', padx=10)
        ttk.Label(outer, textvariable=self.phase).pack(anchor='w')
        self.bar = ttk.Progressbar(outer, maximum=100)
        self.bar.pack(fill='x', pady=5)
        ttk.Label(outer, textvariable=self.counts, wraplength=1000).pack(anchor='w')
        self.table = ttk.Treeview(outer, columns=('level', 'count', 'time', 'bvs', 'stnb', 'points'), show='headings', height=4)
        for key, label in zip(self.table['columns'], ('级别', '有效局数/TopX', 'Time平均', '3BV/s平均', 'STNB平均', '综合分')):
            self.table.heading(key, text=label)
            self.table.column(key, width=140, anchor='center')
        self.table.pack(fill='x', pady=7)
        self.combined = tk.StringVar(value='T37 / B37 / PPP37：等待计算（NT20.5基准沿用原工具配置）')
        ttk.Label(outer, textvariable=self.combined, wraplength=1000).pack(anchor='w')
        self.log = tk.Text(outer, height=3, wrap='word', state='disabled', font=('Microsoft YaHei UI', 9))
        self.log.pack(fill='both', expand=True, pady=(6, 0))
        try:
            config = json.loads((BASE / 'gsc_settings.json').read_text(encoding='utf-8'))
            for p in config.get('inputs', []):
                self.inputs.insert('end', p)
            for key in ('output', 'edition', 'suffix', 'start_time', 'end_time', 'recursive', 'check_completion', 'time_basis', 'display_scale'):
                if key in config:
                    getattr(self, key).set(config[key])
            self.baseline = config.get('baseline', self.baseline)
        except (OSError, ValueError):
            pass
        self.settings = AutoSettings(self, BASE / 'gsc_settings.json', self.settings_snapshot, parent.settings_status.set)
        self.settings.watch(self.input_paths, self.output, self.edition, self.suffix, self.start_time,
                            self.end_time, self.recursive, self.check_completion, self.time_basis, self.display_scale)
        self.after(100, self.poll)

    def settings_snapshot(self):
        return dict(inputs=list(self.inputs.get(0, 'end')), baseline=self.baseline,
            **{key: getattr(self, key).get() for key in ('output', 'edition', 'suffix', 'start_time',
                'end_time', 'recursive', 'check_completion', 'time_basis', 'display_scale')})

    def add_folder(self):
        if not self.running:
            p = filedialog.askdirectory(parent=self)
            if p and p not in self.inputs.get(0, 'end'):
                self.inputs.insert('end', p)

    def remove_folder(self):
        if not self.running:
            for i in reversed(self.inputs.curselection()):
                self.inputs.delete(i)

    def choose_output(self):
        if not self.running:
            p = filedialog.askdirectory(parent=self)
            if p:
                self.output.set(p)

    def start(self):
        if self.parent.other_task_running(self):
            messagebox.showerror('请稍候', '其他功能仍在运行，请等待结束后再开始。', parent=self)
            return
        try:
            config = dict(inputs=list(self.inputs.get(0, 'end')), baseline=self.baseline,
                **{key: getattr(self, key).get() for key in ('output', 'edition', 'suffix', 'start_time', 'end_time', 'recursive', 'check_completion', 'time_basis')})
            basis = 'recorded' if config['time_basis'] == '录像内记录时间' else 'modified'
            validate(config['inputs'], config['output'], config['edition'], config['start_time'], config['end_time'], config['suffix'], self.baseline, basis)
            self.settings.flush()
        except (ValueError, OSError, KeyError) as ex:
            messagebox.showerror('配置错误', str(ex), parent=self)
            return
        self.running = True
        self.stop.clear()
        self.go.configure(state='disabled')
        self.cancel.configure(state='normal')
        self.table.delete(*self.table.get_children())
        self.log.configure(state='normal')
        self.log.delete('1.0', 'end')
        self.log.configure(state='disabled')
        self.bar.configure(mode='indeterminate')
        self.bar.start(15)
        def work():
            try:
                dest, _ = run_gsc(config['inputs'], config['output'], config['edition'],
                    config['start_time'], config['end_time'], config['suffix'],
                    lambda k, v: self.events.put((k, v)), self.stop,
                    config['recursive'], config['check_completion'], basis, self.baseline)
                self.events.put(('done', str(dest)))
            except Exception as ex:
                self.events.put(('error', str(ex)))
        threading.Thread(target=work, daemon=True).start()

    def poll(self):
        logs, progress, terminal, result = [], None, None, None
        for _ in range(1000):
            try:
                kind, value = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == 'log':
                logs.append(value)
            elif kind == 'gsc_progress':
                progress = value
            elif kind == 'gsc_scores':
                result = value
            else:
                terminal = (kind, value)
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
            self.counts.set(f"录像 {s['processed']} / {s['total']}   符合条件 {s['matched']}（已复制 {s['selected_copied']}）   TopX {s['top_copied']} / {s['top_total']}\n"
                f"初级BV<10仅导出 {s['beginner_below10']}   时间不符 {s['outside_time']}   后缀不符 {s['wrong_suffix']}   中高级3BV不足 {s['low_bv']}   重复 {s['duplicates']}   待核验 {s['unverified']}   无效 {s['failed']}   警告 {s['warnings']}")
            if s['phase'] != '扫描录像':
                self.bar.stop()
                self.bar.configure(mode='determinate')
                value = 70 * s['processed'] / max(1, s['total'])
                if s['phase'] == '复制参赛录像':
                    value = 70 + 15 * s['selected_copied'] / max(1, s['matched'])
                if s['phase'] == '复制 TopX':
                    value = 85 + 15 * s['top_copied'] / max(1, s['top_total'])
                self.bar['value'] = 100 if s['phase'] == '完成' else value
        if result and result['scores']:
            self.scoreboard.set_data(result)
            self.views.select(1)
            self.table.delete(*self.table.get_children())
            for level, s in result['scores'].items():
                a = s['averages']
                self.table.insert('', 'end', values=(level, f"{s['available']}/{s['required']}",
                    f"{a['time']:.2f}", f"{a['bvs']:.3f}", f"{a['stnb']:.2f}", f"{s['points']:.2f}"))
            c = result['combined']
            self.combined.set(f"T37 = {c['T37']:.2f}    B37 = {c['B37']:.3f}    PPP37 = {c['PPP37']:.2f}"
                              + ('    局数足够' if c['complete'] else '    暂定：部分级别局数不足'))
        if terminal:
            self.running = False
            self.bar.stop()
            self.go.configure(state='normal')
            self.cancel.configure(state='disabled')
            if terminal[0] == 'error':
                messagebox.showerror('任务失败', terminal[1], parent=self)
            else:
                self.latest = terminal[1]
        self.after(100, self.poll)

    def open_result(self):
        if self.latest and Path(self.latest).is_dir():
            os.startfile(self.latest)

    def open_scores(self):
        self.views.select(1)
        path = Path(self.latest) / '成绩.json' if self.latest else None
        if path is None or not path.is_file():
            root = Path(self.output.get()) / f'金羊杯{self.edition.get()}'
            paths = sorted(root.glob('计算_*/成绩.json'), reverse=True) if self.output.get() else []
            path = paths[0] if paths else None
        if path:
            self.show_scores(path)

    def choose_scores(self):
        path = filedialog.askopenfilename(parent=self, title='打开金羊杯成绩.json',
            filetypes=[('金羊杯成绩', '*.json')], initialdir=self.latest or self.output.get() or str(BASE))
        if path:
            self.show_scores(Path(path))

    def show_scores(self, path):
        try:
            result = load_result(path)
            self.scoreboard.set_data(result)
            self.latest = str(path.parent)
            self.views.select(1)
        except (OSError, ValueError, KeyError, TypeError) as ex:
            messagebox.showerror('无法打开成绩', str(ex), parent=self)

    def open_html(self):
        if self.latest and (Path(self.latest) / '成绩.html').is_file():
            os.startfile(Path(self.latest) / '成绩.html')

    def cancel_task(self):
        self.stop.set()
        self.phase.set('正在取消，请等待当前文件处理完成…')
