"""
services/stage_navigator.py
────────────────────────────────────────────────────────────────
Persistent XYZ stage coordinate tracker, soft-limit clamping,
dual coordinate reset (origin zeroing + bookmark force-sync),
and circular boustrophedon (snake) trajectory generator.

Coordinate Convention (matching physical 6-well plate layout):
  Origin (0, 0) : Center of `bottom_left` well (landmark)
  +X (Right)    : stepper.FORWARD  (bottom_left -> bottom_center -> bottom_right)
  -X (Left)     : stepper.BACKWARD (bottom_right -> bottom_left)
  +Y (Up/Top)   : stepper.BACKWARD (bottom row -> top row)
  -Y (Down/Bot) : stepper.FORWARD  (top row -> bottom row)
  +Z (Up)       : stepper.BACKWARD
  -Z (Down)     : stepper.FORWARD
────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import datetime
import json
import math
import os
import signal
import threading
import time
from pathlib import Path

from config import BASE_DIR, STEP_DELAY
from hardware import stepper_motors

DEFAULT_STATE_PATH = BASE_DIR / "state" / "stage_position.json"


class StageNavigator:
    """
    Manages stage coordinates with atomic persistence, crash recovery,
    soft-limit clamping, bookmark navigation, and circular well scanning.
    """

    def __init__(
        self,
        state_path: Path | str | None = None,
        step_delay: float = STEP_DELAY,
    ) -> None:
        self.state_path = Path(state_path) if state_path else DEFAULT_STATE_PATH
        self.step_delay = step_delay
        self._lock = threading.RLock()

        self.state: dict = {
            "updated_at": None,
            "in_motion": False,
            "position_uncertain": False,
            "current_position": {"x": 0, "y": 0, "z": 0},
            "soft_limits": {
                "min_x": -1800, 
                "max_x": 9400,
                "min_y": -1200,
                "max_y": 6500,
            },
            "bookmarks": {
                "bottom_left": [0, 0],
                "bottom_middle": [4050, 0],
                "bottom_right": [8100, 0],
                "top_left": [0, 4250],
                "top_middle": [4050, 4250],
                "top_right": [8100, 4250],
            },
            "geometry": {
                "well_radius_steps": 1500,
                "step_x": 500,
                "step_y": 500,
                "move_settle_sec": 0.5,
            },
        }
        self._load_state()

    # ── State Persistence & Crash Detection ───────────────────
    def _load_state(self) -> None:
        os.makedirs(self.state_path.parent, exist_ok=True)
        if not self.state_path.exists():
            self.save_state()
            return

        try:
            with open(self.state_path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                for key in ("current_position", "soft_limits", "bookmarks", "geometry"):
                    if isinstance(loaded.get(key), dict):
                        self.state[key].update(loaded[key])
                self.state["in_motion"] = bool(loaded.get("in_motion", False))
                self.state["position_uncertain"] = bool(loaded.get("position_uncertain", False))
                self.state["updated_at"] = loaded.get("updated_at")

            # Detect hard crash / power loss mid-move
            if self.state["in_motion"]:
                self.state["in_motion"] = False
                self.state["position_uncertain"] = True
                self.save_state()
                pos = self.state["current_position"]
                print(
                    f"[NAV WARNING] Unclean shutdown detected during stage motion! "
                    f"Last recorded position (X={pos['x']}, Y={pos['y']}, Z={pos['z']}) is marked UNCERTAIN. "
                    f"Please visually align a landmark and run 'zero' or 'reset-to <bookmark>'."
                )
        except Exception as e:
            print(f"[NAV WARNING] Failed to read {self.state_path} ({e}); using defaults.")
            self.save_state()

    def save_state(self) -> None:
        """Atomically persist stage state to disk via a temporary file and os.replace."""
        with self._lock:
            os.makedirs(self.state_path.parent, exist_ok=True)
            self.state["updated_at"] = datetime.datetime.now().isoformat(timespec="seconds")
            tmp_path = self.state_path.with_suffix(".json.tmp")
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(self.state, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, self.state_path)

    # ── Properties & Configuration ────────────────────────────
    @property
    def pos(self) -> dict[str, int]:
        return self.state["current_position"]

    @property
    def soft_limits(self) -> dict[str, int]:
        return self.state["soft_limits"]

    @property
    def bookmarks(self) -> dict[str, list[int]]:
        return self.state["bookmarks"]

    @property
    def geometry(self) -> dict[str, int | float]:
        return self.state["geometry"]

    def set_soft_limits(self, min_x: int, max_x: int, min_y: int, max_y: int) -> None:
        if min_x > max_x or min_y > max_y:
            raise ValueError("min limit cannot exceed max limit")
        self.state["soft_limits"] = {
            "min_x": int(min_x),
            "max_x": int(max_x),
            "min_y": int(min_y),
            "max_y": int(max_y),
        }
        self.save_state()

    def set_geometry(
        self,
        well_radius_steps: int,
        step_x: int,
        step_y: int,
        move_settle_sec: float | None = None,
    ) -> None:
        if well_radius_steps <= 0 or step_x <= 0 or step_y <= 0:
            raise ValueError("Radius and step sizes must be positive integers")
        self.state["geometry"]["well_radius_steps"] = int(well_radius_steps)
        self.state["geometry"]["step_x"] = int(step_x)
        self.state["geometry"]["step_y"] = int(step_y)
        if move_settle_sec is not None:
            self.state["geometry"]["move_settle_sec"] = float(move_settle_sec)
        self.save_state()

    # ── Dual Coordinate Reset & Bookmarking ───────────────────
    def set_origin(self) -> dict[str, int]:
        """
        Reset current physical position as (0, 0, 0) (`bottom_left` landmark)
        and clear any crash uncertainty flag.
        """
        with self._lock:
            self.state["current_position"] = {"x": 0, "y": 0, "z": 0}
            self.state["bookmarks"]["bottom_left"] = [0, 0]
            self.state["in_motion"] = False
            self.state["position_uncertain"] = False
            self.save_state()
            return dict(self.pos)

    def set_bookmark(self, name: str, x: int | None = None, y: int | None = None) -> list[int]:
        """Record a named XY bookmark (defaults to current XY position)."""
        with self._lock:
            bx = int(self.pos["x"] if x is None else x)
            by = int(self.pos["y"] if y is None else y)
            self.state["bookmarks"][name] = [bx, by]
            self.save_state()
            return [bx, by]

    def force_sync_to_bookmark(self, name: str) -> dict[str, int]:
        """
        Fast coordinate override: sets software (X, Y) coordinates to `bookmarks[name]`
        WITHOUT moving the motors, and clears `position_uncertain`.
        """
        with self._lock:
            if name not in self.bookmarks:
                raise KeyError(f"Unknown bookmark '{name}'. Available: {list(self.bookmarks.keys())}")
            bx, by = self.bookmarks[name]
            self.state["current_position"]["x"] = int(bx)
            self.state["current_position"]["y"] = int(by)
            self.state["in_motion"] = False
            self.state["position_uncertain"] = False
            self.save_state()
            return dict(self.pos)

    # ── Clamping & Safe Stepper Movement ──────────────────────
    def clamp_xy(self, target_x: int, target_y: int) -> tuple[int, int, bool]:
        """Clamp (target_x, target_y) to soft_limits. Returns (cx, cy, was_clamped)."""
        lims = self.soft_limits
        cx = max(lims["min_x"], min(lims["max_x"], int(target_x)))
        cy = max(lims["min_y"], min(lims["max_y"], int(target_y)))
        was_clamped = (cx != int(target_x)) or (cy != int(target_y))
        return cx, cy, was_clamped

    def _step_axis(self, axis: str, signed_steps: int) -> int:
        """
        Step a single axis ('x', 'y', or 'z') by `signed_steps`, updating
        `current_position` after every step and flushing state in `finally`.
        """
        if signed_steps == 0:
            return 0

        axis = axis.lower()
        steps = abs(int(signed_steps))
        sign = 1 if signed_steps > 0 else -1
        stepper = stepper_motors.stepper

        if axis == "x":
            # +X (right) = FORWARD, -X (left) = BACKWARD
            direction_str = "FORWARD" if sign > 0 else "BACKWARD"
            motors = [stepper_motors.x_motor] if stepper_motors.x_motor else []
        elif axis == "y":
            # +Y (bottom -> top) = BACKWARD, -Y (top -> bottom) = FORWARD
            direction_str = "BACKWARD" if sign > 0 else "FORWARD"
            motors = [stepper_motors.y_motor] if stepper_motors.y_motor else []
        elif axis == "z":
            # +Z (up) = BACKWARD, -Z (down) = FORWARD
            direction_str = "BACKWARD" if sign > 0 else "FORWARD"
            kit1 = stepper_motors.kit1
            motors = [kit1.stepper1, kit1.stepper2] if kit1 else []
        else:
            raise ValueError(f"Unknown axis: {axis}")

        with self._lock:
            self.state["in_motion"] = True
            self.save_state()

        completed = 0
        interrupted = False

        # Catch SIGTERM (e.g. `systemctl restart xyz`) on the main thread so
        # the finally block flushes the exact step reached before exit.
        prev_sigterm = None
        if threading.current_thread() is threading.main_thread():
            def _handle_sigterm(signum, frame):
                nonlocal interrupted
                interrupted = True
                raise KeyboardInterrupt("SIGTERM received during stage movement")

            prev_sigterm = signal.signal(signal.SIGTERM, _handle_sigterm)

        try:
            if not motors or stepper is None:
                # Simulated / disconnected HAT mode
                self.pos[axis] += signed_steps
                completed = steps
                return signed_steps

            resolved_dir = stepper_motors.resolve_stepper_direction(direction_str)
            for _ in range(steps):
                if interrupted:
                    break
                for m in motors:
                    m.onestep(direction=resolved_dir, style=stepper.SINGLE)
                completed += 1
                self.pos[axis] += sign
                time.sleep(self.step_delay)
        finally:
            for m in motors:
                try:
                    m.release()
                except Exception:
                    pass
            if prev_sigterm is not None:
                signal.signal(signal.SIGTERM, prev_sigterm)
            with self._lock:
                self.state["in_motion"] = False
                self.save_state()

        return completed * sign

    def move_to(
        self,
        target_x: int,
        target_y: int,
        target_z: int | None = None,
    ) -> dict[str, int]:
        """Move to (target_x, target_y[, target_z]) with soft-limit clamping on XY."""
        cx, cy, clamped = self.clamp_xy(target_x, target_y)
        if clamped:
            print(
                f"  [NAV CLAMP] Requested ({target_x}, {target_y}) clamped to "
                f"soft limits ({cx}, {cy})"
            )

        dx = cx - self.pos["x"]
        dy = cy - self.pos["y"]
        dz = (int(target_z) - self.pos["z"]) if target_z is not None else 0

        if dx != 0:
            self._step_axis("x", dx)
        if dy != 0:
            self._step_axis("y", dy)
        if dz != 0:
            self._step_axis("z", dz)

        return dict(self.pos)

    def move_by(self, dx: int = 0, dy: int = 0, dz: int = 0) -> dict[str, int]:
        """Relative move by (dx, dy, dz) steps, clamped to soft limits."""
        return self.move_to(
            self.pos["x"] + int(dx),
            self.pos["y"] + int(dy),
            self.pos["z"] + int(dz) if dz != 0 else None,
        )

    def goto_bookmark(self, name: str) -> dict[str, int]:
        """Move stage to a saved bookmark's XY coordinates."""
        if name not in self.bookmarks:
            raise KeyError(f"Unknown bookmark '{name}'. Available: {list(self.bookmarks.keys())}")
        bx, by = self.bookmarks[name]
        return self.move_to(bx, by)

    # ── Circular Boustrophedon (Snake) Grid Generator ─────────
    def generate_circular_grid(
        self,
        center_x: int,
        center_y: int,
        radius: int | None = None,
        step_x: int | None = None,
        step_y: int | None = None,
    ) -> list[dict[str, int]]:
        """
        Generate a bottom-to-top layer-by-layer boustrophedon (snake) grid of tiles
        strictly inside a circle of `radius` centered at `(center_x, center_y)`.

        Each returned item is:
          {"row": int, "col": int, "x": int, "y": int}
        Tiles outside `soft_limits` are automatically skipped.
        """
        r = int(radius if radius is not None else self.geometry["well_radius_steps"])
        sx = int(step_x if step_x is not None else self.geometry["step_x"])
        sy = int(step_y if step_y is not None else self.geometry["step_y"])

        if r <= 0 or sx <= 0 or sy <= 0:
            raise ValueError("radius, step_x, and step_y must be positive")

        lims = self.soft_limits
        tiles: list[dict[str, int]] = []

        # Symmetric rows from bottom (center_y - max_ky*sy) to top (center_y + max_ky*sy)
        # so (center_x, center_y) is always included as the central tile.
        max_ky = int(math.floor(r / sy))
        y_offsets = [k * sy for k in range(-max_ky, max_ky + 1)]

        for row_idx, dy in enumerate(y_offsets):
            y = center_y + dy
            if not (lims["min_y"] <= y <= lims["max_y"]):
                continue

            x_half = math.sqrt(max(0.0, float(r * r - dy * dy)))

            # Build symmetric X offsets around center_x within [-x_half, +x_half]
            max_k = int(math.floor(x_half / sx))
            x_coords = [center_x + k * sx for k in range(-max_k, max_k + 1)]
            # Keep only tiles within soft X limits and circle radius
            x_coords = [
                x for x in x_coords
                if (lims["min_x"] <= x <= lims["max_x"])
                and ((x - center_x) ** 2 + (y - center_y) ** 2 <= r * r)
            ]

            # Snake / boustrophedon ordering: even rows left->right, odd rows right->left
            if row_idx % 2 == 1:
                x_coords.reverse()

            for col_idx, x in enumerate(x_coords):
                tiles.append({
                    "row": row_idx,
                    "col": col_idx,
                    "x": int(x),
                    "y": int(y),
                })

        return tiles
