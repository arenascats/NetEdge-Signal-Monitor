# 这个文件用于实现主界面和交互行为，负责把网络检测、设置和开机启动功能组合成完整应用。
import ctypes
import sys
import threading
import time
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import ttk
from tkinter import messagebox

try:
    import pystray
    from PIL import Image, ImageDraw
except Exception:
    pystray = None
    Image = None
    ImageDraw = None

try:
    import psutil
except Exception:
    psutil = None

try:
    from .constants import (
        AUTO_HIDE_DELAY_MS_DEFAULT,
        EDGE_VISIBLE_WIDTH_DEFAULT,
        PUBLIC_IPV4_URLS,
        REFRESH_MS_DEFAULT,
        SNAP_DISTANCE_DEFAULT,
        STARTUP_NAME,
        STARTUP_REG_PATH,
        STRIP_PRESETS,
        settings_path,
    )
    from .network_service import check_connectivity, get_local_ipv4, get_public_ipv4
    from .logger import log_error
    from .settings_service import load_settings, save_settings
    from .startup_service import is_startup_enabled, set_startup_enabled, startup_command
except ImportError:
    from constants import (  # type: ignore
        AUTO_HIDE_DELAY_MS_DEFAULT,
        EDGE_VISIBLE_WIDTH_DEFAULT,
        PUBLIC_IPV4_URLS,
        REFRESH_MS_DEFAULT,
        SNAP_DISTANCE_DEFAULT,
        STARTUP_NAME,
        STARTUP_REG_PATH,
        STRIP_PRESETS,
        settings_path,
    )
    from network_service import check_connectivity, get_local_ipv4, get_public_ipv4  # type: ignore
    from logger import log_error  # type: ignore
    from settings_service import load_settings, save_settings  # type: ignore
    from startup_service import is_startup_enabled, set_startup_enabled, startup_command  # type: ignore


class NetworkMonitorApp:
    def __init__(self, root: tk.Tk, entry_script: Path) -> None:
        self.root = root
        self.entry_script = entry_script
        self.settings_file = settings_path(entry_script.parent)
        self.app_icon_path = self._detect_icon_path()

        self.root.title("网络状态监测")
        self.root.geometry("420x290+80+80")
        self.root.resizable(False, False)
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self._apply_window_icon(self.root)

        self.drag_x = 0
        self.drag_y = 0
        self.refresh_running = False
        self.destroyed = False
        self.refresh_timer_job: str | None = None
        self.anim_job: str | None = None

        self.snapped_edge: str | None = None
        self.hidden_to_edge = False
        self.hide_job: str | None = None
        self.hide_watch_job: str | None = None
        self.mouse_inside_main = False
        self.pinned = False
        self.net_prev = None
        self.net_prev_ts = None

        self.refresh_ms = REFRESH_MS_DEFAULT
        self.auto_hide_delay_ms = AUTO_HIDE_DELAY_MS_DEFAULT
        self.snap_distance = SNAP_DISTANCE_DEFAULT
        self.edge_visible_width = EDGE_VISIBLE_WIDTH_DEFAULT
        self.default_edge = "left"
        self.start_collapsed = False
        self.strip_mode = "bar_small"
        self.strip_style = "bar"
        self.last_signal_level = "yellow"

        self.settings_window: tk.Toplevel | None = None
        self.tray_icon = None
        self.tray_thread: threading.Thread | None = None
        self.tray_supported = pystray is not None and Image is not None and ImageDraw is not None
        self.always_on_top_var = tk.BooleanVar(value=True)
        self.default_edge_var = tk.StringVar(value="left")
        self.start_collapsed_var = tk.BooleanVar(value=True)
        self.strip_mode_var = tk.StringVar(value="bar_small")
        self.startup_var = tk.BooleanVar(value=False)

        self._load_settings()
        self._build_ui()
        self._bind_drag(self.root)

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self._sync_startup_checkbox()
        self._start_tray_icon()
        self._show_default_strip_mode()
        self._start_hide_watch()
        self.refresh_data()

    def _build_ui(self) -> None:
        style = ttk.Style()
        style.theme_use("clam")
        style.configure(
            "Dark.Horizontal.TProgressbar",
            troughcolor="#1F1F1F",
            background="#2C7BE5",
            bordercolor="#1F1F1F",
            lightcolor="#2C7BE5",
            darkcolor="#2C7BE5",
        )

        self.panel = tk.Frame(self.root, bg="#121212", padx=10, pady=10)
        self.panel.pack(fill="both", expand=True)

        title_row = tk.Frame(self.panel, bg="#121212")
        title_row.pack(fill="x", pady=(0, 8))

        title = tk.Label(
            title_row,
            text="网络状态监测",
            fg="#EAEAEA",
            bg="#121212",
            font=("Microsoft YaHei UI", 11, "bold"),
        )
        title.pack(side="left")

        version_label = tk.Label(
            title_row,
            text="v1.0.1",
            fg="#8F8F8F",
            bg="#121212",
            font=("Microsoft YaHei UI", 9),
        )
        version_label.pack(side="left", padx=(8, 0))

        self.settings_btn = tk.Button(
            title_row,
            text="⚙",
            command=self._open_settings,
            width=3,
            bg="#1C1C1C",
            fg="#EAEAEA",
            relief="flat",
            cursor="hand2",
            font=("Segoe UI Symbol", 10),
        )
        self.settings_btn.pack(side="right")

        close_btn = tk.Button(
            title_row,
            text="X",
            command=self._quit_from_ui,
            width=3,
            bg="#3A1D1D",
            fg="#F2F2F2",
            relief="flat",
            cursor="hand2",
            font=("Segoe UI", 9, "bold"),
        )
        close_btn.pack(side="right", padx=(4, 0))

        self.pin_btn = tk.Button(
            title_row,
            text="PIN",
            command=self._toggle_pin,
            width=4,
            bg="#1F2D1F",
            fg="#B8E8C8",
            relief="flat",
            cursor="hand2",
            font=("Segoe UI", 8, "bold"),
        )
        self.pin_btn.pack(side="right", padx=(4, 0))

        self.local_ip_var = tk.StringVar(value="局域网 IPv4: 获取中...")
        self.public_ip_var = tk.StringVar(value="公网 IPv4: 获取中...")
        self.status_var = tk.StringVar(value="外网连通性: 检测中...")
        self.latency_var = tk.StringVar(value="网络延迟: 检测中...")
        self.speed_var = tk.StringVar(value="网速: ↑ - / ↓ -")
        self.updated_var = tk.StringVar(value="上次刷新: -")

        for var in [
            self.local_ip_var,
            self.public_ip_var,
            self.status_var,
            self.latency_var,
            self.speed_var,
            self.updated_var,
        ]:
            tk.Label(
                self.panel,
                textvariable=var,
                fg="#F2F2F2",
                bg="#121212",
                font=("Microsoft YaHei UI", 9),
            ).pack(anchor="w", pady=1)

        button_row = tk.Frame(self.panel, bg="#121212")
        button_row.pack(fill="x", pady=(8, 0))

        self.refresh_btn = tk.Button(
            button_row,
            text="立即刷新",
            command=self.refresh_data,
            width=10,
            bg="#2C7BE5",
            fg="white",
            relief="flat",
            cursor="hand2",
        )
        self.refresh_btn.pack(side="left")

        tk.Button(
            button_row,
            text="贴右边隐藏",
            command=self._dock_to_right_hide,
            width=10,
            bg="#3A3A3A",
            fg="white",
            relief="flat",
            cursor="hand2",
        ).pack(side="left", padx=(6, 0))

        tk.Button(
            button_row,
            text="贴左边隐藏",
            command=self._dock_to_left_hide,
            width=10,
            bg="#2F2F2F",
            fg="white",
            relief="flat",
            cursor="hand2",
        ).pack(side="left", padx=(6, 0))

        link_row = tk.Frame(self.panel, bg="#121212")
        link_row.pack(fill="x", pady=(6, 0))

        tk.Button(
            link_row,
            text="访问github",
            command=lambda: self._open_link("https://github.com"),
            width=12,
            bg="#1F2A44",
            fg="white",
            relief="flat",
            cursor="hand2",
        ).pack(side="left")

        tk.Button(
            link_row,
            text="查看哔站主页",
            command=lambda: self._open_link("https://space.bilibili.com"),
            width=12,
            bg="#3A2550",
            fg="white",
            relief="flat",
            cursor="hand2",
        ).pack(side="left", padx=(6, 0))

        self._build_edge_strip()
        self._update_signal_lamp("yellow")
        self._hide_edge_strip()

        # 保证新增信息和按钮不会被固定窗口高度裁切
        self.root.update_idletasks()
        min_h = max(290, self.panel.winfo_reqheight() + 20)
        min_w = max(420, self.panel.winfo_reqwidth() + 20)
        self.root.minsize(min_w, min_h)
        self.root.geometry(f"{min_w}x{min_h}+{self.root.winfo_x()}+{self.root.winfo_y()}")

    def _apply_strip_preset(self) -> None:
        preset = STRIP_PRESETS.get(self.strip_mode, STRIP_PRESETS["bar_small"])
        self.edge_visible_width = int(preset["width"])
        self.strip_style = str(preset["style"])
        self.strip_mode_var.set(self.strip_mode)

    def _build_edge_strip(self) -> None:
        if hasattr(self, "edge_strip") and self.edge_strip.winfo_exists():
            self.edge_strip.destroy()

        self.edge_strip = tk.Frame(self.root, bg="#0D0D0D", width=self.edge_visible_width)
        self.edge_strip.bind("<ButtonPress-1>", self._on_edge_strip_click)
        self.edge_strip.bind("<Enter>", self._on_edge_strip_hover)
        self.edge_lights: dict[str, tk.Widget] = {}
        self.edge_circles: dict[str, int] = {}

        if self.strip_style == "circle":
            pad = 2 if self.strip_mode == "circle_small" else 3
            size = self.edge_visible_width - (pad * 4)
            for name in ["green", "yellow", "red"]:
                holder = tk.Frame(self.edge_strip, bg="#0D0D0D")
                holder.pack(fill="both", expand=True, padx=pad, pady=pad)
                holder.bind("<ButtonPress-1>", self._on_edge_strip_click)
                holder.bind("<Enter>", self._on_edge_strip_hover)
                canvas = tk.Canvas(holder, bg="#0D0D0D", highlightthickness=0, bd=0)
                canvas.pack(fill="both", expand=True)
                canvas.bind("<ButtonPress-1>", self._on_edge_strip_click)
                canvas.bind("<Enter>", self._on_edge_strip_hover)
                dot = canvas.create_oval(2, 2, max(6, size), max(6, size), fill="#555555", outline="")
                self.edge_lights[name] = canvas
                self.edge_circles[name] = dot
        else:
            for name in ["green", "yellow", "red"]:
                holder = tk.Frame(self.edge_strip, bg="#0D0D0D")
                holder.pack(fill="both", expand=True, padx=2, pady=2)
                holder.bind("<ButtonPress-1>", self._on_edge_strip_click)
                holder.bind("<Enter>", self._on_edge_strip_hover)
                lamp = tk.Frame(holder, bg="#2B2B2B")
                lamp.pack(fill="both", expand=True)
                lamp.bind("<ButtonPress-1>", self._on_edge_strip_click)
                lamp.bind("<Enter>", self._on_edge_strip_hover)
                self.edge_lights[name] = lamp

    def _bind_drag(self, widget: tk.Widget) -> None:
        widget.bind("<ButtonPress-1>", self._start_drag)
        widget.bind("<B1-Motion>", self._do_drag)
        widget.bind("<ButtonRelease-1>", self._end_drag)
        for child in widget.winfo_children():
            self._bind_drag(child)

    def _start_drag(self, event: tk.Event) -> None:
        if self.hidden_to_edge:
            self._restore_from_edge()
        self._cancel_auto_hide()
        self.drag_x = event.x_root - self.root.winfo_x()
        self.drag_y = event.y_root - self.root.winfo_y()

    def _do_drag(self, event: tk.Event) -> None:
        self.root.geometry(f"+{event.x_root - self.drag_x}+{event.y_root - self.drag_y}")

    def _end_drag(self, _event: tk.Event) -> None:
        self._snap_if_close_to_edge()

    def _get_virtual_screen_bounds(self) -> tuple[int, int, int, int]:
        try:
            user32 = ctypes.windll.user32
            left = user32.GetSystemMetrics(76)
            top = user32.GetSystemMetrics(77)
            width = user32.GetSystemMetrics(78)
            height = user32.GetSystemMetrics(79)
            return left, top, left + width, top + height
        except Exception:
            width = self.root.winfo_screenwidth()
            height = self.root.winfo_screenheight()
            return 0, 0, width, height

    def _snap_if_close_to_edge(self) -> None:
        self.root.update_idletasks()
        x = self.root.winfo_x()
        y = self.root.winfo_y()
        width = self.root.winfo_width()
        height = self.root.winfo_height()

        left_bound, top_bound, right_bound, bottom_bound = self._get_virtual_screen_bounds()
        y = max(top_bound, min(y, bottom_bound - height))

        left_distance = abs(x - left_bound)
        right_distance = abs(right_bound - (x + width))
        hidden_left = max(0, left_bound - x)
        hidden_right = max(0, (x + width) - right_bound)
        hidden_left_half_or_more = hidden_left >= (width / 2)
        hidden_right_half_or_more = hidden_right >= (width / 2)

        snapped = False
        if hidden_left_half_or_more:
            x = left_bound
            self.snapped_edge = "left"
            snapped = True
        elif hidden_right_half_or_more:
            x = right_bound - width
            self.snapped_edge = "right"
            snapped = True
        elif left_distance <= self.snap_distance and left_distance <= right_distance:
            x = left_bound
            self.snapped_edge = "left"
            snapped = True
        elif right_distance <= self.snap_distance:
            x = right_bound - width
            self.snapped_edge = "right"
            snapped = True
        else:
            self.snapped_edge = None

        self.root.geometry(f"+{x}+{y}")

        if snapped:
            self._schedule_auto_hide()
        else:
            self.hidden_to_edge = False
            self._cancel_auto_hide()
            self._hide_edge_strip()

    def _schedule_auto_hide(self) -> None:
        self._cancel_auto_hide()
        if self.pinned or self.mouse_inside_main or self.refresh_running:
            return
        self.hide_job = self.root.after(self.auto_hide_delay_ms, self._hide_to_edge)

    def _cancel_auto_hide(self) -> None:
        if self.hide_job is not None:
            self.root.after_cancel(self.hide_job)
            self.hide_job = None

    def _hide_to_edge(self, force: bool = False) -> None:
        if self.destroyed or self.snapped_edge is None:
            return
        if (self.mouse_inside_main or self.pinned) and not force:
            return

        self.root.update_idletasks()
        width = self.root.winfo_width()
        y = self.root.winfo_y()
        left_bound, _, right_bound, _ = self._get_virtual_screen_bounds()

        if self.snapped_edge == "left":
            x = left_bound - (width - self.edge_visible_width)
            strip_side = "right"
        else:
            x = right_bound - self.edge_visible_width
            strip_side = "left"

        self._animate_hide_to(x, y, strip_side)

    def _animate_hide_to(self, target_x: int, y: int, strip_side: str) -> None:
        if self.anim_job is not None:
            self.root.after_cancel(self.anim_job)
            self.anim_job = None

        start_x = self.root.winfo_x()
        distance = abs(target_x - start_x)
        steps = max(10, min(22, distance // 14 if distance > 0 else 10))
        duration_ms = 280
        step_ms = max(10, duration_ms // steps)
        self._hide_edge_strip()

        def frame(i: int) -> None:
            if self.destroyed:
                return
            t = i / steps
            eased = 1 - (1 - t) ** 3
            current_x = int(start_x + (target_x - start_x) * eased)
            self.root.geometry(f"+{current_x}+{y}")
            if i < steps:
                self.anim_job = self.root.after(step_ms, lambda: frame(i + 1))
            else:
                self.anim_job = None
                self.hidden_to_edge = True
                self._show_edge_strip(strip_side)

        frame(1)

    def _restore_from_edge(self) -> None:
        if self.snapped_edge is None:
            return

        self.root.update_idletasks()
        width = self.root.winfo_width()
        y = self.root.winfo_y()
        left_bound, _, right_bound, _ = self._get_virtual_screen_bounds()
        x = left_bound if self.snapped_edge == "left" else (right_bound - width)

        self.root.geometry(f"+{x}+{y}")
        self.hidden_to_edge = False
        self._hide_edge_strip()
        self._schedule_auto_hide()

    def _show_edge_strip(self, side: str) -> None:
        self.root.update_idletasks()
        width = self.root.winfo_width()
        x = 0 if side == "left" else (width - self.edge_visible_width)
        self.edge_strip.place(x=x, y=0, width=self.edge_visible_width, relheight=1.0)
        self.edge_strip.lift()

    def _hide_edge_strip(self) -> None:
        self.edge_strip.place_forget()

    def _on_edge_strip_click(self, _event: tk.Event) -> None:
        if self.hidden_to_edge:
            self._restore_from_edge()

    def _on_edge_strip_hover(self, _event: tk.Event) -> None:
        if self.hidden_to_edge:
            self._restore_from_edge()

    def _start_hide_watch(self) -> None:
        if self.hide_watch_job is not None:
            self.root.after_cancel(self.hide_watch_job)
        self.hide_watch_job = self.root.after(150, self._hide_watch_tick)

    def _hide_watch_tick(self) -> None:
        if self.destroyed:
            return
        try:
            px, py = self.root.winfo_pointerxy()
            hovered = self.root.winfo_containing(px, py)
            self.mouse_inside_main = hovered is not None and hovered.winfo_toplevel() == self.root
        except Exception:
            self.mouse_inside_main = False

        if self.pinned:
            self._cancel_auto_hide()
        elif self.snapped_edge and not self.hidden_to_edge:
            if self.mouse_inside_main:
                self._cancel_auto_hide()
            else:
                self._schedule_auto_hide()

        self.hide_watch_job = self.root.after(150, self._hide_watch_tick)

    def _show_default_strip_mode(self) -> None:
        if not self.start_collapsed:
            return
        left_bound, top_bound, right_bound, _ = self._get_virtual_screen_bounds()
        self.root.update_idletasks()
        width = self.root.winfo_width()
        self.snapped_edge = self.default_edge
        x = left_bound if self.default_edge == "left" else (right_bound - width)
        self.root.geometry(f"+{x}+{top_bound + 80}")
        self.root.after(100, self._hide_to_edge)

    def _dock_to_right_edge(self) -> None:
        self.root.update_idletasks()
        if self.hidden_to_edge:
            self._restore_from_edge()
        self._cancel_auto_hide()

        width = self.root.winfo_width()
        height = self.root.winfo_height()
        y = self.root.winfo_y()
        _, top_bound, right_bound, bottom_bound = self._get_virtual_screen_bounds()
        y = max(top_bound, min(y, bottom_bound - height))

        self.snapped_edge = "right"
        self.root.geometry(f"+{right_bound - width}+{y}")
        self.hidden_to_edge = False
        self._hide_edge_strip()
        self._hide_to_edge(force=True)

    def _dock_and_hide_now(self) -> None:
        self.root.update_idletasks()
        if self.hidden_to_edge:
            self._restore_from_edge()
        self._cancel_auto_hide()
        self._snap_if_close_to_edge()
        if self.snapped_edge is None:
            # 不在吸附范围时，按当前更近的一侧强制吸附后收起
            x = self.root.winfo_x()
            width = self.root.winfo_width()
            left_bound, _, right_bound, _ = self._get_virtual_screen_bounds()
            left_distance = abs(x - left_bound)
            right_distance = abs(right_bound - (x + width))
            self.snapped_edge = "left" if left_distance <= right_distance else "right"
            y = self.root.winfo_y()
            nx = left_bound if self.snapped_edge == "left" else (right_bound - width)
            self.root.geometry(f"+{nx}+{y}")
        self.hidden_to_edge = False
        self._hide_to_edge(force=True)

    def _dock_to_right_hide(self) -> None:
        self._dock_to_edge_hide("right")

    def _dock_to_left_hide(self) -> None:
        self._dock_to_edge_hide("left")

    def _dock_to_edge_hide(self, side: str) -> None:
        self.root.update_idletasks()
        if self.hidden_to_edge:
            self._restore_from_edge()
        self._cancel_auto_hide()

        width = self.root.winfo_width()
        height = self.root.winfo_height()
        y = self.root.winfo_y()
        left_bound, top_bound, right_bound, bottom_bound = self._get_virtual_screen_bounds()
        y = max(top_bound, min(y, bottom_bound - height))

        self.snapped_edge = side
        x = left_bound if side == "left" else (right_bound - width)
        self.root.geometry(f"+{x}+{y}")
        self.hidden_to_edge = False
        self._hide_edge_strip()
        self._hide_to_edge(force=True)

    def _toggle_pin(self) -> None:
        self.pinned = not self.pinned
        if self.pinned:
            self.pin_btn.configure(bg="#2D6A3D", fg="#E8FFEF", text="PIN*")
            self._cancel_auto_hide()
            if self.hidden_to_edge:
                self._restore_from_edge()
        else:
            self.pin_btn.configure(bg="#1F2D1F", fg="#B8E8C8", text="PIN")
            if self.snapped_edge and not self.hidden_to_edge:
                self._schedule_auto_hide()

    def refresh_data(self) -> None:
        if self.destroyed or self.refresh_running:
            return

        if self.refresh_timer_job is not None:
            self.root.after_cancel(self.refresh_timer_job)
            self.refresh_timer_job = None

        self.refresh_running = True
        self.refresh_btn.configure(text="刷新中...", state="disabled")
        threading.Thread(target=self._collect_data, daemon=True).start()

    def _collect_data(self) -> None:
        local_ip = get_local_ipv4()
        public_ip = get_public_ipv4(PUBLIC_IPV4_URLS)
        online, latency_ms = check_connectivity()
        lan_connected = local_ip != "获取失败"

        up_speed, down_speed = self._get_net_speed()

        if online:
            signal_level = "green"
            status_text = "外网连通性: 已连接（互联网）"
        elif lan_connected:
            signal_level = "yellow"
            status_text = "外网连通性: 未连接（仅局域网）"
        else:
            signal_level = "red"
            status_text = "外网连通性: 未连接（局域网断开）"

        def update_ui() -> None:
            if self.destroyed:
                return

            self.local_ip_var.set(f"局域网 IPv4: {local_ip}")
            self.public_ip_var.set(f"公网 IPv4: {public_ip}")
            self.status_var.set(status_text)
            self.latency_var.set(f"网络延迟: {latency_ms:.1f} ms" if latency_ms >= 0 else "网络延迟: -")
            self.speed_var.set(f"网速: ↑ {up_speed} / ↓ {down_speed}")
            self.updated_var.set(f"上次刷新: {time.strftime('%H:%M:%S')}")

            self._update_signal_lamp(signal_level)
            self.refresh_btn.configure(text="立即刷新", state="normal")
            self.refresh_running = False
            self.refresh_timer_job = self.root.after(self.refresh_ms, self.refresh_data)

        self.root.after(0, update_ui)

    def _update_signal_lamp(self, level: str) -> None:
        active_colors = {"green": "#20E06F", "yellow": "#FFD04D", "red": "#FF5B5B"}
        inactive_colors = {"green": "#4F7A62", "yellow": "#807252", "red": "#815B5B"}

        self.last_signal_level = level
        for name, lamp in self.edge_lights.items():
            color = active_colors[name] if name == level else inactive_colors[name]
            if self.strip_style == "circle":
                lamp.itemconfig(self.edge_circles[name], fill=color)
            else:
                lamp.configure(bg=color)

    def _get_net_speed(self) -> tuple[str, str]:
        if psutil is None:
            return "-", "-"
        try:
            now = time.time()
            counters = psutil.net_io_counters()
            if self.net_prev is None or self.net_prev_ts is None:
                self.net_prev = counters
                self.net_prev_ts = now
                return "-", "-"
            elapsed = max(0.1, now - self.net_prev_ts)
            up_bps = max(0.0, (counters.bytes_sent - self.net_prev.bytes_sent) / elapsed)
            down_bps = max(0.0, (counters.bytes_recv - self.net_prev.bytes_recv) / elapsed)
            self.net_prev = counters
            self.net_prev_ts = now
            return self._fmt_speed(up_bps), self._fmt_speed(down_bps)
        except Exception as exc:
            log_error(f"网速计算失败: {exc!r}")
            return "-", "-"

    @staticmethod
    def _fmt_speed(bps: float) -> str:
        kb = bps / 1024.0
        if kb < 1024:
            return f"{kb:.1f} KB/s"
        return f"{(kb / 1024.0):.2f} MB/s"

    def _open_link(self, url: str) -> None:
        try:
            webbrowser.open(url)
        except Exception as exc:
            log_error(f"打开链接失败 {url}: {exc!r}")

    def _open_settings(self) -> None:
        if self.settings_window and self.settings_window.winfo_exists():
            self.settings_window.lift()
            self.settings_window.focus_force()
            return

        win = tk.Toplevel(self.root)
        win.title("设置")
        win.resizable(False, False)
        win.attributes("-topmost", True)
        win.configure(bg="#171717")
        self._apply_window_icon(win)
        self.settings_window = win
        self.root.update_idletasks()
        win.geometry(f"+{self.root.winfo_x()}+{self.root.winfo_y()}")

        body = tk.Frame(win, bg="#171717", padx=12, pady=12)
        body.pack(fill="both", expand=True)

        tk.Label(body, text="刷新间隔(秒)", fg="#F2F2F2", bg="#171717").pack(anchor="w")
        refresh_scale = tk.Scale(body, from_=2, to=30, orient="horizontal", bg="#171717", fg="#F2F2F2", highlightthickness=0, troughcolor="#2A2A2A")
        refresh_scale.set(max(2, int(self.refresh_ms / 1000)))
        refresh_scale.pack(fill="x")

        tk.Label(body, text="贴边吸附距离(像素)", fg="#F2F2F2", bg="#171717").pack(anchor="w", pady=(8, 0))
        snap_scale = tk.Scale(body, from_=8, to=80, orient="horizontal", bg="#171717", fg="#F2F2F2", highlightthickness=0, troughcolor="#2A2A2A")
        snap_scale.set(self.snap_distance)
        snap_scale.pack(fill="x")

        tk.Label(body, text="自动收起延迟(毫秒)", fg="#F2F2F2", bg="#171717").pack(anchor="w", pady=(8, 0))
        hide_scale = tk.Scale(body, from_=300, to=5000, resolution=100, orient="horizontal", bg="#171717", fg="#F2F2F2", highlightthickness=0, troughcolor="#2A2A2A")
        hide_scale.set(self.auto_hide_delay_ms)
        hide_scale.pack(fill="x")

        tk.Label(body, text="启动默认贴边", fg="#F2F2F2", bg="#171717").pack(anchor="w", pady=(8, 0))
        edge_row = tk.Frame(body, bg="#171717")
        edge_row.pack(anchor="w")
        tk.Radiobutton(edge_row, text="左侧", value="left", variable=self.default_edge_var, bg="#171717", fg="#F2F2F2", selectcolor="#171717", activebackground="#171717", activeforeground="#F2F2F2").pack(side="left")
        tk.Radiobutton(edge_row, text="右侧", value="right", variable=self.default_edge_var, bg="#171717", fg="#F2F2F2", selectcolor="#171717", activebackground="#171717", activeforeground="#F2F2F2").pack(side="left", padx=(8, 0))

        tk.Checkbutton(body, text="启动时自动收起为边缘条", variable=self.start_collapsed_var, bg="#171717", fg="#F2F2F2", selectcolor="#171717", activebackground="#171717", activeforeground="#F2F2F2").pack(anchor="w", pady=(8, 0))
        tk.Checkbutton(body, text="窗口置顶", variable=self.always_on_top_var, bg="#171717", fg="#F2F2F2", selectcolor="#171717", activebackground="#171717", activeforeground="#F2F2F2").pack(anchor="w", pady=(8, 0))
        tk.Checkbutton(body, text="开机自动启动", variable=self.startup_var, bg="#171717", fg="#F2F2F2", selectcolor="#171717", activebackground="#171717", activeforeground="#F2F2F2").pack(anchor="w", pady=(8, 0))

        tk.Label(body, text="边缘灯样式", fg="#F2F2F2", bg="#171717").pack(anchor="w", pady=(8, 0))
        style_frame = tk.Frame(body, bg="#171717")
        style_frame.pack(anchor="w")
        options = [("竖条小", "bar_small"), ("竖条中", "bar_medium"), ("竖条大", "bar_large"), ("圆形小", "circle_small"), ("圆形大", "circle_large")]
        for i, (label, value) in enumerate(options):
            tk.Radiobutton(style_frame, text=label, value=value, variable=self.strip_mode_var, bg="#171717", fg="#F2F2F2", selectcolor="#171717", activebackground="#171717", activeforeground="#F2F2F2").grid(row=i // 3, column=i % 3, sticky="w", padx=(0, 10))

        btn_row = tk.Frame(body, bg="#171717")
        btn_row.pack(fill="x", pady=(10, 0))

        def apply_settings() -> None:
            was_hidden = self.hidden_to_edge
            hidden_side = None
            if was_hidden and self.snapped_edge is not None:
                hidden_side = "right" if self.snapped_edge == "left" else "left"

            self.refresh_ms = int(refresh_scale.get()) * 1000
            self.snap_distance = int(snap_scale.get())
            self.auto_hide_delay_ms = int(hide_scale.get())
            self.root.attributes("-topmost", self.always_on_top_var.get())
            self.default_edge = self.default_edge_var.get()
            self.start_collapsed = self.start_collapsed_var.get()
            selected_mode = self.strip_mode_var.get()
            self.strip_mode = selected_mode if selected_mode in STRIP_PRESETS else "bar_small"
            self._apply_strip_preset()
            self._build_edge_strip()
            self._update_signal_lamp(self.last_signal_level)
            if was_hidden and hidden_side is not None:
                self._show_edge_strip(hidden_side)
                self.hidden_to_edge = True
            self._toggle_startup()
            self._save_settings()
            win.destroy()

        tk.Button(btn_row, text="保存", command=apply_settings, bg="#2C7BE5", fg="white", relief="flat").pack(side="right")

        win.update_idletasks()
        req_w = max(360, body.winfo_reqwidth() + 24)
        req_h = max(320, body.winfo_reqheight() + 24)
        win.geometry(f"{req_w}x{req_h}")
        win.minsize(req_w, req_h)

    def _load_settings(self) -> None:
        data = load_settings(self.settings_file)
        self.refresh_ms = self._safe_int(data.get("refresh_ms"), REFRESH_MS_DEFAULT, 2000, 30000, "refresh_ms")
        self.snap_distance = self._safe_int(data.get("snap_distance"), SNAP_DISTANCE_DEFAULT, 8, 120, "snap_distance")
        self.auto_hide_delay_ms = self._safe_int(
            data.get("auto_hide_delay_ms"),
            AUTO_HIDE_DELAY_MS_DEFAULT,
            300,
            10000,
            "auto_hide_delay_ms",
        )
        self.edge_visible_width = self._safe_int(
            data.get("edge_visible_width"),
            EDGE_VISIBLE_WIDTH_DEFAULT,
            10,
            60,
            "edge_visible_width",
        )
        self.default_edge = data.get("default_edge", "left") if data.get("default_edge") in {"left", "right"} else "left"
        self.start_collapsed = bool(data.get("start_collapsed", False))
        self.strip_mode = data.get("strip_mode", "bar_small") if data.get("strip_mode") in STRIP_PRESETS else "bar_small"
        topmost = bool(data.get("always_on_top", True))
        self._apply_strip_preset()

        self.always_on_top_var.set(topmost)
        self.default_edge_var.set(self.default_edge)
        self.start_collapsed_var.set(self.start_collapsed)
        self.strip_mode_var.set(self.strip_mode)
        self.root.attributes("-topmost", topmost)

    def _safe_int(self, value: object, default: int, min_value: int, max_value: int, field_name: str) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            if value is not None:
                log_error(f"配置项 {field_name} 类型错误: {value!r}，已使用默认值 {default}")
            return default
        clamped = max(min_value, min(parsed, max_value))
        if clamped != parsed:
            log_error(f"配置项 {field_name} 超出范围: {parsed}，已修正为 {clamped}")
        return clamped

    def _save_settings(self) -> None:
        save_settings(
            self.settings_file,
            {
                "refresh_ms": self.refresh_ms,
                "snap_distance": self.snap_distance,
                "auto_hide_delay_ms": self.auto_hide_delay_ms,
                "edge_visible_width": self.edge_visible_width,
                "always_on_top": bool(self.always_on_top_var.get()),
                "default_edge": self.default_edge,
                "start_collapsed": bool(self.start_collapsed),
                "strip_mode": self.strip_mode,
            },
        )

    def _create_tray_image(self):
        if Image is None or ImageDraw is None:
            return None
        if self.app_icon_path and self.app_icon_path.exists():
            try:
                return Image.open(self.app_icon_path)
            except Exception as exc:
                log_error(f"托盘图标加载失败，回退默认图标: {exc!r}")
        img = Image.new("RGB", (64, 64), (18, 18, 18))
        draw = ImageDraw.Draw(img)
        draw.rectangle((8, 8, 56, 56), outline=(44, 123, 229), width=3)
        draw.ellipse((20, 20, 44, 44), fill=(32, 224, 111))
        return img

    def _detect_icon_path(self) -> Path | None:
        try:
            icons = sorted(self.entry_script.parent.glob("*.ico"))
            return icons[0] if icons else None
        except Exception as exc:
            log_error(f"扫描 ico 文件失败: {exc!r}")
            return None

    def _apply_window_icon(self, window: tk.Tk | tk.Toplevel) -> None:
        if self.app_icon_path is None:
            return
        try:
            window.iconbitmap(str(self.app_icon_path))
        except Exception as exc:
            log_error(f"设置窗口图标失败: {exc!r}")

    def _start_tray_icon(self) -> None:
        if not self.tray_supported:
            log_error("托盘功能不可用：缺少 pystray 或 Pillow 依赖。")
            return
        if self.tray_icon is not None:
            return
        image = self._create_tray_image()
        if image is None:
            return
        menu = pystray.Menu(
            pystray.MenuItem("显示界面", self._tray_show_window),
            pystray.MenuItem("退出", self._tray_quit_app),
        )
        self.tray_icon = pystray.Icon("NetworkStatusMonitor", image, "网络状态监测", menu)
        self.tray_thread = threading.Thread(target=self.tray_icon.run, daemon=True)
        self.tray_thread.start()

    def _stop_tray_icon(self) -> None:
        if self.tray_icon is not None:
            try:
                self.tray_icon.stop()
            except Exception as exc:
                log_error(f"托盘停止失败: {exc!r}")
            self.tray_icon = None

    def _tray_show_window(self, _icon=None, _item=None) -> None:
        self.root.after(0, self._show_window_from_tray)

    def _tray_quit_app(self, _icon=None, _item=None) -> None:
        self.root.after(0, self._quit_from_ui)

    def _show_window_from_tray(self) -> None:
        if self.destroyed:
            return
        self.root.deiconify()
        self.root.attributes("-topmost", self.always_on_top_var.get())
        self.root.lift()
        self.root.focus_force()

    def _hide_to_tray(self) -> None:
        self.root.withdraw()

    def _quit_from_ui(self) -> None:
        if messagebox.askokcancel("退出", "确认退出网络状态监测工具吗？"):
            self._on_close()

    def _startup_command(self) -> str:
        pythonw = Path(sys.executable).with_name("pythonw.exe")
        executable = str(pythonw if pythonw.exists() else Path(sys.executable))
        return startup_command(executable, str(self.entry_script))

    def _sync_startup_checkbox(self) -> None:
        self.startup_var.set(is_startup_enabled(STARTUP_REG_PATH, STARTUP_NAME, self._startup_command()))

    def _toggle_startup(self) -> None:
        enabled = self.startup_var.get()
        ok = set_startup_enabled(STARTUP_REG_PATH, STARTUP_NAME, self._startup_command(), enabled)
        if not ok:
            self.startup_var.set(False)

    def _on_close(self) -> None:
        if self.destroyed:
            return
        self.destroyed = True
        self._cancel_auto_hide()
        if self.hide_watch_job is not None:
            self.root.after_cancel(self.hide_watch_job)
            self.hide_watch_job = None
        self._save_settings()
        if self.anim_job is not None:
            self.root.after_cancel(self.anim_job)
            self.anim_job = None
        if self.refresh_timer_job is not None:
            self.root.after_cancel(self.refresh_timer_job)
            self.refresh_timer_job = None
        self._stop_tray_icon()
        self.root.destroy()
