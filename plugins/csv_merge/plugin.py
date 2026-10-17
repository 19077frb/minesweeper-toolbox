from common.plugin_api import ToolSpec
from .ui import CsvMergePanel


def register(registry):
    registry.register(ToolSpec('csv_merge', 'CSV合并', 40, CsvMergePanel))
