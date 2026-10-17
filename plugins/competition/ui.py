import json
import os
import queue
import threading
import tkinter as tk
from pathlib import Path
from common.paths import DATA_DIR
from tkinter import ttk, filedialog, messagebox
from plugins.competition.scoring import run_competition, reference_settings, validate
from common.settings_store import AutoSettings
from plugins.competition.display import load_result, summary_rows
from plugins.competition.scoreboard import ScoreboardView
from .rules import DEFAULT_TOP_COUNTS, MAX_TOP_COUNT, normalize_counts, result_counts, validate_name
from ui.tutorial import add_tool_header, show_tutorial
from .tutorial import SECTIONS

BASE = DATA_DIR


class CompetitionPanel(ttk.Frame):
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
        self.competition_name = tk.StringVar()
        self.suffix = tk.StringVar()
        self.start_time = tk.StringVar(value=defaults['start'].replace('/', '-'))
        self.end_time = tk.StringVar(value=defaults['end'].replace('/', '-'))
        self.recursive = tk.BooleanVar(value=True)
        self.check_completion = tk.BooleanVar(value=False)
        self.flat_export = tk.BooleanVar(value=False)
        self.time_basis = tk.StringVar(value='录像内记录时间')
        self.display_scale = tk.StringVar(value='100')
        self.top_counts = {level: tk.StringVar(value=str(n)) for level, n in DEFAULT_TOP_COUNTS.items()}
        self.rules_hint = tk.StringVar()
        self.top_hint = tk.StringVar()
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
        ttk.Button(toolbar, text='教程', command=lambda: show_tutorial(self, '赛事录像管理', SECTIONS)).pack(side='right', padx=(8, 0))
        ttk.Button(toolbar, text='打开已有成绩…', command=self.choose_scores).pack(side='left')
        ttk.Button(toolbar, text='查看最近成绩', command=self.open_scores).pack(side='left', padx=8)
        ttk.Label(toolbar, text='显示比例 %').pack(side='left', padx=(12,5))
        ttk.Combobox(toolbar, textvariable=self.display_scale, values=('75','100','125','150'),
                     state='readonly', width=5).pack(side='left')
        ttk.Button(toolbar, text='打开HTML报告', command=self.open_html).pack(side='right')
        self.scoreboard = ScoreboardView(records_page, self.display_scale)
        self.scoreboard.pack(fill='both', expand=True)
        self.tutorial_button = add_tool_header(outer, self, '赛事录像管理', SECTIONS)
        ttk.Label(outer, textvariable=self.rules_hint).pack(anchor='w', pady=(4, 8))
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
        name_row = ttk.Frame(outer)
        name_row.pack(fill='x', pady=5)
        ttk.Label(name_row, text='比赛名称').pack(side='left')
        ttk.Entry(name_row, textvariable=self.competition_name, width=24).pack(side='left', padx=8)
        ttk.Label(name_row, text='标识后缀（从录像内标识末尾匹配，区分大小写）').pack(side='left', padx=(15, 5))
        ttk.Entry(name_row, textvariable=self.suffix, width=24).pack(side='left', fill='x', expand=True)
        top_row = ttk.Frame(outer)
        top_row.pack(fill='x', pady=5)
        for level, label in (('Beg','初级 Top'),('Int','中级 Top'),('Exp','高级 Top')):
            ttk.Label(top_row, text=label).pack(side='left', padx=(0, 5))
            ttk.Spinbox(top_row, from_=1, to=MAX_TOP_COUNT, width=5,
                        textvariable=self.top_counts[level]).pack(side='left', padx=(0, 18))
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
        ttk.Checkbutton(outer, text='额外复制 ALL 文件夹（三级别合并，方便批量导入）',
                        variable=self.flat_export).pack(anchor='w', pady=3)
        ttk.Label(outer, text='初级参赛录像不设3BV门槛，BV<10也会原样导出；初级计分要求BV≥10。默认按100%完成度计算。').pack(anchor='w', pady=3)
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
        for key, label in zip(self.table['columns'], ('级别', '有效局数/TopX', 'Time平均/TopX', '3BV/s平均/TopX', 'STNB平均/TopX', 'PPP')):
            self.table.heading(key, text=label)
            self.table.column(key, width=160 if key in ('time', 'bvs', 'stnb') else 110, anchor='center')
        self.table.pack(fill='x', pady=7)
        ttk.Label(outer, textvariable=self.top_hint,
                  wraplength=1000).pack(anchor='w')
        self.combined = tk.StringVar(value='汇总成绩：等待计算（PPP采用NT20.5基准）')
        ttk.Label(outer, textvariable=self.combined, wraplength=1000).pack(anchor='w')
        self.log = tk.Text(outer, height=3, wrap='word', state='disabled', font=('Microsoft YaHei UI', 9))
        self.log.pack(fill='both', expand=True, pady=(6, 0))
        try:
            config = json.loads((BASE / 'competition_settings.json').read_text(encoding='utf-8'))
            for p in config.get('inputs', []):
                self.inputs.insert('end', p)
            for key in ('output', 'competition_name', 'suffix', 'start_time', 'end_time', 'recursive', 'check_completion', 'time_basis', 'display_scale', 'flat_export'):
                if key in config:
                    getattr(self, key).set(config[key])
            for level, value in config.get('top_counts', {}).items():
                if level in self.top_counts:
                    self.top_counts[level].set(value)
            self.baseline = config.get('baseline', self.baseline)
        except (OSError, ValueError):
            pass
        self.settings = AutoSettings(self, BASE / 'competition_settings.json', self.settings_snapshot, parent.settings_status.set)
        self.settings.watch(self.input_paths, self.output, self.competition_name, self.suffix, self.start_time,
                            self.end_time, self.recursive, self.check_completion, self.time_basis, self.display_scale, self.flat_export, *self.top_counts.values())
        for variable in self.top_counts.values():
            variable.trace_add('write', self.update_top_hints)
        self.update_top_hints()
        self.after(100, self.poll)

    def update_top_hints(self, *args):
        b, i, e = (self.top_counts[level].get() or '?' for level in DEFAULT_TOP_COUNTS)
        self.rules_hint.set(f'计分：初级Top{b} / 3BV≥10    中级Top{i} / 3BV≥30    高级Top{e} / 3BV≥100；FL、NF合并统计')
        self.top_hint.set(f'平均值 / 第X名成绩：初级X={b}、中级X={i}、高级X={e}；Time更小、3BV/s和STNB更大才能提升成绩。')

    def settings_snapshot(self):
        return dict(inputs=list(self.inputs.get(0, 'end')), baseline=self.baseline,
            top_counts={level: variable.get() for level, variable in self.top_counts.items()},
            **{key: getattr(self, key).get() for key in ('output', 'competition_name', 'suffix', 'start_time',
                'end_time', 'recursive', 'check_completion', 'time_basis', 'display_scale', 'flat_export')})

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
                **{key: getattr(self, key).get() for key in ('output', 'competition_name', 'suffix', 'start_time', 'end_time', 'recursive', 'check_completion', 'time_basis', 'flat_export')})
            config['top_counts'] = normalize_counts({level: var.get() for level, var in self.top_counts.items()})
            basis = 'recorded' if config['time_basis'] == '录像内记录时间' else 'modified'
            validate(config['inputs'], config['output'], config['competition_name'], config['start_time'], config['end_time'], config['suffix'], self.baseline, basis, config['top_counts'])
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
                dest, _ = run_competition(config['inputs'], config['output'], config['competition_name'],
                    config['start_time'], config['end_time'], config['suffix'],
                    lambda k, v: self.events.put((k, v)), self.stop,
                    config['recursive'], config['check_completion'], basis, self.baseline,
                    flat_export=config['flat_export'], top_counts=config['top_counts'])
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
            elif kind == 'competition_progress':
                progress = value
            elif kind == 'competition_scores':
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
                f"已解析 {s['parsed']}   初级BV<10仅导出 {s['beginner_below10']}   时间不符（已跳过解析）{s['outside_time']}   后缀不符 {s['wrong_suffix']}   中高级3BV不足 {s['low_bv']}   重复 {s['duplicates']}   待核验 {s['unverified']}   无效 {s['failed']}   警告 {s['warnings']}")
            if s.get('flat_export'):
                self.counts.set(self.counts.get() + f"\nALL 合集 {s['flat_copied']} / {s['flat_total']}（已处理 {s['flat_checked']}）")
            if s['phase'] != '扫描录像':
                self.bar.stop()
                self.bar.configure(mode='determinate')
                value = 70 * s['processed'] / max(1, s['total'])
                if s['phase'] == '复制参赛录像':
                    value = 70 + 15 * s['selected_copied'] / max(1, s['matched'])
                if s['phase'] == '复制 TopX':
                    value = 85 + (10 if s.get('flat_export') else 15) * s['top_copied'] / max(1, s['top_total'])
                if s['phase'] == '复制 ALL 合集':
                    value = 95 + 5 * s['flat_checked'] / max(1, s['flat_total'])
                self.bar['value'] = 100 if s['phase'] == '完成' else value
        if result and result['scores']:
            self.show_summary(result)
            self.views.select(1)
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

    def show_summary(self, result):
        self.scoreboard.set_data(result)
        self.table.delete(*self.table.get_children())
        for row in summary_rows(result):
            self.table.insert('', 'end', values=row)
        c = result['combined']
        total = sum(result_counts(result).values())
        self.combined.set(f"T{total} = {c.get(f'T{total}', 0):.2f}    B{total} = {c.get(f'B{total}', 0):.3f}    PPP{total} = {c.get(f'PPP{total}', 0):.2f}"
                          + ('    局数足够' if c.get('complete') else '    暂定：部分级别局数不足'))

    def open_result(self):
        if self.latest and Path(self.latest).is_dir():
            os.startfile(self.latest)

    def open_scores(self):
        self.views.select(1)
        if not self.output.get().strip():
            return
        try:
            name = validate_name(self.competition_name.get())
        except ValueError:
            return
        root = Path(self.output.get()) / name
        path = Path(self.latest) / '成绩.json' if self.latest and Path(self.latest).parent == root else None
        if path is None or not path.is_file():
            paths = sorted((p for p in root.glob('*/成绩.json') if p.parent.name.startswith(name + '_')), reverse=True)
            path = paths[0] if paths else None
        if path:
            self.show_scores(path)

    def choose_scores(self):
        path = filedialog.askopenfilename(parent=self, title='打开赛事成绩.json',
            filetypes=[('赛事成绩', '*.json')], initialdir=self.latest or self.output.get() or str(BASE))
        if path:
            self.show_scores(Path(path))

    def show_scores(self, path):
        try:
            result = load_result(path)
            self.show_summary(result)
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
