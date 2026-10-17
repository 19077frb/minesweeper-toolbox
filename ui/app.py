"""Main window: discover tools, host tabs and coordinate task lifetime."""
import tkinter as tk
from tkinter import ttk, messagebox

from common.paths import DATA_DIR, prepare_data_dir
from common.settings_store import AutoSettings, read_settings
from plugins import load_registry

BASE = DATA_DIR


class App(tk.Tk):
    def __init__(self, registry=None):
        super().__init__()
        self.title('扫雷工具箱')
        self.geometry('1080x780')
        self.minsize(900, 660)
        self.registry = registry if registry is not None else load_registry()
        self.panels = {}
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
        for spec in self.registry.all():
            panel = spec.create_panel(self.navigation, self)
            self.panels[spec.id] = panel
            self.navigation.add(panel, text=spec.title)
        prefs = read_settings(BASE / 'app_settings.json')
        tool_id = prefs.get('selected_tool')
        if tool_id in self.panels:
            self.navigation.select(self.panels[tool_id])
        else:
            # Existing settings used an index; preserve it on the first upgrade.
            tab = prefs.get('selected_tab', 0)
            if isinstance(tab, int) and 0 <= tab < len(self.navigation.tabs()):
                self.navigation.select(tab)
        self.app_settings = AutoSettings(self, BASE / 'app_settings.json',
            self.settings_snapshot, self.settings_status.set)
        self.navigation.bind('<<NotebookTabChanged>>', self.app_settings.changed)
        self.protocol('WM_DELETE_WINDOW', self.close)
        if self.registry.errors:
            self.settings_status.set('部分插件加载失败：' + '；'.join(
                f'{name}: {error}' for name, error in self.registry.errors))

    def settings_snapshot(self):
        selected = self.navigation.select()
        tool_id = next((key for key, panel in self.panels.items() if str(panel) == selected), '')
        return dict(selected_tool=tool_id,
                    selected_tab=self.navigation.index(selected) if selected else 0)

    def get_result(self, tool_id):
        panel = self.panels.get(tool_id)
        return panel.latest if panel is not None else ''

    def other_task_running(self, current):
        return any(panel is not current and panel.running for panel in self.panels.values())

    def close(self):
        try:
            for panel in self.panels.values():
                panel.settings.flush()
            self.app_settings.flush()
        except (OSError, ValueError, tk.TclError) as ex:
            messagebox.showerror('设置保存失败', str(ex), parent=self)
            return
        active = [panel for panel in self.panels.values() if panel.running]
        if active:
            for panel in active:
                panel.cancel_task()
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
