"""
server.py
────────────────────────────────────────────────────────────────
Application entrypoint for the XYZ Organoid Remote Imaging System.

Architecture overview:
  - config.py         : Paths, GPIO pins, I2C addresses, scan & cloud settings
  - hardware/         : Camera, GPIO (LED & limit switches), Stepper & DC motors
  - services/         : Telemetry, 6-well automated scanner, ML/OpenCV detection, AWS S3 cloud sync
  - routes/           : Flask blueprints for UI, motion control, and analysis/storage
────────────────────────────────────────────────────────────────
"""

import os
from flask import Flask
from flask_socketio import SocketIO

from config import (
    IMAGE_DIR,
    IMAGES_UPLOAD_DIR,
    SECRET_KEY,
    SERVER_HOST,
    SERVER_PORT,
)
from hardware.camera import start_camera_capture_thread
from hardware.gpio_control import cleanup_gpio, init_gpio
from routes import register_routes
from services.detection import start_detection_model_loader
from services.scanner import start_scan_scheduler
from services.telemetry import set_socketio


def check_directories() -> None:
    """Verify that image and temporary directories exist and are writable."""
    dirs_to_check = [str(IMAGE_DIR), str(IMAGES_UPLOAD_DIR), "/tmp"]
    print("\n" + "=" * 50)
    print("DIRECTORY PERMISSIONS CHECK")
    print("=" * 50)
    for d in dirs_to_check:
        try:
            os.makedirs(d, exist_ok=True)
            test_file = os.path.join(d, "test_write.txt")
            with open(test_file, "w") as f:
                f.write("test")
            os.remove(test_file)
            print(f"✓ {d} - EXISTS and WRITABLE")
        except PermissionError:
            print(f"✗ {d} - PERMISSION DENIED (Fix with: sudo chmod 777 {d})")
        except Exception as e:
            print(f"✗ {d} - ERROR: {e}")
    print("=" * 50 + "\n")


def create_app() -> tuple[Flask, SocketIO]:
    """Create and configure the Flask application, Socket.IO server, and background workers."""
    init_gpio()

    app = Flask(__name__, template_folder="templates")
    app.config["SECRET_KEY"] = SECRET_KEY

    socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")
    set_socketio(socketio)

    register_routes(app)

    # Start background daemon services
    start_camera_capture_thread()
    start_scan_scheduler()
    start_detection_model_loader()

    return app, socketio


app, socketio = create_app()


if __name__ == "__main__":
    try:
        print(f"Starting Flask-SocketIO server on {SERVER_HOST}:{SERVER_PORT}...")
        socketio.run(
            app,
            host=SERVER_HOST,
            port=SERVER_PORT,
            debug=False,
            allow_unsafe_werkzeug=True,
        )
    except KeyboardInterrupt:
        print("\nShutting down cleanly...")
    finally:
        cleanup_gpio()
