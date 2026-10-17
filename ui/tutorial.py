"""Shared, non-modal tutorial window; each plugin owns its tutorial content."""
import tkinter as tk
from tkinter import ttk


class TutorialWindow(tk.Toplevel):
    def __init__(self, owner, title, sections):
        super().__init__(owner)
        self.title(title + ' · 教程')
        self.geometry('920x680')
        self.minsize(640, 420)
        self.sections = sections
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        ttk.Label(self, text=title + ' · 使用教程', style='Title.TLabel').grid(
            row=0, column=0, sticky='w', padx=20, pady=16)
        body = ttk.Panedwindow(self, orient='horizontal')
        body.grid(row=1, column=0, sticky='nsew', padx=16)
        nav = ttk.Frame(body)
        self.contents = tk.Listbox(nav, width=22, exportselection=False,
                                   font=('Microsoft YaHei UI', 10), relief='flat')
        self.contents.pack(fill='both', expand=True)
        article = ttk.Frame(body)
        article.rowconfigure(0, weight=1)
        article.columnconfigure(0, weight=1)
        self.text = tk.Text(article, wrap='word', padx=20, pady=12, relief='flat',
                            font=('Microsoft YaHei UI', 11), spacing3=10,
                            background='#ffffff', foreground='#24364b')
        self.text.grid(row=0, column=0, sticky='nsew')
        scroll = ttk.Scrollbar(article, command=self.text.yview)
        scroll.grid(row=0, column=1, sticky='ns')
        self.text.configure(yscrollcommand=scroll.set)
        self.text.tag_configure('heading', font=('Microsoft YaHei UI', 15, 'bold'),
                                foreground='#163955', spacing1=16, spacing3=12)
        for index, (heading, content) in enumerate(sections):
            self.contents.insert('end', heading)
            self.text.mark_set(f'section_{index}', self.text.index('end-1c'))
            self.text.mark_gravity(f'section_{index}', 'left')
            self.text.insert('end', heading + '\n', 'heading')
            self.text.insert('end', content.strip() + '\n\n')
        self.text.configure(state='disabled')
        self.text.yview_moveto(0)
        self.contents.bind('<<ListboxSelect>>', self.select_section)
        body.add(nav, weight=0)
        body.add(article, weight=1)
        footer = ttk.Frame(self, padding=12)
        footer.grid(row=2, column=0, sticky='ew')
        ttk.Label(footer, text='左侧目录可跳转；正文可滚动和复制。').pack(side='left')
        ttk.Button(footer, text='关闭', command=self.destroy).pack(side='right')
        self.bind('<Escape>', lambda event: self.destroy())

    def select_section(self, event=None):
        selected = self.contents.curselection()
        if selected:
            self.text.yview(f'section_{selected[0]}')


def show_tutorial(panel, title, sections):
    window = getattr(panel, '_tutorial_window', None)
    if window is None or not window.winfo_exists():
        window = TutorialWindow(panel, title, sections)
        panel._tutorial_window = window
    window.deiconify()
    window.lift()
    window.focus_set()
    return window


def add_tool_header(container, panel, title, sections):
    header = ttk.Frame(container)
    header.pack(fill='x')
    ttk.Label(header, text=title, style='Title.TLabel').pack(side='left')
    button = ttk.Button(header, text='教程', command=lambda: show_tutorial(panel, title, sections))
    button.pack(side='right')
    return button
