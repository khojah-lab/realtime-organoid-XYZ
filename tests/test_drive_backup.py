import contextlib
import importlib.util
from pathlib import Path
import sqlite3
import sys
import tempfile
import types
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from services import drive_backup as drive
from config import CHAMBER_NAMES


class DriveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.images = self.root / "images"
        self.images.mkdir()
        self.state = self.root / "state.sqlite3"

    def image(self, well="top_left"):
        path = self.images / (well + "_20261113_120000.jpg")
        path.write_bytes(b"jpeg")
        return path

    def test_all_wells_and_invalid_names(self):
        for well in CHAMBER_NAMES:
            self.assertEqual(drive.parse_name(well + "_20261113_120000.jpg"), well)
        for name in ["other_20261113_120000.jpg", "top_left_20269999_120000.jpg",
                     ".top_left_20261113_120000.part.jpg", "../top_left_20261113_120000.jpg"]:
            self.assertIsNone(drive.parse_name(name))

    def test_pagination(self):
        api = MagicMock()
        api.files.return_value.list.return_value.execute.side_effect = [
            {"files": [{"id": "1"}], "nextPageToken": "next"}, {"files": [{"id": "2"}]}]
        with patch.object(drive, "get_client", return_value=api):
            self.assertEqual(len(list(drive.list_files("name = 'a'"))), 2)
        self.assertEqual(api.files.return_value.list.call_args.kwargs["pageToken"], "next")

    def test_six_folders_created(self):
        api = MagicMock()
        api.files.return_value.create.return_value.execute.side_effect = [{"id": w} for w in CHAMBER_NAMES]
        with patch.object(drive, "list_files", return_value=[]), patch.object(drive, "get_client", return_value=api):
            self.assertEqual(set(drive.well_folders()), set(CHAMBER_NAMES))
        self.assertEqual(api.files.return_value.create.call_count, 6)

    def test_duplicate_folder_rejected(self):
        with patch.object(drive, "list_files", return_value=[
            {"name": "top_left", "id": "a"}, {"name": "top_left", "id": "b"}]):
            with self.assertRaises(RuntimeError):
                drive.well_folders()

    def test_verified_receipts_survive_restart_and_keep_originals(self):
        for well in CHAMBER_NAMES:
            self.image(well)
        with patch.object(drive, "well_folders", return_value={w: w for w in CHAMBER_NAMES}), \
             patch.object(drive, "upload_one", return_value="file") as upload:
            self.assertEqual(drive.backup_once(self.images, self.state)["uploaded"], 6)
            self.assertEqual(drive.backup_once(self.images, self.state)["skipped"], 6)
            self.assertEqual(upload.call_count, 6)
            self.assertEqual({c.args[1] for c in upload.call_args_list}, set(CHAMBER_NAMES))
        self.assertEqual(len(list(self.images.glob("*.jpg"))), 6)

    def test_network_failure_retries_without_receipt(self):
        path = self.image()
        with patch.object(drive, "well_folders", return_value={"top_left": "well"}), \
             patch.object(drive, "upload_one", side_effect=[OSError("offline"), "id"]):
            self.assertEqual(drive.backup_once(self.images, self.state)["failed"], 1)
            self.assertEqual(drive.backup_once(self.images, self.state)["uploaded"], 1)
        self.assertTrue(path.exists())

    def test_missing_authorization_keeps_original(self):
        path = self.image()
        with patch.object(drive, "well_folders", side_effect=RuntimeError("no token")):
            self.assertEqual(drive.backup_once(self.images, self.state)["failed"], 1)
        self.assertTrue(path.exists())

    def test_upload_verifies_and_closes_media(self):
        path = self.image()
        api = MagicMock()
        api.files.return_value.create.return_value.next_chunk.return_value = (
            None, {"id": "new", "md5Checksum": drive.checksum(path)})
        with patch.object(drive, "list_files", return_value=[]), patch.object(drive, "get_client", return_value=api):
            self.assertEqual(drive.upload_one(path, "well", drive.checksum(path)), "new")
        # Windows permits rename only after the file handle has closed.
        path.rename(path.with_suffix(".verified"))

    def test_checksum_mismatch_rejected(self):
        path = self.image()
        api = MagicMock()
        api.files.return_value.create.return_value.next_chunk.return_value = (
            None, {"id": "new", "md5Checksum": "bad"})
        with patch.object(drive, "list_files", return_value=[]), patch.object(drive, "get_client", return_value=api):
            with self.assertRaises(RuntimeError):
                drive.upload_one(path, "well", drive.checksum(path))

    def test_interrupted_upload_reused_and_conflict_rejected(self):
        path = self.image()
        with patch.object(drive, "list_files", return_value=[{"id": "old", "md5Checksum": drive.checksum(path)}]), \
             patch.object(drive, "get_client") as api:
            self.assertEqual(drive.upload_one(path, "well", drive.checksum(path)), "old")
            api.assert_not_called()
        with patch.object(drive, "list_files", return_value=[{"id": "old", "md5Checksum": "different"}]):
            with self.assertRaises(RuntimeError):
                drive.upload_one(path, "well", drive.checksum(path))

    def test_target_change_does_not_reuse_receipts(self):
        self.image()
        with patch.object(drive, "well_folders", return_value={"top_left": "well"}), \
             patch.object(drive, "upload_one", return_value="id"):
            drive.backup_once(self.images, self.state)
            with patch.object(drive, "DRIVE_FOLDER_ID", "another-target"):
                self.assertEqual(drive.backup_once(self.images, self.state)["uploaded"], 1)

    def test_capture_is_backed_up_when_aws_copy_fails(self):
        import numpy as np
        modules = {
            "hardware.camera": types.SimpleNamespace(capture_fresh_bgr_frame=lambda: np.zeros((8, 8, 3), dtype=np.uint8)),
            "hardware.gpio_control": types.SimpleNamespace(set_led=lambda value: None),
            "hardware.stepper_motors": types.SimpleNamespace(move_platform=lambda *a: None),
            "services.telemetry": types.SimpleNamespace(Timer=lambda *a: contextlib.nullcontext(),
                emit_socket_event=lambda *a: None, log_event=lambda *a: None),
        }
        with patch.dict(sys.modules, modules):
            spec = importlib.util.spec_from_file_location("scanner_test", ROOT / "services/scanner.py")
            scanner = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(scanner)
        with patch.object(scanner, "IMAGE_DIR", self.images), \
             patch.object(scanner, "IMAGES_UPLOAD_DIR", self.root / "aws"), \
             patch.object(scanner.shutil, "copy2", side_effect=OSError("AWS staging failed")):
            scanner.take_scan_photo("top_left")
        self.assertEqual(len(list(self.images.glob("top_left_*.jpg"))), 1)
        with patch.object(drive, "well_folders", return_value={"top_left": "well"}), \
             patch.object(drive, "upload_one", return_value="id"):
            self.assertEqual(drive.backup_once(self.images, self.state)["uploaded"], 1)

    def test_actual_aws_cleanup_cannot_remove_drive_source(self):
        from services import cloud_storage as aws
        path = self.image()
        staging = self.root / "aws"
        staging.mkdir()
        aws_copy = staging / path.name
        aws_copy.write_bytes(path.read_bytes())
        with patch.object(aws, "get_client", return_value=MagicMock()):
            aws.upload_pending_images(str(staging))
        self.assertFalse(aws_copy.exists())
        self.assertTrue(path.exists())
        with patch.object(drive, "well_folders", return_value={"top_left": "well"}), \
             patch.object(drive, "upload_one", return_value="id"):
            self.assertEqual(drive.backup_once(self.images, self.state)["uploaded"], 1)

    def test_disabled_worker_does_not_start(self):
        with patch.object(drive, "DRIVE_BACKUP_ENABLED", False), patch.object(drive.threading, "Thread") as thread:
            drive.start_drive_backup()
            thread.assert_not_called()


if __name__ == "__main__":
    unittest.main()
