"""Atomic, debounced JSON settings persistence."""
import json
import os
import tempfile
import tkinter as tk
from pathlib import Path


def read_settings(path):
    try:
        value = json.loads(Path(path).read_text(encoding='utf-8'))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def write_settings(path, data):
    path = Path(path)
    temp = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                         prefix='.settings-', suffix='.tmp', delete=False) as f:
            temp = Path(f.name)
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, path)
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)


def variable_value(variable):
    try:
        return variable.get()
    except tk.TclError:
        # Preserve partially typed numeric fields too; validation happens on Run.
        return variable._tk.globalgetvar(str(variable))


class AutoSettings:
    def __init__(self, owner, path, snapshot, on_error, delay=350):
        self.owner, self.path = owner, Path(path)
        self.snapshot, self.on_error = snapshot, on_error
        self.delay, self.pending = delay, None
        self.traces = []
        self.last = read_settings(path)

    def watch(self, *variables):
        for variable in variables:
            token = variable.trace_add('write', self.changed)
            self.traces.append((variable, token))

    def changed(self, *_):
        if self.pending is not None:
            self.owner.after_cancel(self.pending)
        self.pending = self.owner.after(self.delay, self._automatic_flush)

    def _automatic_flush(self):
        self.pending = None
        try:
            self.flush()
        except (OSError, ValueError, tk.TclError) as ex:
            self.on_error(f'设置保存失败：{ex}')

    def flush(self):
        if self.pending is not None:
            self.owner.after_cancel(self.pending)
            self.pending = None
        data = self.snapshot()
        if data != self.last or not self.path.exists():
            write_settings(self.path, data)
            self.last = data

