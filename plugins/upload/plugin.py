from common.plugin_api import ToolSpec
from .ui import UploadPanel


def register(registry):
    registry.register(ToolSpec('upload', '自动上传录像', 20, UploadPanel))
