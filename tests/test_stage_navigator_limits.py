import tempfile
import threading
import unittest
from pathlib import Path

from services.stage_navigator import StageNavigator


class TestStageNavigatorLimits(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.state_path = Path(self.tmpdir.name) / "stage_position.json"
        self.nav = StageNavigator(state_path=self.state_path, step_delay=0.0)
        self.nav.set_soft_limits(min_x=-1900, max_x=9400, min_y=-1200, max_y=6500)
        self.cancel = threading.Event()

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_in_bounds_jog_xy_and_z(self):
        pos = self.nav.jog_axis("x", -500, self.cancel)
        self.assertEqual(pos["x"], -500)
        pos = self.nav.jog_axis("y", 300, self.cancel)
        self.assertEqual(pos["y"], 300)
        pos = self.nav.jog_axis("z", -5000, self.cancel)
        self.assertEqual(pos["z"], -5000)

    def test_jog_clamps_at_min_and_max_limits(self):
        self.nav.move_to(-1850, 6450)
        pos = self.nav.jog_axis("x", -100, self.cancel)
        self.assertEqual(pos["x"], -1900)

        # Further outward movement at the limit is blocked
        pos = self.nav.jog_axis("x", -100, self.cancel)
        self.assertEqual(pos["x"], -1900)

        pos = self.nav.jog_axis("y", 100, self.cancel)
        self.assertEqual(pos["y"], 6500)

        pos = self.nav.jog_axis("y", 100, self.cancel)
        self.assertEqual(pos["y"], 6500)

    def test_out_of_bounds_state_blocks_outward_and_allows_inward_recovery(self):
        # Simulate starting already out of bounds (e.g. X = -2100 when min_x = -1900)
        self.nav.pos["x"] = -2100
        self.nav.save_state()

        # Moving further negative (-X) must be blocked (0 steps)
        pos = self.nav.jog_axis("x", -50, self.cancel)
        self.assertEqual(pos["x"], -2100)

        # Moving positive (+X) back toward the valid range must step normally without jumping
        pos = self.nav.jog_axis("x", 50, self.cancel)
        self.assertEqual(pos["x"], -2050)


if __name__ == "__main__":
    unittest.main()
