#!/usr/bin/env python3
"""
dev/calibrate_stage.py
────────────────────────────────────────────────────────────────
Interactive in-lab hardware calibration & diagnostic CLI for the
XYZ Organoid Imaging System.

Designed to run over SSH on the Raspberry Pi while you watch the
live web stream at http://100.112.125.34:3000/ in your browser.

Capabilities:
  1. Limit Switch Inspector (`l` / `p`):
     - Live-polls GPIO 17 (LR) and GPIO 27 (UD) so you can press each
       switch by hand and confirm active-high vs. active-low behavior,
       plus test internal pull-up / pull-down resistor configurations.
  2. Safe Homing (`h`):
     - Steps X and Y toward the limit switches with a safety step limit
       and zeros (X=0, Y=0) when triggered.
  3. Precision XYZ Step Jogging (`w/a/s/d` for XY, `u/j` for Z):
     - Move any axis by custom step counts while tracking cumulative
       (X, Y, Z) coordinates from your origin.
  4. Waypoint & FOV Bookmarking (`b`):
     - Record exact (X, Y, Z) step coordinates for well centers
       (bottom_right .. top_right), single-FOV shifts, or well edges.
  5. Z-Axis Focus & Sharpness Sweep (`z`):
     - Sweeps Z across a range, grabs a frame at each Z plane (via the
       running web server's `/video` stream or Picamera2 fallback),
       computes Laplacian variance sharpness + mean brightness, saves
       annotated images to `images/calibration/`, and optionally moves
       to the sharpest Z plane.
  6. LED & Motion Settling Timer (`t`):
     - Toggles LED or steps the stage and samples frames every 100 ms
       for 3 seconds to measure exposure warm-up and liquid vibration
       settling time.
  7. Profile Export (`save`):
     - Saves all recorded calibration data to `calibration_profile.json`.

Usage on Raspberry Pi:
  python3 dev/calibrate_stage.py

Usage on macOS / non-Pi with simulated hardware:
  python3 dev/calibrate_stage.py --sim
  python3 dev/calibrate_stage.py --sim --self-test
────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent


def _configure_paths(use_sim: bool) -> None:
    if use_sim:
        sys.path[:0] = [str(REPO_DIR / "dev" / "fakes"), str(REPO_DIR)]
    else:
        sys.path[:0] = [str(REPO_DIR)]


class StageCalibrator:
    """Interactive calibration controller for XYZ motors, GPIO switches, and camera."""

    WELL_PRESETS = [
        "bottom_right",
        "bottom_center",
        "bottom_left",
        "top_left",
        "top_center",
        "top_right",
        "fov_shift_x_100pct",
        "fov_shift_x_80pct",
        "fov_shift_y_100pct",
        "fov_shift_y_80pct",
        "well_edge_left",
        "well_edge_right",
    ]

    def __init__(self, server_url: str = "http://127.0.0.1:3000", profile_path: Path | None = None):
        import cv2
        import numpy as np
        import config
        from hardware import gpio_control, stepper_motors

        self.cv2 = cv2
        self.np = np
        self.config = config
        self.gpio_control = gpio_control
        self.stepper_motors = stepper_motors
        self.server_url = server_url.rstrip("/")
        self.profile_path = profile_path or (REPO_DIR / "calibration_profile.json")
        self.calib_img_dir = config.IMAGE_DIR / "calibration"
        os.makedirs(self.calib_img_dir, exist_ok=True)

        self.gpio_control.init_gpio()

        # Current step coordinates relative to origin (0, 0, 0)
        self.pos = {"x": 0, "y": 0, "z": 0}
        self.jog_steps = {"xy": 250, "z": 25}
        self.step_delay = config.STEP_DELAY

        # Limit switch polarity configuration (1 = active HIGH, 0 = active LOW)
        self.limit_triggered_value = {"lr": 0, "ud": 0}
        self.pull_mode = "NONE"

        # Stored calibration data
        self.profile: dict = {
            "updated_at": None,
            "gpio": {
                "limit_switch_lr_pin": config.LIMIT_SWITCH_LR,
                "limit_switch_ud_pin": config.LIMIT_SWITCH_UD,
                "led_pin": config.LED_PIN,
                "pull_mode": self.pull_mode,
                "lr_triggered_value": self.limit_triggered_value["lr"],
                "ud_triggered_value": self.limit_triggered_value["ud"],
            },
            "step_settings": {
                "step_delay_sec": self.step_delay,
            },
            "waypoints": {},
            "z_sweeps": [],
            "settling_tests": [],
            "notes": [],
        }
        self._load_existing_profile()

    def _load_existing_profile(self) -> None:
        if self.profile_path.exists():
            try:
                with open(self.profile_path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict):
                    self.profile.update(loaded)
                    gpio_cfg = self.profile.get("gpio", {})
                    self.pull_mode = gpio_cfg.get("pull_mode", self.pull_mode)
                    self.limit_triggered_value["lr"] = gpio_cfg.get("lr_triggered_value", 0)
                    self.limit_triggered_value["ud"] = gpio_cfg.get("ud_triggered_value", 0)
                print(f"[CALIB] Loaded existing profile from {self.profile_path}")
            except Exception as e:
                print(f"[CALIB] Could not load existing profile ({e}); starting fresh.")

    def save_profile(self) -> None:
        self.profile["updated_at"] = datetime.datetime.now().isoformat(timespec="seconds")
        self.profile["gpio"]["pull_mode"] = self.pull_mode
        self.profile["gpio"]["lr_triggered_value"] = self.limit_triggered_value["lr"]
        self.profile["gpio"]["ud_triggered_value"] = self.limit_triggered_value["ud"]
        self.profile["step_settings"]["step_delay_sec"] = self.step_delay

        with open(self.profile_path, "w", encoding="utf-8") as f:
            json.dump(self.profile, f, indent=2)
        print(f"  ✓ Saved calibration profile to {self.profile_path}")

    # ── GPIO & Limit Switches ─────────────────────────────────
    def read_limit_switches(self) -> dict[str, int | None]:
        GPIO = self.gpio_control.GPIO
        if GPIO is None:
            return {"lr": None, "ud": None}
        try:
            lr_val = int(GPIO.input(self.config.LIMIT_SWITCH_LR))
            ud_val = int(GPIO.input(self.config.LIMIT_SWITCH_UD))
            return {"lr": lr_val, "ud": ud_val}
        except Exception as e:
            print(f"  [GPIO ERROR] {e}")
            return {"lr": None, "ud": None}

    def configure_gpio_pull(self, mode: str) -> None:
        """Configure internal RPi.GPIO pull-up/pull-down resistors (NONE, UP, DOWN)."""
        GPIO = self.gpio_control.GPIO
        mode = mode.upper()
        if GPIO is None:
            print("  [GPIO] Running without physical RPi.GPIO.")
            self.pull_mode = mode
            return

        try:
            if mode == "UP" and hasattr(GPIO, "PUD_UP"):
                GPIO.setup(self.config.LIMIT_SWITCH_LR, GPIO.IN, pull_up_down=GPIO.PUD_UP)
                GPIO.setup(self.config.LIMIT_SWITCH_UD, GPIO.IN, pull_up_down=GPIO.PUD_UP)
            elif mode == "DOWN" and hasattr(GPIO, "PUD_DOWN"):
                GPIO.setup(self.config.LIMIT_SWITCH_LR, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
                GPIO.setup(self.config.LIMIT_SWITCH_UD, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
            else:
                GPIO.setup(self.config.LIMIT_SWITCH_LR, GPIO.IN)
                GPIO.setup(self.config.LIMIT_SWITCH_UD, GPIO.IN)
                mode = "NONE"
            self.pull_mode = mode
            print(f"  ✓ Configured limit switch pins (17, 27) with pull_mode={self.pull_mode}")
        except TypeError:
            # Fake GPIO.setup(pin, dir) only takes 2 args
            self.pull_mode = mode
            print(f"  ✓ Configured fake GPIO pull_mode={self.pull_mode}")
        except Exception as e:
            print(f"  ✗ Failed to set pull mode: {e}")

    def inspect_limit_switches(self, duration_sec: float = 10.0) -> None:
        """Live-poll limit switches so the user can press them by hand."""
        print("\n" + "─" * 58)
        print(f"  LIVE LIMIT SWITCH MONITOR ({duration_sec:.0f}s) — Press Ctrl+C to stop early")
        print(f"  Pins: LR = BCM {self.config.LIMIT_SWITCH_LR}, UD = BCM {self.config.LIMIT_SWITCH_UD} | Pull = {self.pull_mode}")
        print("  Press each physical limit switch by hand and watch the values below:")
        print("─" * 58)
        start = time.time()
        last_vals = None
        try:
            while time.time() - start < duration_sec:
                vals = self.read_limit_switches()
                elapsed = time.time() - start
                marker = " <-- CHANGED!" if (last_vals is not None and vals != last_vals) else ""
                sys.stdout.write(
                    f"\r  [{elapsed:5.1f}s] LR (GPIO 17) = {vals['lr']} | UD (GPIO 27) = {vals['ud']}{marker}          "
                )
                sys.stdout.flush()
                if marker:
                    print()
                last_vals = vals
                time.sleep(0.05)
        except KeyboardInterrupt:
            pass
        print("\n" + "─" * 58)

    # ── Frame Grabber (HTTP /video stream or direct camera) ───
    def grab_frame(self):
        """
        Grab a single BGR image frame.
        1. Tries fetching a single JPEG frame from the running server's `/video` MJPEG stream
           so `xyz.service` can stay running while you watch in the browser.
        2. Falls back to `hardware.camera.capture_bgr_frame()` if the HTTP server isn't running.
        """
        # 1. Try local MJPEG stream first
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
                        jpg_bytes = buf[start : end + 2]
                        arr = self.np.frombuffer(jpg_bytes, dtype=self.np.uint8)
                        frame = self.cv2.imdecode(arr, self.cv2.IMREAD_COLOR)
                        if frame is not None:
                            return frame
        except Exception:
            pass

        # 2. Fallback to direct camera module
        try:
            from hardware.camera import capture_bgr_frame
            return capture_bgr_frame()
        except Exception:
            return None

    def compute_frame_metrics(self, frame) -> dict[str, float]:
        """Compute focus sharpness (Laplacian variance) and mean brightness."""
        if frame is None:
            return {"sharpness": 0.0, "brightness": 0.0, "contrast": 0.0}
        gray = self.cv2.cvtColor(frame, self.cv2.COLOR_BGR2GRAY)
        sharpness = float(self.cv2.Laplacian(gray, self.cv2.CV_64F).var())
        brightness = float(gray.mean())
        contrast = float(gray.std())
        return {
            "sharpness": round(sharpness, 2),
            "brightness": round(brightness, 2),
            "contrast": round(contrast, 2),
        }

    # ── Stepper Movement & Homing ─────────────────────────────
    def move_axis(self, axis: str, signed_steps: int, check_limits: bool = False) -> int:
        """
        Move axis ('x', 'y', or 'z') by `signed_steps`.
        Convention matching config.py / routes:
          +X = FORWARD  (right)    | -X = BACKWARD (left)
          +Y = FORWARD  (backward) | -Y = BACKWARD (forward)
          +Z = BACKWARD (up)       | -Z = FORWARD  (down)
        Returns the actual number of signed steps completed.
        """
        if signed_steps == 0:
            return 0

        axis = axis.lower()
        steps = abs(signed_steps)
        stepper = self.stepper_motors.stepper

        if axis == "x":
            direction_str = "FORWARD" if signed_steps > 0 else "BACKWARD"
            motors = [self.stepper_motors.x_motor] if self.stepper_motors.x_motor else []
            limit_key = "lr"
        elif axis == "y":
            direction_str = "FORWARD" if signed_steps > 0 else "BACKWARD"
            motors = [self.stepper_motors.y_motor] if self.stepper_motors.y_motor else []
            limit_key = "ud"
        elif axis == "z":
            # In hardware/stepper_motors.py: move_up uses BACKWARD, move_down uses FORWARD
            direction_str = "BACKWARD" if signed_steps > 0 else "FORWARD"
            kit1 = self.stepper_motors.kit1
            motors = [kit1.stepper1, kit1.stepper2] if kit1 else []
            limit_key = None
        else:
            raise ValueError(f"Unknown axis: {axis}")

        sign = 1 if signed_steps > 0 else -1
        completed = 0

        if not motors or stepper is None:
            # Simulated coordinate update even if motor HAT isn't attached
            self.pos[axis] += signed_steps
            print(f"  [SIM/NO-HAT] {axis.upper()} {'+' if sign > 0 else ''}{signed_steps} -> {self.pos[axis]}")
            return signed_steps

        resolved_dir = self.stepper_motors.resolve_stepper_direction(direction_str)
        try:
            for _ in range(steps):
                if check_limits and limit_key is not None:
                    switches = self.read_limit_switches()
                    if switches[limit_key] == self.limit_triggered_value[limit_key]:
                        print(f"  [LIMIT] {limit_key.upper()} switch triggered after {completed} steps!")
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

        return completed * sign

    def home_xy(self, x_dir_sign: int = 1, y_dir_sign: int = -1, max_steps: int = 12000) -> None:
        """
        Home X and Y axes toward their limit switches.
        Default directions match archive/resetXYPlatform.py:
          Y: BACKWARD (-1), X: FORWARD (+1)
        """
        print("\n" + "─" * 58)
        print(f"  HOMING XY STAGE (max_steps={max_steps} per axis)")
        print(
            f"  Stop condition: LR (GPIO 17) == {self.limit_triggered_value['lr']}, "
            f"UD (GPIO 27) == {self.limit_triggered_value['ud']}"
        )
        print("  Press Ctrl+C at any time to abort immediately.")
        print("─" * 58)
        try:
            print(f"  1/2 Homing Y axis (sign={y_dir_sign:+d})...")
            y_moved = self.move_axis("y", y_dir_sign * max_steps, check_limits=True)
            print(f"      Y moved {y_moved} steps.")

            print(f"  2/2 Homing X axis (sign={x_dir_sign:+d})...")
            x_moved = self.move_axis("x", x_dir_sign * max_steps, check_limits=True)
            print(f"      X moved {x_moved} steps.")

            self.pos["x"] = 0
            self.pos["y"] = 0
            print("  ✓ Homing complete — set origin (X=0, Y=0).")
        except KeyboardInterrupt:
            self.stepper_motors.release_all()
            print("\n  ⚠ Homing aborted by user! Coils released.")

    # ── Z-Axis Focus Sweep ────────────────────────────────────
    def run_z_sweep(
        self,
        half_range_steps: int = 150,
        step_interval: int = 25,
        settle_sec: float = 0.3,
        save_images: bool = True,
        move_to_best: bool = True,
    ) -> dict:
        """
        Sweep Z from (current_z - half_range_steps) to (current_z + half_range_steps),
        computing Laplacian variance sharpness at each plane.
        """
        start_z = self.pos["z"]
        offsets = list(range(-half_range_steps, half_range_steps + 1, step_interval))
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

        print("\n" + "─" * 62)
        print(
            f"  Z-FOCUS SWEEP: {offsets[0]:+d} to {offsets[-1]:+d} (step={step_interval}) "
            f"around Z={start_z}"
        )
        print("─" * 62)

        # Ensure LED is on
        was_led_on = self.gpio_control.get_led_state()
        if not was_led_on:
            self.gpio_control.set_led(True)
            time.sleep(0.5)

        results = []
        # Move to starting offset
        self.move_axis("z", offsets[0])

        for i, offset in enumerate(offsets):
            if i > 0:
                delta = offsets[i] - offsets[i - 1]
                self.move_axis("z", delta)
            time.sleep(settle_sec)

            frame = self.grab_frame()
            metrics = self.compute_frame_metrics(frame)
            z_coord = self.pos["z"]

            img_path = None
            if save_images and frame is not None:
                fname = f"zsweep_{stamp}_z{z_coord:+05d}_sharp{metrics['sharpness']:.1f}.jpg"
                img_path = str(self.calib_img_dir / fname)
                self.cv2.imwrite(img_path, frame)

            entry = {
                "offset": offset,
                "z": z_coord,
                "sharpness": metrics["sharpness"],
                "brightness": metrics["brightness"],
                "contrast": metrics["contrast"],
                "image": img_path,
            }
            results.append(entry)
            bar = "█" * min(30, int(metrics["sharpness"] / 10.0))
            print(
                f"  Z={z_coord:+5d} (offset {offset:+4d}) | "
                f"Sharpness={metrics['sharpness']:8.2f} | "
                f"Bright={metrics['brightness']:6.1f}  {bar}"
            )

        best = max(results, key=lambda r: r["sharpness"]) if results else None
        if best and move_to_best:
            return_delta = best["z"] - self.pos["z"]
            self.move_axis("z", return_delta)
            print(f"\n  ✓ Best focus at Z={best['z']:+d} (Sharpness={best['sharpness']:.2f}) — stage moved to peak.")
        else:
            return_delta = start_z - self.pos["z"]
            self.move_axis("z", return_delta)
            print(f"\n  ✓ Returned to starting Z={start_z:+d}.")

        sweep_record = {
            "timestamp": stamp,
            "xy_position": {"x": self.pos["x"], "y": self.pos["y"]},
            "start_z": start_z,
            "best_z": best["z"] if best else start_z,
            "best_sharpness": best["sharpness"] if best else 0.0,
            "samples": results,
        }
        self.profile["z_sweeps"].append(sweep_record)
        return sweep_record

    # ── LED & Stage Settling Time Test ────────────────────────
    def run_settling_test(self, mode: str = "led", duration_sec: float = 3.0, interval_sec: float = 0.1) -> dict:
        """
        Measure how fast brightness and frame-to-frame motion stabilize after:
          - mode='led'  : turning LED from OFF -> ON
          - mode='move' : stepping X +200 and -200 steps
        """
        print("\n" + "─" * 62)
        print(f"  SETTLING TEST (mode={mode.upper()}, duration={duration_sec:.1f}s, dt={interval_sec*1000:.0f}ms)")
        print("─" * 62)

        if mode == "led":
            self.gpio_control.set_led(False)
            time.sleep(0.8)
            self.gpio_control.set_led(True)
        else:
            self.gpio_control.set_led(True)
            time.sleep(0.3)
            self.move_axis("x", 200)
            self.move_axis("x", -200)

        t0 = time.time()
        prev_gray = None
        samples = []

        while time.time() - t0 <= duration_sec:
            elapsed_ms = int((time.time() - t0) * 1000)
            frame = self.grab_frame()
            if frame is not None:
                gray = self.cv2.cvtColor(frame, self.cv2.COLOR_BGR2GRAY)
                metrics = self.compute_frame_metrics(frame)
                frame_diff = (
                    float(self.np.mean(self.np.abs(gray.astype(self.np.float32) - prev_gray.astype(self.np.float32))))
                    if prev_gray is not None
                    else 0.0
                )
                prev_gray = gray
            else:
                metrics = {"sharpness": 0.0, "brightness": 0.0}
                frame_diff = 0.0

            sample = {
                "t_ms": elapsed_ms,
                "brightness": metrics["brightness"],
                "sharpness": metrics["sharpness"],
                "frame_diff": round(frame_diff, 3),
            }
            samples.append(sample)
            print(
                f"  t={elapsed_ms:4d} ms | Brightness={sample['brightness']:6.1f} | "
                f"Sharpness={sample['sharpness']:8.2f} | FrameDiff={sample['frame_diff']:6.3f}"
            )
            time.sleep(interval_sec)

        record = {
            "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
            "mode": mode,
            "samples": samples,
        }
        self.profile["settling_tests"].append(record)
        return record

    # ── Bookmarking Waypoints ─────────────────────────────────
    def bookmark_waypoint(self, name: str, note: str = "") -> None:
        frame = self.grab_frame()
        metrics = self.compute_frame_metrics(frame)
        self.profile["waypoints"][name] = {
            "x": self.pos["x"],
            "y": self.pos["y"],
            "z": self.pos["z"],
            "sharpness": metrics["sharpness"],
            "brightness": metrics["brightness"],
            "note": note,
            "recorded_at": datetime.datetime.now().isoformat(timespec="seconds"),
        }
        print(
            f"  ✓ Bookmarked '{name}' -> (X={self.pos['x']}, Y={self.pos['y']}, Z={self.pos['z']}) "
            f"[Sharpness={metrics['sharpness']:.1f}]"
        )

    # ── Status Banner & Interactive Loop ──────────────────────
    def print_status(self) -> None:
        switches = self.read_limit_switches()
        led = "ON" if self.gpio_control.get_led_state() else "OFF"
        frame = self.grab_frame()
        metrics = self.compute_frame_metrics(frame)
        cam_status = (
            f"Sharpness={metrics['sharpness']:.1f}, Bright={metrics['brightness']:.1f}"
            if frame is not None
            else "No camera frame"
        )

        print("\n" + "═" * 68)
        print(
            f"  POS: (X={self.pos['x']:+6d}, Y={self.pos['y']:+6d}, Z={self.pos['z']:+6d})  |  "
            f"JOG: XY={self.jog_steps['xy']}  Z={self.jog_steps['z']}"
        )
        print(
            f"  LIMITS: LR(17)={switches['lr']} (trig={self.limit_triggered_value['lr']}) "
            f"UD(27)={switches['ud']} (trig={self.limit_triggered_value['ud']}) [Pull={self.pull_mode}]  |  LED={led}"
        )
        print(f"  CAMERA: {cam_status}  |  Waypoints saved: {len(self.profile['waypoints'])}")
        print("═" * 68)

    def print_help(self) -> None:
        print(
            """
  COMMANDS:
    w / s       : Jog Y Forward (-steps) / Backward (+steps)
    a / d       : Jog X Left (-steps)    / Right (+steps)
    u / j       : Jog Z Up (+steps)      / Down (-steps)
    step <xy> [z]: Set jog step size (e.g., `step 500 25` or `step 4000`)
    goto <x> <y> [z]: Move directly to target coordinate (e.g., `goto 0 0`)
    zero        : Reset current (X, Y, Z) counter to (0, 0, 0)
    led         : Toggle illumination LED (GPIO 18)
    l           : Live-monitor limit switches (10s) while you press them by hand
    pull <mode> : Set GPIO internal pull resistor: `pull up`, `pull down`, or `pull none`
    trig <lr> <ud>: Set limit switch triggered values (e.g., `trig 0 0` or `trig 1 1`)
    h           : Run safe XY homing routine toward limit switches
    b [name]    : Bookmark current (X, Y, Z) waypoint (lists presets if no name given)
    list        : Show all bookmarked waypoints & calculated deltas
    z [range] [step]: Run Z-axis autofocus sharpness sweep (default: range=150, step=25)
    t [led|move]: Run 3-second exposure / vibration settling timer test
    snap [label]: Save a snapshot image with sharpness/coordinate overlay to `images/calibration/`
    save        : Save all measurements to `calibration_profile.json`
    q           : Save and quit
"""
        )

    def show_waypoints(self) -> None:
        wps = self.profile.get("waypoints", {})
        if not wps:
            print("  (No waypoints recorded yet. Use `b <name>` to bookmark current position.)")
            return
        print("\n  BOOKMARKED WAYPOINTS:")
        print("  " + "─" * 62)
        for name, data in wps.items():
            print(
                f"  {name:<22} : X={data['x']:+6d}, Y={data['y']:+6d}, Z={data['z']:+6d} "
                f"(Sharp={data.get('sharpness', 0):.1f})"
            )
        print("  " + "─" * 62)

    def save_snapshot(self, label: str = "snap") -> None:
        frame = self.grab_frame()
        if frame is None:
            print("  ✗ Could not grab camera frame.")
            return
        metrics = self.compute_frame_metrics(frame)
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        fname = f"{label}_x{self.pos['x']:+d}_y{self.pos['y']:+d}_z{self.pos['z']:+d}_{stamp}.jpg"
        out_path = self.calib_img_dir / fname
        self.cv2.imwrite(str(out_path), frame)
        print(f"  ✓ Saved {out_path} (Sharpness={metrics['sharpness']:.2f}, Brightness={metrics['brightness']:.1f})")

    def interactive_loop(self) -> None:
        self.print_help()
        while True:
            self.print_status()
            try:
                raw = input("calib> ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nExiting...")
                break

            if not raw:
                continue
            parts = raw.split()
            cmd = parts[0].lower()

            if cmd in ("q", "quit", "exit"):
                self.save_profile()
                self.stepper_motors.release_all()
                break
            elif cmd in ("?", "help"):
                self.print_help()
            elif cmd == "w":
                self.move_axis("y", -self.jog_steps["xy"])
            elif cmd == "s":
                self.move_axis("y", self.jog_steps["xy"])
            elif cmd == "a":
                self.move_axis("x", -self.jog_steps["xy"])
            elif cmd == "d":
                self.move_axis("x", self.jog_steps["xy"])
            elif cmd == "u":
                self.move_axis("z", self.jog_steps["z"])
            elif cmd == "j":
                self.move_axis("z", -self.jog_steps["z"])
            elif cmd == "step":
                if len(parts) >= 2:
                    self.jog_steps["xy"] = abs(int(parts[1]))
                if len(parts) >= 3:
                    self.jog_steps["z"] = abs(int(parts[2]))
                print(f"  ✓ Jog steps set to XY={self.jog_steps['xy']}, Z={self.jog_steps['z']}")
            elif cmd == "goto":
                if len(parts) < 3:
                    print("  Usage: goto <x> <y> [z]")
                    continue
                tx, ty = int(parts[1]), int(parts[2])
                tz = int(parts[3]) if len(parts) >= 4 else self.pos["z"]
                self.move_axis("x", tx - self.pos["x"])
                self.move_axis("y", ty - self.pos["y"])
                self.move_axis("z", tz - self.pos["z"])
            elif cmd == "zero":
                self.pos = {"x": 0, "y": 0, "z": 0}
                print("  ✓ Origin reset to (X=0, Y=0, Z=0)")
            elif cmd == "led":
                new_state = self.gpio_control.toggle_led()
                print(f"  ✓ LED is now {'ON' if new_state else 'OFF'}")
            elif cmd == "l":
                dur = float(parts[1]) if len(parts) >= 2 else 10.0
                self.inspect_limit_switches(dur)
            elif cmd == "pull":
                mode = parts[1] if len(parts) >= 2 else "UP"
                self.configure_gpio_pull(mode)
            elif cmd == "trig":
                if len(parts) < 3:
                    print("  Usage: trig <lr_val: 0|1> <ud_val: 0|1>")
                    continue
                self.limit_triggered_value["lr"] = int(parts[1])
                self.limit_triggered_value["ud"] = int(parts[2])
                print(f"  ✓ Limit trigger values set: LR={self.limit_triggered_value['lr']}, UD={self.limit_triggered_value['ud']}")
            elif cmd == "h":
                self.home_xy()
            elif cmd == "b":
                if len(parts) >= 2:
                    name = parts[1]
                    note = " ".join(parts[2:]) if len(parts) > 2 else ""
                    self.bookmark_waypoint(name, note)
                else:
                    print("  Preset names:")
                    for idx, preset in enumerate(self.WELL_PRESETS, 1):
                        print(f"    {idx:2d}. {preset}")
                    choice = input("  Enter preset number or custom waypoint name: ").strip()
                    if choice.isdigit() and 1 <= int(choice) <= len(self.WELL_PRESETS):
                        name = self.WELL_PRESETS[int(choice) - 1]
                    else:
                        name = choice
                    if name:
                        self.bookmark_waypoint(name)
            elif cmd == "list":
                self.show_waypoints()
            elif cmd == "z":
                rng = int(parts[1]) if len(parts) >= 2 else 150
                stp = int(parts[2]) if len(parts) >= 3 else 25
                self.run_z_sweep(half_range_steps=rng, step_interval=stp)
            elif cmd == "t":
                mode = parts[1].lower() if len(parts) >= 2 else "led"
                self.run_settling_test(mode=mode)
            elif cmd == "snap":
                lbl = parts[1] if len(parts) >= 2 else "snap"
                self.save_snapshot(lbl)
            elif cmd == "save":
                self.save_profile()
            else:
                print(f"  Unknown command '{cmd}'. Type 'help' for options.")


def run_self_test(calibrator: StageCalibrator) -> None:
    """Automated non-interactive verification for `--sim --self-test`."""
    print("[SELF-TEST] Starting StageCalibrator verification...")
    calibrator.configure_gpio_pull("UP")
    switches = calibrator.read_limit_switches()
    assert "lr" in switches and "ud" in switches

    calibrator.move_axis("x", 500)
    calibrator.move_axis("y", -300)
    calibrator.move_axis("z", 50)
    assert calibrator.pos == {"x": 500, "y": -300, "z": 50}

    calibrator.bookmark_waypoint("bottom_right", note="self-test")
    assert "bottom_right" in calibrator.profile["waypoints"]

    sweep = calibrator.run_z_sweep(half_range_steps=50, step_interval=25, settle_sec=0.05)
    assert len(sweep["samples"]) == 5

    settle = calibrator.run_settling_test(mode="led", duration_sec=0.25, interval_sec=0.1)
    assert len(settle["samples"]) >= 2

    calibrator.save_profile()
    assert calibrator.profile_path.exists()
    print("[SELF-TEST] ✓ All checks passed!")


def main() -> None:
    parser = argparse.ArgumentParser(description="Interactive XYZ Stage & Camera Calibration CLI")
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
        "--profile",
        default=None,
        help="Path to calibration JSON output file (default: calibration_profile.json)",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Run automated self-test and exit",
    )
    args = parser.parse_args()

    _configure_paths(args.sim)
    profile_path = Path(args.profile) if args.profile else None
    calibrator = StageCalibrator(server_url=args.server_url, profile_path=profile_path)

    if args.self_test:
        run_self_test(calibrator)
    else:
        calibrator.interactive_loop()


if __name__ == "__main__":
    main()
