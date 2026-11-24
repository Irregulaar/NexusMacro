"""X11 backend for controlling Sober inside gamescope headless."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Optional

import numpy as np
from Xlib import X, XK, display as xdisplay
from Xlib.ext import xtest


class BackendError(RuntimeError):
    pass


def _walk_windows(window):
    stack = [window]
    while stack:
        current = stack.pop()
        yield current
        try:
            stack.extend(current.query_tree().children)
        except Exception:
            continue


def live_xwayland_displays() -> set[int]:
    """Display numbers of live Xwayland processes (avoids stale sockets)."""
    result: set[int] = set()
    proc = Path("/proc")
    try:
        entries = list(proc.iterdir())
    except Exception:
        return result
    for entry in entries:
        if not entry.name.isdigit():
            continue
        try:
            raw = (entry / "cmdline").read_bytes()
        except Exception:
            continue
        if b"Xwayland" not in raw:
            continue
        for token in raw.replace(b"\x00", b" ").decode("utf-8", "replace").split():
            if token.startswith(":") and token[1:].isdigit():
                result.add(int(token[1:]))
    return result


def _find_window(d, wm_class: Optional[str]):
    best = None
    for window in _walk_windows(d.screen().root):
        try:
            attrs = window.get_attributes()
            if attrs.map_state != X.IsViewable:
                continue
            geom = window.get_geometry()
            if geom.width < 40 or geom.height < 40:
                continue
            if wm_class:
                classes = window.get_wm_class() or ()
                if not any(wm_class.lower() in (c or "").lower() for c in classes):
                    continue
            area = geom.width * geom.height
            if best is None or area > best[0]:
                best = (area, window, geom)
        except Exception:
            continue
    return best


def detect_display(
    wm_class: str = "org.vinegarhq.Sober",
    max_display: int = 30,
    preferred: str = "",
) -> Optional[str]:
    """Busca el Xwayland privado de gamescope. Nunca usa :0 salvo preferred."""
    if preferred and preferred not in (":0", "0"):
        number_text = preferred.lstrip(":")
        if number_text.isdigit() and int(number_text) not in live_xwayland_displays():
            return None
        try:
            d = xdisplay.Display(preferred)
            try:
                if _find_window(d, wm_class) is not None:
                    return preferred
            finally:
                d.close()
        except Exception:
            pass

    live = live_xwayland_displays()
    for number in range(1, max_display + 1):
        if number not in live:
            continue
        if not Path(f"/tmp/.X11-unix/X{number}").exists():
            continue
        name = f":{number}"
        try:
            d = xdisplay.Display(name)
            try:
                if _find_window(d, wm_class) is not None:
                    return name
            finally:
                d.close()
        except Exception:
            continue
    return None


def wait_for_window(
    display_name: str,
    wm_class: str = "org.vinegarhq.Sober",
    timeout: float = 120.0,
    interval: float = 0.25,
) -> bool:
    deadline = time.monotonic() + timeout
    while True:
        try:
            d = xdisplay.Display(display_name)
            try:
                found = _find_window(d, wm_class)
            finally:
                d.close()
            if found is not None:
                return True
        except Exception:
            pass
        if time.monotonic() >= deadline:
            return False
        time.sleep(interval)


def list_displays(wm_class: str = "org.vinegarhq.Sober") -> list[dict]:
    result = []
    live = live_xwayland_displays()
    for number in range(1, 31):
        if number not in live:
            continue
        if not Path(f"/tmp/.X11-unix/X{number}").exists():
            continue
        name = f":{number}"
        try:
            d = xdisplay.Display(name)
            try:
                found = _find_window(d, wm_class)
                if found is None:
                    continue
                _, window, geom = found
                result.append(
                    {
                        "display": name,
                        "id": hex(window.id),
                        "title": window.get_wm_name() or "",
                        "class": window.get_wm_class() or (),
                        "width": geom.width,
                        "height": geom.height,
                    }
                )
            finally:
                d.close()
        except Exception:
            continue
    return result


class X11Backend:
    """Capture and input on an X11 window (Sober inside gamescope Xwayland)."""

    def __init__(
        self,
        display_name: Optional[str] = None,
        wm_class: str = "org.vinegarhq.Sober",
        park_after_click: bool = True,
    ) -> None:
        self.requested_display = display_name or ""
        self.wm_class = wm_class
        self.park_after_click = park_after_click
        self.display_name = ""
        self.display = None
        self.root = None
        self.window = None
        self.geom = (0, 0, 0, 0)
        self._cursor: Optional[tuple[int, int]] = None
        self._lock = threading.RLock()

    # -- connection ---------------------------------------------------------

    def connect(self) -> None:
        with self._lock:
            if self.display is not None:
                return

            name = ""
            if self.requested_display:
                number_text = self.requested_display.lstrip(":")
                if (
                    number_text.isdigit()
                    and int(number_text) != 0
                    and int(number_text) not in live_xwayland_displays()
                ):
                    raise BackendError(
                        f"Display {self.requested_display} has no live "
                        "Xwayland. Use «auto» or launch Sober headless."
                    )
                try:
                    d = xdisplay.Display(self.requested_display)
                    d.close()
                    name = self.requested_display
                except Exception as exc:
                    raise BackendError(
                        f"Couldn't open display {self.requested_display}: {exc}"
                    ) from exc
            else:
                found = detect_display(self.wm_class)
                if not found:
                    raise BackendError(
                        "I can't find the Sober window on any private Xwayland. "
                        "Launch Sober from Nexus Macro or check the display."
                    )
                name = found

            try:
                d = xdisplay.Display(name)
            except Exception as exc:
                raise BackendError(f"Couldn't connect to {name}: {exc}") from exc

            found = _find_window(d, self.wm_class)
            if found is None:
                d.close()
                raise BackendError(
                    f"Display {name} has no window with class "
                    f"'{self.wm_class}'."
                )

            _, window, _ = found
            self.display = d
            self.display_name = name
            self.root = d.screen().root
            self.window = window
            self._refresh_geometry()
            try:
                pointer = self.root.query_pointer()
                self._cursor = (
                    pointer.root_x - self.geom[0],
                    pointer.root_y - self.geom[1],
                )
            except Exception:
                self._cursor = None
            self.focus()

    def close(self) -> None:
        with self._lock:
            if self.display is not None:
                try:
                    self.display.close()
                except Exception:
                    pass
            self.display = None
            self.root = None
            self.window = None

    def ping(self) -> bool:
        with self._lock:
            if self.window is None:
                return False
            try:
                attrs = self.window.get_attributes()
                return attrs.map_state == X.IsViewable
            except Exception:
                return False

    # -- geometry -----------------------------------------------------------

    def _refresh_geometry(self) -> None:
        if self.window is None or self.root is None:
            raise BackendError("Backend is not connected.")
        geom = self.window.get_geometry()
        translated = self.window.translate_coords(self.root, 0, 0)
        self.geom = (translated.x, translated.y, geom.width, geom.height)

    @property
    def width(self) -> int:
        return self.geom[2]

    @property
    def height(self) -> int:
        return self.geom[3]

    @property
    def size(self) -> tuple[int, int]:
        return self.geom[2], self.geom[3]

    @property
    def window_title(self) -> str:
        if self.window is None:
            return ""
        try:
            return self.window.get_wm_name() or ""
        except Exception:
            return ""

    def capture(self) -> np.ndarray:
        with self._lock:
            if self.window is None:
                raise BackendError("Backend is not connected.")
            self._refresh_geometry()
            _, _, width, height = self.geom
            if width <= 0 or height <= 0:
                raise BackendError("The game window has zero size.")
            try:
                raw = self.window.get_image(
                    0, 0, width, height, X.ZPixmap, 0xFFFFFFFF
                )
            except Exception as exc:
                raise BackendError(f"Couldn't capture the window: {exc}") from exc

            data = raw.data
            stride = len(data) // height
            if stride % 4 == 0:
                pixels = np.frombuffer(data, dtype=np.uint8).reshape(
                    (height, stride // 4, 4)
                )[:, :width, :3]
            elif stride % 3 == 0:
                pixels = np.frombuffer(data, dtype=np.uint8).reshape(
                    (height, stride // 3, 3)
                )[:, :width, :3]
            else:
                raise BackendError(
                    f"Unsupported pixel format (stride={stride}, width={width})."
                )
            return np.ascontiguousarray(pixels.copy())

    # -- mouse --------------------------------------------------------------

    def focus(self) -> None:
        with self._lock:
            if self.window is None:
                return
            try:
                self.window.set_input_focus(X.RevertToParent, X.CurrentTime)
                self.display.sync()
            except Exception:
                pass

    def move(self, x: int, y: int) -> None:
        with self._lock:
            if self.root is None:
                raise BackendError("Backend is not connected.")
            width, height = self.width, self.height
            x = max(0, min(width - 1, int(x)))
            y = max(0, min(height - 1, int(y)))
            self.root.warp_pointer(self.geom[0] + x, self.geom[1] + y)
            self.display.sync()
            self._cursor = (x, y)

    def smooth_move(self, x: int, y: int, duration: float = 0.10) -> None:
        """Glide the pointer to a point instead of teleporting."""
        with self._lock:
            if self.root is None:
                raise BackendError("Backend is not connected.")
            width, height = self.width, self.height
            target_x = max(0, min(width - 1, int(x)))
            target_y = max(0, min(height - 1, int(y)))
            if self._cursor is None:
                try:
                    pointer = self.root.query_pointer()
                    start_x = pointer.root_x - self.geom[0]
                    start_y = pointer.root_y - self.geom[1]
                except Exception:
                    start_x, start_y = target_x, target_y
            else:
                start_x, start_y = self._cursor
            if abs(target_x - start_x) + abs(target_y - start_y) <= 2:
                self.move(target_x, target_y)
                return
            steps = max(4, min(12, int(max(0.04, duration) / 0.02)))
            step_delay = max(0.004, duration / steps)
            for index in range(1, steps + 1):
                t = index / steps
                current_x = int(round(start_x + (target_x - start_x) * t))
                current_y = int(round(start_y + (target_y - start_y) * t))
                self.root.warp_pointer(
                    self.geom[0] + current_x, self.geom[1] + current_y
                )
                self.display.sync()
                time.sleep(step_delay)
            self._cursor = (target_x, target_y)

    def click(self, x: int, y: int, button: int = 1, park: Optional[bool] = None) -> None:
        with self._lock:
            self.smooth_move(x, y)
            # Final absolute warp: guarantees the exact target even if the
            # intermediate motion events were coalesced by the game.
            self.move(x, y)
            time.sleep(0.06)
            xtest.fake_input(self.display, X.ButtonPress, button)
            self.display.sync()
            time.sleep(0.05)
            xtest.fake_input(self.display, X.ButtonRelease, button)
            self.display.sync()
            time.sleep(0.03)
            do_park = self.park_after_click if park is None else park
            if do_park:
                self.park_cursor()

    def click_series(
        self,
        x: int,
        y: int,
        count: int,
        delay: float = 0.04,
        button: int = 1,
    ) -> None:
        """Click the same point several times without re-warping the pointer."""
        with self._lock:
            self.smooth_move(x, y)
            self.move(x, y)
            time.sleep(0.06)
            for index in range(max(1, int(count))):
                xtest.fake_input(self.display, X.ButtonPress, button)
                self.display.sync()
                time.sleep(0.02)
                xtest.fake_input(self.display, X.ButtonRelease, button)
                self.display.sync()
                if index < count - 1:
                    time.sleep(max(0.01, delay))
            if self.park_after_click:
                self.park_cursor()

    def mouse_down(self, button: int = 1) -> None:
        with self._lock:
            xtest.fake_input(self.display, X.ButtonPress, button)
            self.display.sync()

    def mouse_up(self, button: int = 1) -> None:
        with self._lock:
            xtest.fake_input(self.display, X.ButtonRelease, button)
            self.display.sync()

    def park_cursor(self) -> None:
        with self._lock:
            width, height = self.width, self.height
            parked_x = max(0, width - 2)
            parked_y = max(0, height - 2)
            self.root.warp_pointer(
                self.geom[0] + parked_x,
                self.geom[1] + parked_y,
            )
            self.display.sync()
            self._cursor = (parked_x, parked_y)

    def scroll(self, clicks: int, x: Optional[int] = None, y: Optional[int] = None) -> None:
        with self._lock:
            if x is not None and y is not None:
                self.smooth_move(x, y, duration=0.10)
            button = 4 if clicks > 0 else 5
            for _ in range(abs(int(clicks))):
                xtest.fake_input(self.display, X.ButtonPress, button)
                self.display.sync()
                time.sleep(0.02)
                xtest.fake_input(self.display, X.ButtonRelease, button)
                self.display.sync()
                time.sleep(0.02)

    def drag(
        self,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        duration: float = 0.5,
        steps: int = 12,
    ) -> None:
        with self._lock:
            self.move(x1, y1)
            self.mouse_down()
            try:
                for index in range(1, max(1, steps) + 1):
                    t = index / steps
                    self.move(
                        int(round(x1 + (x2 - x1) * t)),
                        int(round(y1 + (y2 - y1) * t)),
                    )
                    time.sleep(max(0.0, duration / steps))
            finally:
                self.mouse_up()
            self.park_cursor()

    # -- keyboard -----------------------------------------------------------

    KEY_ALIASES = {
        "enter": "Return",
        "return": "Return",
        "esc": "Escape",
        "escape": "Escape",
        "space": "space",
        "tab": "Tab",
        "backspace": "BackSpace",
        "up": "Up",
        "down": "Down",
        "left": "Left",
        "right": "Right",
        "pageup": "Prior",
        "pagedown": "Next",
        "home": "Home",
        "end": "End",
        "delete": "Delete",
    }

    def key(self, name: str) -> None:
        with self._lock:
            self.focus()
            alias = self.KEY_ALIASES.get(name.lower(), name)
            keysym = XK.string_to_keysym(alias)
            if not keysym and len(alias) == 1:
                keysym = ord(alias)
            if not keysym:
                raise BackendError(f"Unsupported key: {name}")
            self._press_keysym(keysym)
            self.display.sync()

    def type_text(self, text: str) -> None:
        """Type ASCII text into the window (search, chat, etc.)."""
        with self._lock:
            self.focus()
            for char in text:
                if char == "\n":
                    self._press_keysym(self._keysym("Return"))
                elif char == "\t":
                    self._press_keysym(self._keysym("Tab"))
                elif 0x20 <= ord(char) <= 0x7E:
                    self._press_keysym(ord(char))
                else:
                    raise BackendError(
                        "Manual control only supports ASCII characters."
                    )
                time.sleep(0.015)
            self.display.sync()

    def _keysym(self, name: str) -> int:
        alias = self.KEY_ALIASES.get(name.lower(), name)
        keysym = XK.string_to_keysym(alias)
        if not keysym and len(alias) == 1:
            keysym = ord(alias)
        if not keysym:
            raise BackendError(f"Tecla no soportada: {name}")
        return keysym

    def _press_keysym(self, keysym: int) -> None:
        keycode = self.display.keysym_to_keycode(keysym)
        if not keycode:
            raise BackendError(f"No key exists for keysym {keysym:#x}.")
        shift = False
        for level in (0, 1):
            if self.display.keycode_to_keysym(keycode, level) == keysym:
                shift = level == 1
                break
        shift_code = self.display.keysym_to_keycode(XK.string_to_keysym("Shift_L"))
        if shift and shift_code:
            xtest.fake_input(self.display, X.KeyPress, shift_code)
        xtest.fake_input(self.display, X.KeyPress, keycode)
        xtest.fake_input(self.display, X.KeyRelease, keycode)
        if shift and shift_code:
            xtest.fake_input(self.display, X.KeyRelease, shift_code)
        self.display.sync()
