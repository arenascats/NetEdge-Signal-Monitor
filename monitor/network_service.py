# 这个文件用于封装网络检测逻辑，包括局域网 IPv4、公网 IPv4 和连通性检测。
import socket
import time
import urllib.request


def get_local_ipv4() -> str:
    try:
        candidates = socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET, socket.SOCK_STREAM)
        for item in candidates:
            ip = item[4][0]
            if not ip.startswith("127."):
                return ip
    except OSError:
        pass

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("8.8.8.8", 80))
        ip = sock.getsockname()[0]
        sock.close()
        return ip
    except OSError:
        return "获取失败"


def get_public_ipv4(urls: list[str]) -> str:
    for url in urls:
        try:
            with urllib.request.urlopen(url, timeout=2.5) as resp:
                return resp.read().decode("utf-8").strip()
        except Exception:
            continue
    return "获取失败"


def check_connectivity() -> tuple[bool, float]:
    start = time.perf_counter()
    try:
        with socket.create_connection(("8.8.8.8", 53), timeout=2.0):
            latency = (time.perf_counter() - start) * 1000
            return True, latency
    except OSError:
        return False, -1
