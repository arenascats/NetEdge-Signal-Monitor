# 这个文件用于记录运行时错误，方便排查配置错误、写入失败等问题。
from pathlib import Path
from datetime import datetime


LOG_FILE = Path(__file__).resolve().parent.parent / "error.log"


def log_error(message: str) -> None:
    try:
        line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}\n"
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(line)
    except OSError:
        pass
