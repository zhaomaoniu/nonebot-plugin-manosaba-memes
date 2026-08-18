from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import nonebot_plugin_localstore as localstore

from ..models import Character

DIST_NAME = "nonebot-plugin-manosaba-memes"
REPOSITORY_URL = "https://github.com/zhaomaoniu/nonebot-plugin-manosaba-memes"
PREFAB_DIRECTORY = "prefabs"
REQUIRED_CHARACTERS = frozenset(character.value for character in Character)


def plugin_version() -> str:
    try:
        return version(DIST_NAME)
    except PackageNotFoundError:
        return "0.0.0"


def prefab_archive_name(current_version: str | None = None) -> str:
    current_version = current_version or plugin_version()
    return f"manosaba-prefabs-{current_version}.tar.gz"


def prefab_release_url(current_version: str | None = None) -> str:
    current_version = current_version or plugin_version()
    filename = prefab_archive_name(current_version)
    return f"{REPOSITORY_URL}/releases/download/v{current_version}/{filename}"


def prefab_install_dir() -> Path:
    """Return the directory into which the release archive should be extracted."""
    return localstore.get_plugin_data_dir()


def prefab_asset_root() -> Path:
    return prefab_install_dir() / PREFAB_DIRECTORY


def _character_is_complete(path: Path) -> bool:
    return (
        (path / "character.json").is_file()
        and (path / "composition.json").is_file()
        and (path / "sprites").is_dir()
    )


@dataclass(frozen=True)
class PrefabAssetStatus:
    root: Path
    missing_characters: tuple[str, ...]

    @property
    def available(self) -> bool:
        return not self.missing_characters


def prefab_asset_status(root: Path | None = None) -> PrefabAssetStatus:
    root = root or prefab_asset_root()
    missing = tuple(
        sorted(
            character
            for character in REQUIRED_CHARACTERS
            if not _character_is_complete(root / character)
        )
    )
    return PrefabAssetStatus(root=root, missing_characters=missing)


def prefab_unavailable_message(status: PrefabAssetStatus | None = None) -> str:
    status = status or prefab_asset_status()
    missing = "、".join(status.missing_characters)
    return (
        "立绘功能未启用：未找到完整的角色资源。\n"
        f"缺少：{missing}\n"
        f"请下载与当前插件版本对应的 {prefab_archive_name()}，"
        "并将压缩包解压到：\n"
        f"{status.root.parent}\n"
        f"下载地址：{prefab_release_url()}\n"
        f"解压后应存在：{status.root / 'AnAn' / 'character.json'}"
    )
