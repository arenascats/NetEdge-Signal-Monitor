# 这个文件用于读写本地设置文件，提供配置持久化能力。
import json
from pathlib import Path

try:
    from .logger import log_error
except ImportError:
    from logger import log_error  # type: ignore


def load_settings(path: Path) -> dict:
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
            log_error(f"settings.json 内容类型错误，期望对象，实际: {type(data).__name__}")
    except json.JSONDecodeError as exc:
        log_error(f"settings.json JSON 解析失败: {exc}")
    except OSError as exc:
        log_error(f"settings.json 读取失败: {exc}")
    return {}


def save_settings(path: Path, data: dict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as exc:
        log_error(f"settings.json 写入失败: {exc}")
