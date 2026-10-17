from common.plugin_api import ToolSpec
from .ui import PbTop5Panel


def register(registry):
    registry.register(ToolSpec('pb_top5', 'PB/TOP5', 10, PbTop5Panel))
