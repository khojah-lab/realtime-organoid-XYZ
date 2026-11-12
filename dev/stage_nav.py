#!/usr/bin/env python3
"""
dev/stage_nav.py
────────────────────────────────────────────────────────────────
Minimal interactive CLI for XYZ stage navigation, landmark zeroing,
bookmarking, crash-recovery resync, and single-well circular
boustrophedon (snake) scanning.

Usage on Raspberry Pi (while watching http://100.112.125.34:3000/):
  python3 dev/stage_nav.py

Usage on local machine (simulation mode):
  python3 dev/stage_nav.py --sim
  python3 dev/stage_nav.py --sim --self-test
────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import argparse
import datetime
import os
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent


def _configure_paths(use_sim: bool) -> None:
    if use_sim:
        sys.path[:0] = [str(REPO_DIR / "dev" / "fakes"), str(REPO_DIR)]
    else:
        sys.path[:0] = [str(REPO_DIR)]


class StageNavCLI:
    """Interactive CLI wrapper around StageNavigator."""

    def __init__(
        self,
        server_url: str = "http://127.0.0.1:3000",
        state_path: Path | None = None,
        step_delay: float | None = None,
    ) -> None:
        import cv2
        import numpy as np
        import config
        from hardware import gpio_control, stepper_motors
        from services.stage_navigator import StageNavigator

        self.cv2 = cv2
        self.np = np
        self.config = config
        self.gpio_control = gpio_control
        self.stepper_motors = stepper_motors
        self.server_url = server_url.rstrip("/")

        self.gpio_control.init_gpio()
        kwargs = {}
        if state_path is not None:
            kwargs["state_path"] = state_path
        if step_delay is not None:
            kwargs["step_delay"] = step_delay
        self.nav = StageNavigator(**kwargs)
        self.jog_step = 250

    def grab_frame(self):
        """Fetch a BGR frame from `/video` stream, or fall back to direct camera."""
        try:
            req = urllib.request.Request(f"{self.server_url}/video")
            with urllib.request.urlopen(req, timeout=1.5) as resp:
                buf = b""
                for _ in range(256):
                    chunk = resp.read(4096)
                    if not chunk:
                        break
                    buf += chunk
                    start = buf.find(b"\xff\xd8")
                    end = buf.find(b"\xff\xd9", start + 2) if start != -1 else -1
                    if start != -1 and end != -1:
                        arr = self.np.frombuffer(buf[start : end + 2], dtype=self.np.uint8)
                        frame = self.cv2.imdecode(arr, self.cv2.IMREAD_COLOR)
                        if frame is not None:
                            return frame
        except Exception:
            pass

        try:
            from hardware.camera import capture_bgr_frame
            return capture_bgr_frame()
        except Exception:
            return None

    def scan_well(
        self,
        well_name: str = "bottom_middle",
        interactive_verify: bool = True,
    ) -> list[str]:
        """
        Execute a layer-by-layer circular boustrophedon scan on `well_name`,
        return to `(0, 0)` landmark, and prompt user for visual verification.
        """
        if self.nav.state.get("position_uncertain"):
            print(
                "  ✗ Scan blocked: stage position is marked UNCERTAIN after an interrupted move.\n"
                "    Visually align a landmark and run 'zero' or 'reset-to <bookmark>' first."
            )
            return []

        if well_name not in self.nav.bookmarks:
            print(f"  ✗ Unknown bookmark '{well_name}'. Use 'mark {well_name}' first.")
            return []

        cx, cy = self.nav.bookmarks[well_name]
        geom = self.nav.geometry
        tiles = self.nav.generate_circular_grid(
            center_x=cx,
            center_y=cy,
            radius=int(geom["well_radius_steps"]),
            step_x=int(geom["step_x"]),
            step_y=int(geom["step_y"]),
        )
        if not tiles:
            print("  ✗ No tiles generated (check soft limits and well geometry).")
            return []

        settle_sec = float(geom.get("move_settle_sec", 0.5))
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        os.makedirs(self.config.IMAGE_DIR, exist_ok=True)

        print("\n" + "═" * 64)
        print(
            f"  CIRCULAR SCAN: '{well_name}' center=({cx}, {cy}) | "
            f"R={geom['well_radius_steps']} | step=({geom['step_x']}, {geom['step_y']}) | "
            f"tiles={len(tiles)}"
        )
        print("═" * 64)

        self.gpio_control.set_led(True)
        saved_files: list[str] = []

        try:
            for idx, tile in enumerate(tiles, 1):
                tx, ty = tile["x"], tile["y"]
                r_idx, c_idx = tile["row"], tile["col"]
                print(
                    f"  [{idx:3d}/{len(tiles):3d}] Row {r_idx:2d} Col {c_idx:2d} -> "
                    f"Moving to (X={tx:+6d}, Y={ty:+6d})..."
                )
                self.nav.move_to(tx, ty)
                if settle_sec > 0:
                    time.sleep(settle_sec)

                frame = self.grab_frame()
                fname = f"{well_name}_r{r_idx:02d}_c{c_idx:02d}_{stamp}.jpg"
                out_path = str(self.config.IMAGE_DIR / fname)
                if frame is not None and self.cv2.imwrite(out_path, frame):
                    saved_files.append(out_path)

            print("\n  Returning to (0, 0) landmark (`bottom_left`)...")
            self.nav.move_to(0, 0)
            print(f"  ✓ Arrived at (X={self.nav.pos['x']}, Y={self.nav.pos['y']}).")
        finally:
            self.gpio_control.set_led(False)

        if interactive_verify:
            try:
                ans = input("\n  Please verify live stream at (0, 0): Is the landmark centered? [Y/n]: ").strip().lower()
                if ans.startswith("n"):
                    print(
                        "  ⚠ Drift noted. Use 'w/a/s/d' or 'jog' to re-center the landmark, "
                        "then run 'zero' to re-sync (0, 0)."
                    )
                else:
                    print("  ✓ Landmark verified in-sync!")
            except (EOFError, KeyboardInterrupt):
                print()

        return saved_files

    def measure_well_interactive(self, well_name: str = "bottom_center") -> None:
        """Interactive helper to compute well center & radius from left/right or bottom/top edges."""
        print(
            f"\n  MEASURE WELL '{well_name}':\n"
            f"  1. Jog to the LEFT edge of '{well_name}' and record X, then RIGHT edge.\n"
            f"  Or enter known coordinates directly."
        )
        try:
            raw_l = input(f"  Enter LEFT edge X (or press Enter to use current X={self.nav.pos['x']}): ").strip()
            x_left = int(raw_l) if raw_l else self.nav.pos["x"]
            raw_r = input("  Enter RIGHT edge X: ").strip()
            x_right = int(raw_r)
            raw_y = input(f"  Enter center Y (or press Enter to use current Y={self.nav.pos['y']}): ").strip()
            y_center = int(raw_y) if raw_y else self.nav.pos["y"]
        except (ValueError, EOFError, KeyboardInterrupt):
            print("  ✗ Aborted well measurement.")
            return

        cx = (x_left + x_right) // 2
        radius = abs(x_right - x_left) // 2
        if radius <= 0:
            print("  ✗ Radius must be > 0.")
            return

        self.nav.set_bookmark(well_name, cx, y_center)
        self.nav.set_geometry(
            well_radius_steps=radius,
            step_x=int(self.nav.geometry["step_x"]),
            step_y=int(self.nav.geometry["step_y"]),
        )
        print(f"  ✓ Saved '{well_name}' center=({cx}, {y_center}), well_radius_steps={radius}")

    def print_status(self) -> None:
        pos = self.nav.pos
        lims = self.nav.soft_limits
        geom = self.nav.geometry
        uncertain = " [⚠ UNCERTAIN - RE-SYNC NEEDED]" if self.nav.state.get("position_uncertain") else ""
        print("\n" + "─" * 68)
        print(
            f"  POS: (X={pos['x']:+6d}, Y={pos['y']:+6d}, Z={pos['z']:+6d}){uncertain}  |  "
            f"JOG={self.jog_step}"
        )
        print(
            f"  SOFT LIMITS: X=[{lims['min_x']}, {lims['max_x']}]  "
            f"Y=[{lims['min_y']}, {lims['max_y']}]"
        )
        print(
            f"  GEOMETRY: R={geom['well_radius_steps']}  "
            f"step=({geom['step_x']}, {geom['step_y']})  "
            f"settle={geom['move_settle_sec']}s"
        )
        bm_str = ", ".join(f"{k}:({v[0]},{v[1]})" for k, v in self.nav.bookmarks.items())
        print(f"  BOOKMARKS: {bm_str}")
        print("─" * 68)

    def print_help(self) -> None:
        print(
            """
  COMMANDS:
    w / s                        : Jog Y Up (+steps) / Down (-steps)
    a / d                        : Jog X Left (-steps) / Right (+steps)
    step <steps>                 : Set jog step size (default: 250)
    jog <x|y|z> <signed_steps>   : Move axis by signed steps
    zero                         : Set current physical position as (0, 0) (`bottom_left` landmark)
    mark <name> [x y]            : Bookmark current position (or explicit x y) as <name>
    goto <name | x y>            : Move to bookmark <name> or coordinates (x, y)
    reset-to <name>              : Override software (X, Y) to bookmark <name> WITHOUT moving motors
    limits <min_x> <max_x> <min_y> <max_y> : Update soft travel limits
    geometry <radius> <step_x> <step_y> [settle_sec] : Update circular scan parameters
    measure-well [name]          : Calculate center & radius from left/right well edges
    scan-well [name]             : Circular boustrophedon scan on <name> (default: bottom_center)
    led                          : Toggle illumination LED
    q                            : Quit
"""
        )

    def interactive_loop(self) -> None:
        self.print_help()
        while True:
            self.print_status()
            try:
                raw = input("nav> ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nExiting...")
                break

            if not raw:
                continue
            parts = raw.split()
            cmd = parts[0].lower()

            try:
                if cmd in ("q", "quit", "exit"):
                    self.stepper_motors.release_all()
                    break
                elif cmd in ("?", "help"):
                    self.print_help()
                elif cmd == "w":
                    self.nav.move_by(dy=self.jog_step)
                elif cmd == "s":
                    self.nav.move_by(dy=-self.jog_step)
                elif cmd == "a":
                    self.nav.move_by(dx=-self.jog_step)
                elif cmd == "d":
                    self.nav.move_by(dx=self.jog_step)
                elif cmd == "step":
                    self.jog_step = abs(int(parts[1]))
                    print(f"  ✓ Jog step set to {self.jog_step}")
                elif cmd == "jog":
                    axis = parts[1].lower()
                    delta = int(parts[2])
                    self.nav.move_by(
                        dx=delta if axis == "x" else 0,
                        dy=delta if axis == "y" else 0,
                        dz=delta if axis == "z" else 0,
                    )
                elif cmd == "zero":
                    self.nav.set_origin()
                    print("  ✓ Origin set to (0, 0, 0) at `bottom_left` landmark.")
                elif cmd == "mark":
                    name = parts[1]
                    if len(parts) >= 4:
                        coords = self.nav.set_bookmark(name, int(parts[2]), int(parts[3]))
                    else:
                        coords = self.nav.set_bookmark(name)
                    print(f"  ✓ Bookmarked '{name}' at ({coords[0]}, {coords[1]})")
                elif cmd == "goto":
                    if len(parts) == 2:
                        pos = self.nav.goto_bookmark(parts[1])
                    else:
                        pos = self.nav.move_to(int(parts[1]), int(parts[2]))
                    print(f"  ✓ Position: (X={pos['x']}, Y={pos['y']}, Z={pos['z']})")
                elif cmd == "reset-to":
                    pos = self.nav.force_sync_to_bookmark(parts[1])
                    print(f"  ✓ Software coordinates synced to '{parts[1]}': (X={pos['x']}, Y={pos['y']})")
                elif cmd == "limits":
                    self.nav.set_soft_limits(int(parts[1]), int(parts[2]), int(parts[3]), int(parts[4]))
                    print(f"  ✓ Updated soft limits: {self.nav.soft_limits}")
                elif cmd == "geometry":
                    settle = float(parts[4]) if len(parts) >= 5 else None
                    self.nav.set_geometry(int(parts[1]), int(parts[2]), int(parts[3]), settle)
                    print(f"  ✓ Updated geometry: {self.nav.geometry}")
                elif cmd == "measure-well":
                    wname = parts[1] if len(parts) >= 2 else "bottom_middle"
                    self.measure_well_interactive(wname)
                elif cmd == "scan-well":
                    wname = parts[1] if len(parts) >= 2 else "bottom_middle"
                    self.scan_well(wname, interactive_verify=True)
                elif cmd == "led":
                    state = self.gpio_control.toggle_led()
                    print(f"  ✓ LED is now {'ON' if state else 'OFF'}")
                else:
                    print(f"  Unknown command '{cmd}'. Type 'help' for options.")
            except (IndexError, ValueError, KeyError) as e:
                print(f"  ✗ Command error: {e}")


def run_self_test() -> None:
    """Automated verification of StageNavigator, crash recovery, and circular scan."""
    from services.stage_navigator import StageNavigator

    print("[SELF-TEST] Running StageNavigator & circular scan verification...")
    with tempfile.TemporaryDirectory() as tmpdir:
        state_file = Path(tmpdir) / "stage_position.json"
        nav = StageNavigator(state_path=state_file, step_delay=0.0)

        # 1. Zero origin & set soft limits
        nav.set_origin()
        nav.set_soft_limits(min_x=-500, max_x=6000, min_y=-2000, max_y=2000)
        assert nav.pos == {"x": 0, "y": 0, "z": 0}

        # 2. Verify soft-limit clamping
        nav.move_to(7500, 2500)
        assert nav.pos["x"] == 6000 and nav.pos["y"] == 2000, f"Expected clamped (6000, 2000), got {nav.pos}"

        # 3. Bookmark & force_sync_to_bookmark (no-motion reset)
        nav.set_bookmark("bottom_center", 4000, 0)
        nav.force_sync_to_bookmark("bottom_left")
        assert nav.pos["x"] == 0 and nav.pos["y"] == 0

        # 4. Simulate mid-move crash (in_motion=True on disk) and verify reload flags position_uncertain
        nav.state["in_motion"] = True
        nav.save_state()
        reloaded = StageNavigator(state_path=state_file, step_delay=0.0)
        assert reloaded.state["position_uncertain"] is True
        assert reloaded.state["in_motion"] is False

        # Clear uncertainty via force_sync_to_bookmark
        reloaded.force_sync_to_bookmark("bottom_left")
        assert reloaded.state["position_uncertain"] is False

        # 5. Verify circular boustrophedon grid math
        reloaded.set_geometry(well_radius_steps=1000, step_x=400, step_y=400, move_settle_sec=0.0)
        tiles = reloaded.generate_circular_grid(center_x=4000, center_y=0)
        assert len(tiles) > 0
        # Ensure all tiles lie inside the circle and rows progress bottom-to-top
        prev_y = None
        for t in tiles:
            dist_sq = (t["x"] - 4000) ** 2 + (t["y"] - 0) ** 2
            assert dist_sq <= 1000 ** 2, f"Tile {t} outside radius!"
            if prev_y is not None:
                assert t["y"] >= prev_y, "Rows must move from bottom (-R) to top (+R)!"
            prev_y = t["y"]

        # Verify boustrophedon (snake) alternation between row 0 and row 1
        row0_x = [t["x"] for t in tiles if t["row"] == 0]
        row1_x = [t["x"] for t in tiles if t["row"] == 1]
        if len(row0_x) > 1:
            assert row0_x == sorted(row0_x), "Row 0 should move left-to-right"
        if len(row1_x) > 1:
            assert row1_x == sorted(row1_x, reverse=True), "Row 1 should move right-to-left"

        # 6. End-to-end CLI scan_well returning to (0, 0)
        cli = StageNavCLI(state_path=state_file, step_delay=0.0)
        cli.scan_well("bottom_center", interactive_verify=False)
        assert cli.nav.pos["x"] == 0 and cli.nav.pos["y"] == 0

    print("[SELF-TEST] ✓ All navigation, crash-recovery, and circular scan checks passed!")


def main() -> None:
    parser = argparse.ArgumentParser(description="Interactive XYZ Stage Navigation & Circular Well Scanner")
    parser.add_argument(
        "--sim",
        action="store_true",
        help="Use simulated RPi.GPIO, Picamera2, and MotorKit modules from dev/fakes",
    )
    parser.add_argument(
        "--server-url",
        default="http://127.0.0.1:3000",
        help="URL of running Flask server to grab frames from (default: http://127.0.0.1:3000)",
    )
    parser.add_argument(
        "--state-file",
        default=None,
        help="Path to stage_position.json (default: state/stage_position.json)",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Run automated self-test and exit",
    )
    args = parser.parse_args()

    _configure_paths(args.sim)

    if args.self_test:
        run_self_test()
        return

    state_path = Path(args.state_file) if args.state_file else None
    cli = StageNavCLI(server_url=args.server_url, state_path=state_path)
    cli.interactive_loop()


if __name__ == "__main__":
    main()
