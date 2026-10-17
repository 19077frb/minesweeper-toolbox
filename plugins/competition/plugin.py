from common.plugin_api import ToolSpec
from .ui import CompetitionPanel


def register(registry):
    registry.register(ToolSpec('competition', '赛事录像管理', 30, CompetitionPanel))
