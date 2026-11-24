"""Minimize/restore the visible gamescope window on the host X11 display."""

from __future__ import annotations

import os
import time
from typing import Optional

from Xlib import X, display, protocol


def host_display_name() -> str:
    return os.environ.get("DISPLAY", ":0")


def _walk_windows(window):
    stack = [window]
    while stack:
        current = stack.pop()
        yield current
        try:
            stack.extend(current.query_tree().children)
        except Exception:
            continue


def find_gamescope_window(
    timeout: float = 5.0,
    display_name: Optional[str] = None,
) -> Optional[int]:
    """Find the visible gamescope/SDL window on the host X display."""
    deadline = time.monotonic() + max(0.1, timeout)
    target = display_name or host_display_name()
    while True:
        try:
            d = display.Display(target)
        except Exception:
            d = None
        if d is not None:
            try:
                best = None
                for window in _walk_windows(d.screen().root):
                    try:
                        attrs = window.get_attributes()
                        if attrs.map_state != X.IsViewable:
                            continue
                        geom = window.get_geometry()
                        if geom.width < 400 or geom.height < 300:
                            continue
                        classes = " ".join(
                            c for c in (window.get_wm_class() or ()) if c
                        )
                        title = window.get_wm_name() or ""
                        text = f"{classes} {title}".lower()
                        if "gamescope" not in text and "sober" not in text:
                            continue
                        area = geom.width * geom.height
                        if best is None or area > best[0]:
                            best = (area, window.id)
                    except Exception:
                        continue
                if best is not None:
                    return int(best[1])
            finally:
                d.close()
        if time.monotonic() >= deadline:
            return None
        time.sleep(0.25)


def minimize(window_id: int, display_name: Optional[str] = None) -> bool:
    """Iconify a host window; KWin/X11 honors WM_CHANGE_STATE."""
    try:
        d = display.Display(display_name or host_display_name())
        root = d.screen().root
        window = d.create_resource_object("window", window_id)
        atom = d.intern_atom("WM_CHANGE_STATE")
        event = protocol.event.ClientMessage(
            window=window,
            client_type=atom,
            data=(32, [3, 0, 0, 0, 0]),  # IconicState
        )
        root.send_event(
            event,
            event_mask=X.SubstructureRedirectMask | X.SubstructureNotifyMask,
        )
        d.sync()
        d.close()
        return True
    except Exception:
        return False


def restore(window_id: int, display_name: Optional[str] = None) -> bool:
    """Activate and restore a minimized host window."""
    try:
        d = display.Display(display_name or host_display_name())
        root = d.screen().root
        window = d.create_resource_object("window", window_id)
        atom = d.intern_atom("_NET_ACTIVE_WINDOW")
        event = protocol.event.ClientMessage(
            window=window,
            client_type=atom,
            data=(32, [2, 0, 0, 0, 0]),  # source: pager
        )
        root.send_event(
            event,
            event_mask=X.SubstructureRedirectMask | X.SubstructureNotifyMask,
        )
        d.sync()
        d.close()
        return True
    except Exception:
        return False


def is_minimized(window_id: int, display_name: Optional[str] = None) -> bool:
    try:
        d = display.Display(display_name or host_display_name())
        window = d.create_resource_object("window", window_id)
        state_atom = d.intern_atom("_NET_WM_STATE")
        hidden_atom = d.intern_atom("_NET_WM_STATE_HIDDEN")
        prop = window.get_full_property(state_atom, X.AnyPropertyType)
        if prop is not None and hidden_atom in prop.value:
            d.close()
            return True
        wm_state = window.get_full_property(
            d.intern_atom("WM_STATE"), X.AnyPropertyType
        )
        minimized = bool(wm_state and wm_state.value and wm_state.value[0] == 3)
        d.close()
        return minimized
    except Exception:
        return False


def exists(window_id: int, display_name: Optional[str] = None) -> bool:
    try:
        d = display.Display(display_name or host_display_name())
        window = d.create_resource_object("window", window_id)
        window.get_attributes()
        d.close()
        return True
    except Exception:
        return False
