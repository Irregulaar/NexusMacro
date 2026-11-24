"""Launch Sober inside gamescope for Nexus Macro."""

from __future__ import annotations

import os
import re
import shutil
import signal
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable, Optional

from .backend import detect_display, wait_for_window
from .config import Config
from .hostwindow import (
    exists as host_window_exists,
    find_gamescope_window,
    is_minimized as host_window_minimized,
    minimize as minimize_host_window,
    restore as restore_host_window,
)
from .paths import data_dir, gamescope_vendor_bin

LogFn = Callable[[str, str], None]
StatusFn = Callable[[str], None]
ReadyFn = Callable[[dict], None]
ErrorFn = Callable[[str], None]


class LauncherError(RuntimeError):
    pass


class GamescopeLauncher:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.pid_file = data_dir() / "gamescope.pid"
        self.log_path = data_dir() / "gamescope.log"
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._process: Optional[subprocess.Popen] = None
        self._log_file = None
        self._lock = threading.RLock()
        self.host_window_id: Optional[int] = None

    # -- estado -------------------------------------------------------------

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def connected_display(self) -> Optional[str]:
        return detect_display(
            self.config.window_class,
            preferred=self.config.display,
        )

    def flatpak_running(self) -> bool:
        return self._sober_running()

    def status(self) -> dict:
        return {
            "headless": self.connected_display(),
            "flatpak": self._sober_running(),
        }

    @property
    def owns_process(self) -> bool:
        pid = self._read_pid()
        if not pid:
            return False
        try:
            os.kill(pid, 0)
        except Exception:
            return False
        return self._pid_is_gamescope(pid)

    @staticmethod
    def _pid_is_gamescope(pid: int) -> bool:
        try:
            cmdline = Path(f"/proc/{pid}/cmdline").read_bytes()
            return b"gamescope" in cmdline
        except Exception:
            return False

    def find_gamescope(self) -> Optional[Path]:
        configured = (self.config.gamescope_path or "").strip()
        if configured:
            path = Path(configured).expanduser()
            if path.is_file() and os.access(path, os.X_OK):
                return path
        system = shutil.which("gamescope")
        if system:
            return Path(system)
        bundled = gamescope_vendor_bin()
        if bundled.is_file() and os.access(bundled, os.X_OK):
            return bundled
        return None

    def _environment(self, gamescope: Path) -> dict[str, str]:
        env = os.environ.copy()
        # The local gamescope package ships its own libraries.
        if "vendor" in gamescope.parts:
            usr = gamescope.parent.parent  # .../vendor/gamescope/usr
            lib = usr / "lib"
            bin_dir = usr / "bin"
            env["LD_LIBRARY_PATH"] = str(lib) + (
                ":" + env["LD_LIBRARY_PATH"] if env.get("LD_LIBRARY_PATH") else ""
            )
            env["PATH"] = str(bin_dir) + ":" + env.get("PATH", "")
        if self.config.gamescope_backend == "sdl":
            # Force an X11 host window so Nexus Macro can minimize it via X11.
            env["SDL_VIDEODRIVER"] = "x11"
        return env

    def _command(self, gamescope: Path) -> list[str]:
        cfg = self.config
        command = [
            str(gamescope),
            "--backend",
            cfg.gamescope_backend,
            "-W",
            str(cfg.window_width),
            "-H",
            str(cfg.window_height),
            "-w",
            str(cfg.window_width),
            "-h",
            str(cfg.window_height),
            "-r",
            str(cfg.gamescope_fps),
        ]
        if cfg.gamescope_grab_cursor:
            command.append("--force-grab-cursor")
        command.extend([
            "--",
            "env",
            "-u",
            "LD_LIBRARY_PATH",
            "-u",
            "SDL_VIDEODRIVER",
            "flatpak",
            "run",
            "org.vinegarhq.Sober",
        ])
        uri = cfg.game_uri()
        if uri:
            command.append(uri)
        return command

    # -- lanzar -------------------------------------------------------------

    def start_async(
        self,
        on_log: LogFn,
        on_status: StatusFn,
        on_ready: ReadyFn,
        on_error: ErrorFn,
        kill_existing: bool = True,
    ) -> None:
        with self._lock:
            if self.running:
                on_log("gamescope is already starting.", "warning")
                return
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._start_worker,
                args=(on_log, on_status, on_ready, on_error, kill_existing),
                daemon=True,
                name="gamescope-launcher",
            )
            self._thread.start()

    def _start_worker(
        self,
        on_log: LogFn,
        on_status: StatusFn,
        on_ready: ReadyFn,
        on_error: ErrorFn,
        kill_existing: bool,
    ) -> None:
        try:
            existing = self.connected_display()
            if existing:
                host_window = None
                if self.config.gamescope_backend == "sdl":
                    host_window = find_gamescope_window(timeout=1.0)
                self.host_window_id = host_window
                on_status(f"Connected to {existing}")
                on_ready(
                    {
                        "display": existing,
                        "pid": self._read_pid(),
                        "log": str(self.log_path),
                        "external": not self.owns_process,
                        "host_window": host_window,
                    }
                )
                return

            gamescope = self.find_gamescope()
            if gamescope is None:
                raise LauncherError(
                    "I couldn't find gamescope. Install it with "
                    "'sudo pacman -S --needed gamescope' or use the bundled "
                    "copy in vendor/gamescope."
                )

            if not shutil.which("flatpak"):
                raise LauncherError("I couldn't find flatpak in PATH.")
            info = subprocess.run(
                ["flatpak", "info", "org.vinegarhq.Sober"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            if info.returncode != 0:
                raise LauncherError(
                    "Sober is not installed as a Flatpak (org.vinegarhq.Sober)."
                )

            if self._sober_running():
                if not kill_existing:
                    raise LauncherError(
                        "Sober is already running. Close it or let Nexus Macro "
                        "close it before launching Nexus Macro's gamescope instance."
                    )
                on_log("Closing the current Sober instance...", "warning")
                subprocess.run(
                    ["flatpak", "kill", "org.vinegarhq.Sober"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
                # Wait until the old Sober instance has fully released its
                # single-instance lock before starting a new one.
                for _ in range(40):
                    if not self._sober_running():
                        break
                    time.sleep(0.25)
                time.sleep(1.5)

            on_status("Launching gamescope...")
            on_log(
                f"gamescope: {gamescope} · {self.config.window_width}x"
                f"{self.config.window_height} @ {self.config.gamescope_fps}fps",
                "info",
            )
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            self._log_file = self.log_path.open("w", encoding="utf-8", errors="replace")
            env = self._environment(gamescope)
            self._process = subprocess.Popen(
                self._command(gamescope),
                stdin=subprocess.DEVNULL,
                stdout=self._log_file,
                stderr=subprocess.STDOUT,
                env=env,
                start_new_session=True,
                cwd=str(self.log_path.parent),
            )
            self._write_pid(self._process.pid)

            display = self._wait_for_display(on_log, on_status)
            if display is None:
                if self._stop_event.is_set():
                    return
                raise LauncherError(self._failure_message())

            on_status(f"Xwayland {display}; waiting for Sober...")
            if not wait_for_window(
                display,
                self.config.window_class,
                timeout=150.0,
                interval=0.25,
            ):
                if self._stop_event.is_set():
                    return
                raise LauncherError(
                    "Sober did not open its window within 150 seconds. "
                    f"Check {self.log_path}"
                )

            # Give Roblox a moment to paint its UI.
            time.sleep(2.0)
            host_window = None
            if self.config.gamescope_backend == "sdl":
                host_window = find_gamescope_window(timeout=6.0)
                self.host_window_id = host_window
            on_status(f"Sober ready on {display}")
            on_log(f"Sober ready on {display}.", "success")
            on_ready(
                {
                    "display": display,
                    "pid": self._process.pid,
                    "log": str(self.log_path),
                    "external": False,
                    "host_window": host_window,
                }
            )
        except Exception as exc:
            on_error(str(exc))
            self._cleanup_after_error()
        finally:
            if self._log_file is not None:
                try:
                    self._log_file.flush()
                except Exception:
                    pass

    def _wait_for_display(
        self,
        on_log: LogFn,
        on_status: StatusFn,
    ) -> Optional[str]:
        pattern = re.compile(r"Starting Xwayland on (:\d+)")
        deadline = time.monotonic() + 40.0
        last_size = 0
        while time.monotonic() < deadline:
            if self._stop_event.is_set():
                return None
            if self._process is not None and self._process.poll() is not None:
                return None
            try:
                text = self.log_path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                text = ""
            if len(text) > last_size:
                last_size = len(text)
                for line in text.splitlines()[-10:]:
                    if "Error" in line or "error" in line or "warn" in line.lower():
                        on_log(line.strip(), "warning")
            match = pattern.search(text)
            if match:
                return match.group(1)
            time.sleep(0.25)
        return None

    def _failure_message(self) -> str:
        tail = self.tail(25)
        return (
            "gamescope did not create Sober's display. "
            f"Check {self.log_path}\n\n{tail}"
        )

    # -- parar --------------------------------------------------------------

    def _ensure_host_window(self) -> Optional[int]:
        if self.host_window_id and host_window_exists(self.host_window_id):
            return self.host_window_id
        self.host_window_id = find_gamescope_window(timeout=1.0)
        return self.host_window_id

    def has_host_window(self) -> bool:
        return bool(
            self.host_window_id and host_window_exists(self.host_window_id)
        )

    def host_window_available(self) -> bool:
        return self._ensure_host_window() is not None

    def host_minimized(self) -> bool:
        window = self._ensure_host_window()
        return bool(window and host_window_minimized(window))

    def minimize_host(self) -> bool:
        window = self._ensure_host_window()
        return bool(window and minimize_host_window(window))

    def restore_host(self) -> bool:
        window = self._ensure_host_window()
        return bool(window and restore_host_window(window))

    def stop(self) -> None:
        self._stop_event.set()
        pid = self._read_pid()
        if (
            (not pid or not self._pid_is_gamescope(pid))
            and self._process is not None
            and self._process.poll() is None
        ):
            pid = self._process.pid
        if pid and self._pid_is_gamescope(pid):
            try:
                os.killpg(os.getpgid(pid), signal.SIGTERM)
            except Exception:
                try:
                    os.kill(pid, signal.SIGTERM)
                except Exception:
                    pass
            for _ in range(25):
                try:
                    os.kill(pid, 0)
                except Exception:
                    break
                time.sleep(0.2)
            try:
                os.killpg(os.getpgid(pid), signal.SIGKILL)
            except Exception:
                pass
            subprocess.run(
                ["flatpak", "kill", "org.vinegarhq.Sober"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        self._remove_pid()

        with self._lock:
            if self._process is not None:
                try:
                    self._process.terminate()
                except Exception:
                    pass
                self._process = None
            if self._log_file is not None:
                try:
                    self._log_file.close()
                except Exception:
                    pass
                self._log_file = None
            self.host_window_id = None

    def _cleanup_after_error(self) -> None:
        self._stop_event.set()
        with self._lock:
            if self._process is not None:
                try:
                    if self._process.poll() is None:
                        os.killpg(os.getpgid(self._process.pid), signal.SIGTERM)
                except Exception:
                    pass
                self._process = None
            if self._log_file is not None:
                try:
                    self._log_file.close()
                except Exception:
                    pass
                self._log_file = None
        self._remove_pid()

    # -- utilidades ---------------------------------------------------------

    def _sober_running(self) -> bool:
        try:
            result = subprocess.run(
                ["flatpak", "ps", "--columns=application"],
                capture_output=True,
                text=True,
                check=False,
                timeout=5,
            )
            return "org.vinegarhq.Sober" in result.stdout.splitlines()
        except Exception:
            return False

    def _write_pid(self, pid: int) -> None:
        try:
            self.pid_file.write_text(f"{pid}\n", encoding="utf-8")
        except Exception:
            pass

    def _read_pid(self) -> Optional[int]:
        try:
            text = self.pid_file.read_text(encoding="utf-8").strip()
            return int(text) if text else None
        except Exception:
            return None

    def _remove_pid(self) -> None:
        try:
            self.pid_file.unlink(missing_ok=True)
        except Exception:
            pass

    def tail(self, lines: int = 30) -> str:
        try:
            content = self.log_path.read_text(encoding="utf-8", errors="replace")
            return "\n".join(content.splitlines()[-lines:])
        except Exception:
            return ""
