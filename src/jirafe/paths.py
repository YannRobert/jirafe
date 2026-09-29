"""Default locations of the configuration and of the local copy, following each system's conventions.

Linux follows the XDG specification (XDG_CONFIG_HOME, XDG_CACHE_HOME), macOS ~/Library, Windows APPDATA and
LOCALAPPDATA. The local copy is a cache: the system or the user may delete it, it rebuilds itself.
"""
import os
import sys
from pathlib import Path

from .constants import APP_NAME, CONFIG_FILE_NAME


def default_config_file():
    return config_dir() / CONFIG_FILE_NAME


def config_dir():
    home = Path.home()
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA") or home / "AppData" / "Roaming") / APP_NAME
    if sys.platform == "darwin":
        return home / "Library" / "Application Support" / APP_NAME
    return xdg_dir(
        "XDG_CONFIG_HOME",
        home / ".config"
    ) / APP_NAME


def cache_dir():
    home = Path.home()
    if sys.platform == "win32":
        # LOCALAPPDATA rather than APPDATA: a cache has no business following a roaming profile across machines.
        return Path(os.environ.get("LOCALAPPDATA") or home / "AppData" / "Local") / APP_NAME / "cache"
    if sys.platform == "darwin":
        return home / "Library" / "Caches" / APP_NAME
    return xdg_dir(
        "XDG_CACHE_HOME",
        home / ".cache"
    ) / APP_NAME


def xdg_dir(
        variable,
        fallback
):
    # The XDG specification requires ignoring an empty or relative value.
    value = os.environ.get(variable, "")
    return Path(value) if os.path.isabs(value) else fallback
