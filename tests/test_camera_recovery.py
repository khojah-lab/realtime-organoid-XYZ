import sys
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

REPO_DIR = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(REPO_DIR / "dev" / "fakes"), str(REPO_DIR)]

from hardware import camera as cam_mod
from dev.fakes.picamera2 import Picamera2 as FakePicamera2


class _FlakyCamera(FakePicamera2):
    """Fake camera that can be programmed to fail N capture calls."""

    def __init__(self, fail_captures=0):
        super().__init__()
        self.fail_captures = fail_captures
        self.closed = False

    def close(self):
        self.closed = True
        super().close()

    def capture_array(self, name="main", wait=None, signal_function=None, flush=None):
        if self.fail_captures > 0:
            self.fail_captures -= 1
            raise TimeoutError("Simulated Unicam V4L2 frame timeout")
        return super().capture_array(name=name, wait=wait)


class CameraRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.orig_picam2 = cam_mod.picam2
        self.orig_cls = cam_mod._Picamera2_cls
        self.orig_seq = cam_mod._latest_frame_seq
        self.orig_time = cam_mod._latest_frame_time
        self.orig_frame = cam_mod._latest_frame
        self.orig_jpeg = cam_mod._latest_jpeg
        self.orig_failures = cam_mod._consecutive_failures
        self.orig_recoveries = cam_mod._recovery_count
        self.orig_thread_started = cam_mod._capture_thread_started

        cam_mod._consecutive_failures = 0
        cam_mod._recovery_count = 0

    def tearDown(self):
        cam_mod.picam2 = self.orig_picam2
        cam_mod._Picamera2_cls = self.orig_cls
        cam_mod._latest_frame_seq = self.orig_seq
        cam_mod._latest_frame_time = self.orig_time
        cam_mod._latest_frame = self.orig_frame
        cam_mod._latest_jpeg = self.orig_jpeg
        cam_mod._consecutive_failures = self.orig_failures
        cam_mod._recovery_count = self.orig_recoveries
        cam_mod._capture_thread_started = self.orig_thread_started

    def test_single_stream_configuration_omits_unused_lores(self):
        cam = _FlakyCamera()
        cfg = cam_mod._configure_and_start(cam)
        self.assertIn("main", cfg)
        self.assertNotIn("lores", cfg)

    def test_reinit_camera_after_two_consecutive_failures(self):
        wedged = _FlakyCamera(fail_captures=2)
        fresh_instances = []

        def make_fresh_cam():
            c = _FlakyCamera(fail_captures=0)
            fresh_instances.append(c)
            return c

        cam_mod.picam2 = wedged
        cam_mod._Picamera2_cls = make_fresh_cam

        with patch("hardware.camera.time.sleep"):
            self.assertIsNone(cam_mod.capture_bgr_frame())
            self.assertEqual(cam_mod._recovery_count, 0)

            self.assertIsNone(cam_mod.capture_bgr_frame())
            self.assertEqual(cam_mod._recovery_count, 1)
            self.assertTrue(wedged.closed)
            self.assertEqual(len(fresh_instances), 1)
            self.assertIs(cam_mod.picam2, fresh_instances[0])

            # Next capture succeeds on the fresh instance
            frame = cam_mod.capture_bgr_frame()
            self.assertIsNotNone(frame)
            self.assertEqual(frame.shape, (1024, 1024, 3))

    def test_capture_fresh_bgr_frame_reads_from_condition_without_touching_camera(self):
        cam_mod._capture_thread_started = True
        cam_mod._latest_frame = None
        cam_mod._latest_frame_time = 0.0

        def publish_next_frame():
            time.sleep(0.05)
            with cam_mod._frame_cond:
                cam_mod._latest_frame = np.full((1024, 1024, 3), 128, dtype=np.uint8)
                cam_mod._latest_frame_time = time.monotonic()
                cam_mod._latest_frame_seq += 1
                cam_mod._frame_cond.notify_all()

        t = threading.Thread(target=publish_next_frame, daemon=True)
        t.start()
        frame = cam_mod.capture_fresh_bgr_frame(max_age_sec=0.25, wait_timeout_sec=1.0)
        t.join(timeout=1.0)

        self.assertIsNotNone(frame)
        self.assertEqual(frame.shape, (1024, 1024, 3))

    def test_mjpeg_generator_yields_on_new_frame_seq(self):
        with cam_mod._frame_cond:
            cam_mod._latest_jpeg = b"\xff\xd8\xff\xd9"
            cam_mod._latest_frame_seq += 1

        gen = cam_mod.generate_mjpeg_frames()
        chunk = next(gen)
        self.assertIn(b"--frame\r\nContent-Type: image/jpeg\r\n\r\n", chunk)
        gen.close()


if __name__ == "__main__":
    unittest.main()
