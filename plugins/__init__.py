"""Discover tool packages exposing a plugin.py register(registry) entry point."""
from importlib import import_module
from pkgutil import iter_modules

from common.plugin_api import ToolRegistry


def load_registry():
    registry = ToolRegistry()
    for package in sorted(iter_modules(__path__), key=lambda item: item.name):
        if not package.ispkg:
            continue
        try:
            entry = import_module(f'{__name__}.{package.name}.plugin')
            # Stage each package separately: a failing entry cannot partially register.
            staged = ToolRegistry()
            entry.register(staged)
            specs = staged.all()
            if len(specs) != 1:
                raise ValueError('每个插件目录必须注册且只注册一个工具')
            registry.register(specs[0])
        except Exception as ex:
            registry.errors.append((package.name, str(ex)))
    return registry
