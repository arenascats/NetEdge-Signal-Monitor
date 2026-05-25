# 这个文件用于定义项目的默认常量，避免在多个模块里重复硬编码。
from pathlib import Path

REFRESH_MS_DEFAULT = 5000
AUTO_HIDE_DELAY_MS_DEFAULT = 1600
SNAP_DISTANCE_DEFAULT = 28
EDGE_VISIBLE_WIDTH_DEFAULT = 14

PUBLIC_IPV4_URLS = [
    "https://api4.ipify.org",
    "https://ipv4.icanhazip.com",
]

STARTUP_REG_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
STARTUP_NAME = "NetworkStatusMonitor"

STRIP_PRESETS = {
    "bar_small": {"width": 14, "style": "bar"},
    "bar_medium": {"width": 20, "style": "bar"},
    "bar_large": {"width": 28, "style": "bar"},
    "circle_small": {"width": 24, "style": "circle"},
    "circle_large": {"width": 34, "style": "circle"},
}


def settings_path(base_dir: Path) -> Path:
    return base_dir / "settings.json"
