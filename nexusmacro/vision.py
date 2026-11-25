"""Nexus Macro vision: masked template matching with NCC verification."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional

import cv2
import numpy as np

from .config import Config


class TemplateError(RuntimeError):
    pass


@dataclass(frozen=True)
class TemplateSpec:
    key: str
    filename: str
    title: str
    description: str
    border_ignore: int = 6
    dark_threshold: int = 55
    ignore_top: int = 0
    ignore_right: float = 0.0
    max_results: int = 1
    threshold_boost: float = 0.0
    invert_mask: bool = False


TEMPLATE_SPECS: tuple[TemplateSpec, ...] = (
    TemplateSpec(
        "battle",
        "battle1.png",
        "Battle",
        "Battle button center, without the rounded border.",
        border_ignore=1,
        dark_threshold=45,
    ),
    TemplateSpec(
        "battle2",
        "battle2.png",
        "Continue",
        "Continue button center, without the rounded border.",
        border_ignore=1,
        dark_threshold=45,
    ),
    TemplateSpec(
        "yescontinue",
        "yescontinue.png",
        "Yes, continue",
        "Green confirmation button shown when a battle is already running.",
        border_ignore=1,
        dark_threshold=45,
    ),
    TemplateSpec(
        "spawner1",
        "spawners1.png",
        "Spawner",
        "Spawner button center, without the rounded border.",
        border_ignore=1,
        dark_threshold=45,
    ),
    TemplateSpec(
        "spawner2",
        "spawners2.png",
        "Spawner (compact)",
        "Compact spawner button center, without the rounded border.",
        border_ignore=1,
        dark_threshold=45,
    ),
    TemplateSpec(
        "spawner3",
        "spawnerbutton3.png",
        "Spawner (full, timer)",
        "Full spawner button with timer. Used as a fallback.",
        border_ignore=6,
        ignore_top=32,
    ),
    TemplateSpec(
        "build",
        "build1.png",
        "Build",
        "Build button center, without the rounded border.",
        border_ignore=1,
        dark_threshold=45,
    ),
    TemplateSpec(
        "fuseall",
        "fuseallbutton.png",
        "Fuse all",
        "Fuse-all button inside the build menu.",
        border_ignore=1,
        dark_threshold=45,
    ),
    TemplateSpec(
        "placebest",
        "placebestbutton.png",
        "Place best",
        "Place-best button inside the build menu.",
        border_ignore=1,
        dark_threshold=45,
    ),
    TemplateSpec(
        "stop",
        "stopbutton.png",
        "Stop",
        "Build button while the build menu is open (Stop).",
        border_ignore=1,
        dark_threshold=45,
    ),
    TemplateSpec(
        "discard",
        "discardbutton.png",
        "Discard",
        "Discard the saved battle and start a new one.",
        border_ignore=1,
        dark_threshold=45,
    ),
    TemplateSpec(
        "play",
        "playbutton.png",
        "Play",
        "Play button on the Roblox loading screen.",
        border_ignore=1,
        dark_threshold=45,
    ),
    TemplateSpec(
        "tabimage",
        "tabimage.png",
        "Leaderboard header",
        "Visible when the leaderboard is open; press Tab only then.",
        border_ignore=2,
        dark_threshold=45,
    ),
    TemplateSpec(
        "reconnectbutton",
        "reconnectbutton.png",
        "Reconnect",
        "Roblox reconnect button: never click it; restart Sober instead.",
        border_ignore=2,
        dark_threshold=120,
        invert_mask=True,
    ),
    TemplateSpec(
        "settingsbutton",
        "settingsbutton.png",
        "Settings",
        "Roblox in-game settings gear.",
        border_ignore=1,
        dark_threshold=45,
    ),
    TemplateSpec(
        "classicforfeitsetting",
        "classicforfeitsetting.png",
        "Classic Forfeit",
        "Classic Forfeit setting row; enable it once.",
        border_ignore=1,
        dark_threshold=45,
    ),
    TemplateSpec(
        "forfeit",
        "forfeitbutton.png",
        "Forfeit",
        "Forfeit button shown during a battle.",
        border_ignore=1,
        dark_threshold=45,
    ),
    TemplateSpec(
        "confirm",
        "confirmbutton.png",
        "Confirm",
        "Confirmation button in the forfeit modal.",
        border_ignore=1,
        dark_threshold=45,
    ),
    TemplateSpec(
        "buy",
        "buybutton.png",
        "Buy",
        "Green buy button. The price is ignored.",
        border_ignore=4,
        ignore_right=0.45,
        max_results=20,
    ),
    TemplateSpec(
        "scroll",
        "scrollspawner.png",
        "Spawner scrollbar",
        "Vertical bar used to scroll the shop list.",
        border_ignore=2,
        max_results=3,
        threshold_boost=0.02,
    ),
    TemplateSpec(
        "close",
        "closebutton.png",
        "Close",
        "X button used to close the shop.",
        border_ignore=3,
        threshold_boost=0.02,
    ),
)

SPECS_BY_KEY = {spec.key: spec for spec in TEMPLATE_SPECS}

# Restrict searches to the part of the HUD where each control can appear.
# Fractions are (x, y, width, height). Limiting the area is what makes the
# matcher fast enough (~4-10x) for a 600 ms tick budget.
DEFAULT_REGIONS: dict[str, tuple[float, float, float, float]] = {
    "build": (0.0, 0.45, 1.0, 0.55),
    "battle": (0.0, 0.45, 1.0, 0.55),
    "battle2": (0.0, 0.40, 1.0, 0.60),
    "yescontinue": (0.10, 0.25, 0.80, 0.65),
    "stop": (0.0, 0.40, 1.0, 0.60),
    "forfeit": (0.45, 0.45, 0.55, 0.55),
    "play": (0.10, 0.35, 0.80, 0.60),
    "tabimage": (0.55, 0.0, 0.45, 0.35),
    "settingsbutton": (0.08, 0.0, 0.35, 0.14),
    "discard": (0.05, 0.20, 0.90, 0.70),
    "confirm": (0.10, 0.25, 0.80, 0.65),
    "fuseall": (0.0, 0.15, 0.60, 0.85),
    "placebest": (0.0, 0.15, 0.60, 0.85),
    # The spawner buttons live in the lower HUD / map band. This matches the
    # old engine comment and cuts the search area by more than half.
    "spawner1": (0.0, 0.35, 1.0, 0.65),
    "spawner2": (0.0, 0.35, 1.0, 0.65),
    "spawner3": (0.0, 0.35, 1.0, 0.65),
}


def default_region(
    key: str, frame_w: int, frame_h: int
) -> Optional[tuple[int, int, int, int]]:
    area = DEFAULT_REGIONS.get(key)
    if area is None:
        return None
    x, y, w, h = area
    return (
        int(frame_w * x),
        int(frame_h * y),
        int(frame_w * w),
        int(frame_h * h),
    )


@dataclass(frozen=True)
class TemplateData:
    spec: TemplateSpec
    path: Path
    bgr: np.ndarray
    gray: np.ndarray
    mask: np.ndarray
    scale: float

    @property
    def width(self) -> int:
        return int(self.bgr.shape[1])

    @property
    def height(self) -> int:
        return int(self.bgr.shape[0])


@dataclass(frozen=True)
class Match:
    key: str
    x: int
    y: int
    w: int
    h: int
    score: float

    @property
    def cx(self) -> int:
        return self.x + self.w // 2

    @property
    def cy(self) -> int:
        return self.y + self.h // 2

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "x": self.x,
            "y": self.y,
            "w": self.w,
            "h": self.h,
            "cx": self.cx,
            "cy": self.cy,
            "score": self.score,
        }


MATCH_COLORS = {
    "battle": (80, 120, 255),
    "spawner1": (60, 180, 255),
    "spawner2": (60, 220, 200),
    "buy": (90, 230, 120),
    "scroll": (220, 210, 60),
    "close": (120, 120, 255),
}


def _prepare_mask(
    bgr: np.ndarray,
    alpha: Optional[np.ndarray],
    spec: TemplateSpec,
    config: Config,
) -> np.ndarray:
    height, width = bgr.shape[:2]
    border = max(0, int(spec.border_ignore))
    mask = np.zeros((height, width), dtype=np.uint8)
    if border * 2 >= min(width, height):
        border = 0
    mask[border : height - border, border : width - border] = 255

    ignore_top = spec.ignore_top
    if spec.key == "spawner3":
        ignore_top = int(config.ignore_spawner_timer)
    if ignore_top:
        mask[: min(height, int(ignore_top)), :] = 0

    ignore_right = spec.ignore_right
    if spec.key == "buy":
        ignore_right = config.ignore_buy_price
    if ignore_right:
        cutoff = int(width * (1.0 - float(ignore_right)))
        mask[:, max(0, cutoff) :] = 0

    # The dark border and background add nothing; keep button, text and icons.
    bright = bgr.max(axis=2) > spec.dark_threshold
    if spec.invert_mask:
        # White button with dark text: keep the glyphs, not the background.
        bright = ~bright
    mask = np.where(bright, mask, 0).astype(np.uint8)

    if alpha is not None:
        mask = np.where(alpha > 8, mask, 0).astype(np.uint8)

    if int((mask > 0).sum()) < 30:
        raise TemplateError(
            f"The mask for {spec.filename} is empty. "
            "Try another crop or adjust the settings."
        )
    return mask


class Matcher:
    """Carga templates y busca coincidencias verificadas con NCC."""

    def __init__(
        self,
        base_dir: Path,
        user_dir: Path,
        config: Config,
    ) -> None:
        self.base_dir = Path(base_dir)
        self.user_dir = Path(user_dir)
        self.config = config
        self._cache: dict[tuple[str, float, int, float], TemplateData] = {}
        self._paths: dict[str, Path] = {}

    # -- rutas --------------------------------------------------------------

    def template_path(self, key: str) -> Path:
        if key in self._paths:
            return self._paths[key]
        spec = SPECS_BY_KEY[key]
        user = self.user_dir / spec.filename
        path = user if user.exists() else self.base_dir / spec.filename
        self._paths[key] = path
        return path

    def refresh_paths(self) -> None:
        self._paths.clear()
        self._cache.clear()

    def reload(self) -> None:
        self.refresh_paths()

    def template_status(self) -> list[dict[str, Any]]:
        result = []
        for spec in TEMPLATE_SPECS:
            path = self.template_path(spec.key)
            result.append(
                {
                    "key": spec.key,
                    "filename": spec.filename,
                    "title": spec.title,
                    "description": spec.description,
                    "path": path,
                    "exists": path.exists(),
                    "source": "user" if path.parent == self.user_dir else "bundled",
                }
            )
        return result

    def save_user_template(self, key: str, source: Path) -> Path:
        spec = SPECS_BY_KEY[key]
        destination = self.user_dir / spec.filename
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        self.reload()
        return destination

    # -- carga --------------------------------------------------------------

    def _load(self, key: str, scale: Optional[float] = None) -> TemplateData:
        spec = SPECS_BY_KEY[key]
        if scale is None:
            scale = self.config.scale
        cache_key = (
            key,
            round(float(scale), 4),
            int(self.config.ignore_spawner_timer),
            float(self.config.ignore_buy_price),
        )
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        path = self.template_path(key)
        if not path.exists():
            raise TemplateError(f"Missing template: {path}")

        raw = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
        if raw is None:
            raise TemplateError(f"No pude leer el template: {path}")

        if raw.ndim == 2:
            bgr = cv2.cvtColor(raw, cv2.COLOR_GRAY2BGR)
            alpha = None
        elif raw.shape[2] == 4:
            bgr = raw[:, :, :3].copy()
            alpha = raw[:, :, 3].copy()
        elif raw.shape[2] == 3:
            bgr = raw.copy()
            alpha = None
        else:
            raise TemplateError(f"Formato de imagen no soportado: {path}")

        mask = _prepare_mask(bgr, alpha, spec, self.config)

        if abs(scale - 1.0) > 0.001:
            interpolation = cv2.INTER_AREA if scale < 1.0 else cv2.INTER_LINEAR
            new_width = max(8, int(round(bgr.shape[1] * scale)))
            new_height = max(8, int(round(bgr.shape[0] * scale)))
            bgr = cv2.resize(bgr, (new_width, new_height), interpolation=interpolation)
            mask = cv2.resize(mask, (new_width, new_height), interpolation=interpolation)
            _, mask = cv2.threshold(mask, 10, 255, cv2.THRESH_BINARY)

        if int((mask > 0).sum()) < 30:
            raise TemplateError(f"The mask for {path.name} is too small.")

        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        data = TemplateData(spec=spec, path=path, bgr=bgr, gray=gray, mask=mask, scale=scale)
        self._cache[cache_key] = data
        return data

    def template_data(self, key: str, scale: float = 1.0):
        """Public access to a loaded template (used by color detectors)."""
        return self._load(key, scale=scale)

    # -- search -------------------------------------------------------------

    @staticmethod
    def _ncc(patch_gray: np.ndarray, template_gray: np.ndarray, mask: np.ndarray) -> float:
        selected = mask > 0
        a = patch_gray[selected].astype(np.float32)
        b = template_gray[selected].astype(np.float32)
        a = a - float(a.mean())
        b = b - float(b.mean())
        denominator = float(np.linalg.norm(a) * np.linalg.norm(b))
        if denominator < 1e-6:
            return 0.0
        return float(np.dot(a, b) / denominator)

    def find(
        self,
        frame: np.ndarray,
        key: str,
        threshold: Optional[float] = None,
        region: Optional[tuple[int, int, int, int]] = None,
        max_results: Optional[int] = None,
        scale: Optional[float] = None,
    ) -> list[Match]:
        if frame is None or frame.size == 0:
            return []

        data = self._load(key, scale=scale)
        base_threshold = self.config.threshold if threshold is None else threshold
        minimum = min(0.995, max(0.30, base_threshold + data.spec.threshold_boost))
        candidate_threshold = max(0.35, minimum - 0.20)
        limit = data.spec.max_results if max_results is None else max_results

        frame_h, frame_w = frame.shape[:2]
        if region is None:
            region = default_region(key, frame_w, frame_h)
        if region is not None:
            rx, ry, rw, rh = (int(v) for v in region)
            rx = max(0, min(frame_w - 1, rx))
            ry = max(0, min(frame_h - 1, ry))
            rw = max(1, min(rw, frame_w - rx))
            rh = max(1, min(rh, frame_h - ry))
            search = frame[ry : ry + rh, rx : rx + rw]
            offset_x, offset_y = rx, ry
        else:
            search = frame
            offset_x, offset_y = 0, 0

        if search.shape[0] < data.height or search.shape[1] < data.width:
            return []

        # Grayscale matching is ~3-4x faster than color and the NCC score is
        # already computed on grayscale, so detection quality does not change.
        if search.ndim == 3:
            search_gray = cv2.cvtColor(search, cv2.COLOR_BGR2GRAY)
        else:
            search_gray = search
        result = cv2.matchTemplate(
            search_gray,
            data.gray,
            cv2.TM_CCORR_NORMED,
            mask=data.mask,
        )
        result = np.nan_to_num(result, nan=-1.0, posinf=-1.0, neginf=-1.0)

        matches: list[Match] = []
        nms_x = max(6, data.width // 2)
        nms_y = max(6, data.height // 2)

        # Scan a few extra candidates so false positives can be rejected
        # without losing the real button.
        # Verify more candidates than we return. With TM_CCORR_NORMED the
        # brightest patches can outrank the real button; the NCC check below
        # rejects them. Four candidates was too few and lost real buttons.
        scan_limit = max(12, min(32, limit * 2))
        for _ in range(scan_limit):
            _, candidate_score, _, location = cv2.minMaxLoc(result)
            if candidate_score < candidate_threshold:
                break

            x, y = int(location[0]), int(location[1])
            patch_gray = search_gray[
                y : y + data.height, x : x + data.width
            ]
            if (
                patch_gray.shape[0] != data.height
                or patch_gray.shape[1] != data.width
            ):
                break
            score = self._ncc(patch_gray, data.gray, data.mask)

            if score >= minimum:
                matches.append(
                    Match(
                        key=key,
                        x=offset_x + x,
                        y=offset_y + y,
                        w=data.width,
                        h=data.height,
                        score=score,
                    )
                )
                if len(matches) >= limit:
                    break

            # Evita que la misma coincidencia vuelva a salir desplazada.
            x0 = max(0, x - nms_x)
            y0 = max(0, y - nms_y)
            x1 = min(result.shape[1], x + nms_x + 1)
            y1 = min(result.shape[0], y + nms_y + 1)
            result[y0:y1, x0:x1] = -1.0

        matches.sort(key=lambda m: (m.y, m.x))
        return matches

    def best(
        self,
        frame: np.ndarray,
        key: str,
        threshold: Optional[float] = None,
        region: Optional[tuple[int, int, int, int]] = None,
        scale: Optional[float] = None,
    ) -> Optional[Match]:
        matches = self.find(
            frame,
            key,
            threshold=threshold,
            region=region,
            max_results=4,
            scale=scale,
        )
        if not matches:
            return None
        return max(matches, key=lambda m: m.score)

    def best_of(
        self,
        frame: np.ndarray,
        keys: Iterable[str],
        threshold: Optional[float] = None,
        scale: Optional[float] = None,
    ) -> tuple[Optional[str], Optional[Match]]:
        best_key: Optional[str] = None
        best_match: Optional[Match] = None
        for key in keys:
            match = self.best(frame, key, threshold=threshold, scale=scale)
            if match is None:
                continue
            if best_match is None or match.score > best_match.score:
                best_key, best_match = key, match
        return best_key, best_match

    def shop_open(
        self,
        frame: np.ndarray,
        threshold: Optional[float] = None,
        scale: Optional[float] = None,
    ) -> bool:
        return bool(
            self.find(
                frame,
                "buy",
                threshold=threshold,
                max_results=1,
                scale=scale,
            )
            or self.find(
                frame,
                "scroll",
                threshold=threshold,
                max_results=1,
                scale=scale,
            )
            or self.find(
                frame,
                "close",
                threshold=threshold,
                max_results=1,
                scale=scale,
            )
        )

    def annotate(self, frame: np.ndarray, matches: Iterable[Match]) -> np.ndarray:
        annotated = frame.copy()
        for match in matches:
            color = MATCH_COLORS.get(match.key, (0, 255, 255))
            cv2.rectangle(
                annotated,
                (match.x, match.y),
                (match.x + match.w, match.y + match.h),
                color,
                2,
            )
            label = f"{match.key} {match.score:.2f}"
            text_size, _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1)
            tx = max(0, match.x)
            ty = max(16, match.y - 5)
            cv2.rectangle(
                annotated,
                (tx, ty - text_size[1] - 4),
                (tx + text_size[0] + 6, ty + 2),
                color,
                -1,
            )
            cv2.putText(
                annotated,
                label,
                (tx + 3, ty - 2),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.45,
                (10, 15, 25),
                1,
                cv2.LINE_AA,
            )
        return annotated

    def detect_all(
        self,
        frame: np.ndarray,
        keys: Optional[Iterable[str]] = None,
    ) -> list[Match]:
        selected = list(keys) if keys is not None else [spec.key for spec in TEMPLATE_SPECS]
        matches: list[Match] = []
        for key in selected:
            try:
                matches.extend(
                    self.find(
                        frame, key, max_results=SPECS_BY_KEY[key].max_results
                    )
                )
            except TemplateError:
                # Optional templates (Fuse, Best place) may not exist yet.
                continue
        matches.sort(key=lambda m: (m.y, m.x))
        return matches

    def calibrate_scale(
        self,
        frame: np.ndarray,
        keys: tuple[str, ...] = ("battle", "spawner1", "spawner2"),
        scales: tuple[float, ...] = (0.6, 0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.3, 1.4),
    ) -> dict[str, Any]:
        """Try several scales and return the best-scoring one."""
        best_scale = self.config.scale
        best_score = 0.0
        best_key: Optional[str] = None
        details: list[dict[str, Any]] = []

        for scale in scales:
            key, match = self.best_of(frame, keys, threshold=0.35, scale=scale)
            score = match.score if match else 0.0
            details.append({"scale": scale, "key": key, "score": score})
            if match is not None and score > best_score:
                best_scale, best_score, best_key = scale, score, key

        return {
            "scale": best_scale,
            "score": best_score,
            "key": best_key,
            "details": details,
        }
