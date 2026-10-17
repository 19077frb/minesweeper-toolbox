# 开发说明

用户操作步骤见 [使用说明](../README.md)。以下命令均在项目根目录执行。

## 开发运行

```powershell
uv sync --locked
uv run main.py
uv run python -m unittest discover -s tests -v
```

Python 3.13+，依赖版本由 `uv.lock` 锁定。使用标准库 Tkinter 桌面界面；本机的 Python 已包含 Tk。解析库参考：[ms-toollib 公开文档](https://docs.rs/ms_toollib/latest/ms_toollib/videos/base_video/struct.BaseVideo.html)。


## 代码目录

```text
minesweeper-toolbox/
  main.py                 启动入口，仍可双击“启动程序.bat”
  ui/                     主窗口，只负责装载插件和协调任务
  plugins/
    pb_top5/              PB/TOP5：注册入口、界面、整理逻辑
    upload/               自动上传：注册入口、界面、上传逻辑
    competition/          赛事管理：注册入口、界面、计分、成绩表和HTML
    csv_merge/            CSV合并：注册入口、界面、合并逻辑
  common/                 录像解析、原样复制、设置保存、路径管理、插件接口
  tests/                  回归测试
  tools/                  开发分析及历史问题修复脚本
  data/                   所有程序运行数据
    *.json                设置、完成确认清单
    *.sqlite3             录像解析缓存、上传历史
    upload_reports/       上传日志及报告
```

设置、完成确认清单、数据库和上传报告统一保存在 `data/`。启动时自动将旧版根目录中的这些文件原样迁入，保留已保存的文件夹、选项和上传历史；遇到同名数据冲突会停止迁移，不覆盖任何一份数据。PB/TOP5、赛事及CSV的结果报告仍随结果保存在你选择的输出位置。也可在项目根目录运行 `uv run main.py` 启动程序。

`tools/` 不参与正常启动。维护时从项目根目录以模块方式调用，例如 `uv run python -m tools.inspect_gsc`；修复脚本只应在需要处理对应历史问题时手动运行。


## 插件注册

四个工具均为内置插件，每个工具的界面与业务逻辑放在自己的目录。启动时自动发现 `plugins/` 下的Python包，调用各自 `plugin.py` 的 `register(registry)` 入口，再按 `order` 生成顶部功能页；主窗口没有四个工具的固定列表。新增工具不需要修改主窗口，重启即可加载。

例如新增 `plugins/example/`，包含 `__init__.py`、`ui.py` 和如下 `plugin.py`：

```python
from common.plugin_api import ToolSpec
from .ui import ExamplePanel

def register(registry):
    registry.register(ToolSpec('example', '示例工具', 50, ExamplePanel))
```

每个目录注册一个唯一标识。面板是 `ttk.Frame`，构造参数为 `(master, host)`，提供 `running`、`latest`、`settings` 和 `cancel_task()`；其中 `settings` 提供 `flush()`（现有工具使用 `AutoSettings`），配置仍写入 `data/`。主窗口统一保存设置、阻止多个工具同时运行、关闭时请求取消正在运行的工具。插件启动任务前应检查 `host.other_task_running(self)`；公共状态栏通过 `host.settings_status` 更新。

跨工具取结果通过 `host.get_result(tool_id)`，例如上传插件读取 `pb_top5` 的本次输出，无需导入PB插件内部代码。上次选中的功能按稳定的插件标识保存，新增或调整标签页顺序后仍能恢复，并兼容旧设置中的页码。

登记失败的插件会在状态栏显示原因，其他插件继续加载。这是本地代码注册机制，插件在重启时发现，不提供在线安装和运行中热加载。


`tests/` 和 `tools/` 是本地开发文件夹，按项目设置不提交到 Git；仓库下载版本可能不包含它们，测试和历史维护命令仅在相应文件存在时使用。

赛事插件标识为 `competition`，代码在 `plugins/competition/`，设置保存在 `data/competition_settings.json`。`rules.py` 管理比赛名称校验和三级别Top数量；计分、摘要门槛、矩阵布局和HTML均使用报告中记录的Top数量。
