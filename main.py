# 这个文件保留为兼容入口，实际启动逻辑在“网络状态监测工具.py”中。
from pathlib import Path

from monitor.app import NetworkMonitorApp
import tkinter as tk


def main() -> None:
    root = tk.Tk()
    NetworkMonitorApp(root, Path(__file__).resolve().with_name("网络状态监测工具.py"))
    root.mainloop()


if __name__ == "__main__":
    main()
