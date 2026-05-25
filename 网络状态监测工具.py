# 这个文件是程序启动入口，负责创建主窗口并启动网络状态监测应用。
import tkinter as tk
from pathlib import Path
from tkinter import messagebox

from monitor.app import NetworkMonitorApp
from monitor.logger import log_error


def main() -> None:
    try:
        root = tk.Tk()
        NetworkMonitorApp(root, Path(__file__).resolve())
        root.mainloop()
    except Exception as exc:
        log_error(f"程序启动失败: {exc!r}")
        try:
            fallback = tk.Tk()
            fallback.withdraw()
            messagebox.showerror("网络状态监测", f"程序启动失败，请查看 error.log\n\n{exc}")
            fallback.destroy()
        except Exception:
            pass


if __name__ == "__main__":
    main()
