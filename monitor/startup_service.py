# 这个文件用于封装开机启动相关逻辑，统一处理注册表读写。
import winreg


def startup_command(executable: str, script: str) -> str:
    return f'"{executable}" "{script}"'


def is_startup_enabled(reg_path: str, startup_name: str, command: str) -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, reg_path) as key:
            value, _ = winreg.QueryValueEx(key, startup_name)
            return value == command
    except (FileNotFoundError, OSError):
        return False


def set_startup_enabled(reg_path: str, startup_name: str, command: str, enabled: bool) -> bool:
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            reg_path,
            0,
            winreg.KEY_SET_VALUE,
        ) as key:
            if enabled:
                winreg.SetValueEx(key, startup_name, 0, winreg.REG_SZ, command)
            else:
                try:
                    winreg.DeleteValue(key, startup_name)
                except FileNotFoundError:
                    pass
        return True
    except OSError:
        return False
