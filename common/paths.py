"""Stable runtime data paths, independent of source file layout."""
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / 'data'

# Only application-owned runtime files; never scan or move replay inputs.
LEGACY_DATA_NAMES = (
    'settings.json', 'app_settings.json', 'upload_settings.json',
    'gsc_settings.json', 'csv_merge_settings.json', 'confirmed_completed.json',
    'metadata.sqlite3', 'metadata.sqlite3-wal', 'metadata.sqlite3-shm',
    'metadata.sqlite3-journal', 'upload_history.sqlite3',
    'upload_history.sqlite3-wal', 'upload_history.sqlite3-shm',
    'upload_history.sqlite3-journal', 'upload_reports',
)


def prepare_data_dir(project_root=PROJECT_ROOT):
    """Move legacy runtime files intact; refuse to overwrite existing data."""
    project_root = Path(project_root).resolve()
    destination = project_root / 'data'
    if destination.is_symlink() or destination.is_junction():
        raise ValueError(f'数据目录不能是目录联接或符号链接：{destination}')
    pending = [(project_root / name, destination / name) for name in LEGACY_DATA_NAMES
               if (project_root / name).exists()]
    for source, target in pending:
        if target.exists():
            raise FileExistsError(f'数据迁移冲突，请保留并核对这两个文件或目录：{source} 和 {target}')
        if source.is_symlink() or source.is_junction():
            raise ValueError(f'数据迁移不处理目录联接或符号链接：{source}')
    destination.mkdir(parents=True, exist_ok=True)
    for source, target in pending:
        # Both resolved paths are constrained to this explicitly selected project.
        if not source.resolve().is_relative_to(project_root) or not target.resolve().is_relative_to(project_root):
            raise ValueError('数据迁移路径超出项目目录')
        source.rename(target)
    return destination
