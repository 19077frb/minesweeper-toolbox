"""Registration and host contracts shared by all built-in tool plugins."""
from dataclasses import dataclass
from typing import Callable, Protocol
import tkinter as tk
from tkinter import ttk

from common.settings_store import AutoSettings


class ToolPanel(Protocol):
    running: bool
    latest: str
    settings: AutoSettings

    def cancel_task(self) -> None: ...


class ToolHost(Protocol):
    settings_status: tk.StringVar

    def other_task_running(self, current: ToolPanel) -> bool: ...

    def get_result(self, tool_id: str) -> str: ...


@dataclass(frozen=True)
class ToolSpec:
    id: str
    title: str
    order: int
    create_panel: Callable[[ttk.Notebook, ToolHost], ToolPanel]


class ToolRegistry:
    def __init__(self):
        self._tools = {}
        self.errors = []

    def register(self, spec: ToolSpec):
        if not isinstance(spec, ToolSpec) or not spec.id.isidentifier() or not spec.title.strip():
            raise ValueError('插件必须提供有效的ToolSpec、标识和名称')
        if spec.id in self._tools:
            raise ValueError(f'插件标识重复：{spec.id}')
        if not isinstance(spec.order, int) or not callable(spec.create_panel):
            raise ValueError(f'插件排序或面板工厂无效：{spec.id}')
        self._tools[spec.id] = spec

    def all(self):
        return sorted(self._tools.values(), key=lambda spec: (spec.order, spec.id))
