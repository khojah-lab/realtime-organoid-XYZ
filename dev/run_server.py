"""Run server.py on a non-Pi machine with fake camera, GPIO and motor hardware.

Usage: python dev/run_server.py
Open http://localhost:3000/
"""
import os
import runpy
import sys
import tempfile

REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

os.environ.setdefault("XYZ_BASE_DIR", os.path.join(tempfile.gettempdir(), "xyz_dev"))
sys.path[:0] = [os.path.join(REPO_DIR, "dev", "fakes"), REPO_DIR]
runpy.run_path(os.path.join(REPO_DIR, "server.py"), run_name="__main__")
