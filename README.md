# XYZ Organoid Remote Imaging Device

This repository contains the software for controlling the **XYZ Organoid Imaging System**, a custom remote microscopy platform built with Raspberry Pi, Python, stepper/DC motors, and a web interface.

Lab drive: https://drive.google.com/drive/folders/1pTi2H-WdkrL60x7fensSTAS5a-E9sUcp?usp=drive_link

## 🚀 Quick Start Guide

### 0. Connect to Tailscale
Go to https://tailscale.com/download, and follow the instructions for your respective OS. When prompted to sign in, use the `khojahlab@gmail.com` credentials. Do not use your own credentials on Tailscale. Once you are connected, you should see your device on the admin console.

### 1. SSH into the Raspberry Pi (via Tailscale)
Ensure your computer is connected to the lab's **Tailscale** network, then SSH into the Raspberry Pi:

```bash
ssh khojahlab@khojahlab
```

---

### 2. Start the Web Server
To ensure that the server is already started, or if it needs to be started, run this command:

```bash
ss -lptn 'sport = :3000'
```

If there is an entry, the server is up. If there are no entries, the server needs to be started.

---

> **Note:** You should not normally need to start the server by hand. On the Pi it runs as a systemd service, `/etc/systemd/system/xyz.service`, which starts on boot, restarts on failure, and keeps running after you close your SSH session. Manage it with:
>
> ```bash
> sudo systemctl status xyz     # is it running?
> sudo systemctl restart xyz    # restart after pulling changes
> journalctl -u xyz -f          # live logs
> ```
>
> Only use the manual steps below if the service is stopped or for debugging. Stop the service first (`sudo systemctl stop xyz`) so two servers don't fight over port 3000.

To start the server manually, navigate to the project directory, activate the Python virtual environment, and launch the server:

```bash
cd SpringXYZ
source venv/bin/activate
python3 server.py
```

---
Open the site here (your device must be connected to tailscale): http://100.112.125.34:3000/

---

### 3. Local Development on a Non-Pi Machine (`dev/run_server.py`)
You can run the full web server locally on macOS/Linux without Raspberry Pi hardware using the simulated hardware fakes in `dev/fakes/`:

```bash
python3 dev/run_server.py
```

Then open http://localhost:3000/ in your browser.

---

## 📋 TODO & Documentation Links

The following guides and SOPs will be linked below for lab onboarding and knowledge transfer:

- [ ] **TODO**: Link to Web Dashboard UI & Automated Scan SOP
- [ ] **TODO**: Link to Hardware Pinout & Motor HAT Schematic (Adafruit MotorHAT 0x60 / GPIO limit switches)
- [ ] **TODO**: Link to Cloud Upload & Data Storage Guide (AWS S3 sync)
- [ ] **TODO**: Link to Device Troubleshooting & FAQ Guide

---

## 🗂️ Codebase Structure

```text
realtime-organoid-XYZ/
├── server.py                  # Application entrypoint (Flask + SocketIO + background threads)
├── config.py                  # Central paths, GPIO pins, I2C addresses, scan & S3 settings
├── .env.example               # Template for optional environment variable overrides
├── hardware/                  # Hardware abstraction layer (safe fallbacks on non-Pi hosts)
│   ├── __init__.py            # Hardware connectivity status (get_disconnected_hardware)
│   ├── camera.py              # Picamera2 stream, frame buffer loop, and MJPEG generator
│   ├── gpio_control.py        # LED illumination (GPIO 18) and limit switches (GPIO 17, 27)
│   ├── stepper_motors.py      # Z-axis (0x60) & XY-platform (0x61) stepper motor drivers
│   └── dc_motors.py           # 4-channel DC shaker motor driver (0x63) with auto-stop timers
├── services/                  # Background services & core domain logic
│   ├── telemetry.py           # Action/latency logger (logs/actions.csv + live SocketIO feed)
│   ├── scanner.py             # Automated 6-well plate scan workflow & hourly scheduler
│   ├── detection.py           # TensorFlow SavedModel + OpenCV contour organoid detection
│   └── cloud_storage.py       # AWS S3 client & post-scan background image uploader
├── routes/                    # Modular Flask route blueprints
│   ├── main_routes.py         # Dashboard UI, MJPEG /video feed, LED toggle, hardware status
│   ├── motion_routes.py       # XYZ stepper movement (hold-to-move & scan lock), DC motors, zoom/focus
│   └── analysis_routes.py     # Manual scan trigger, organoid detection, S3 /captures browser & zip download
├── dev/                       # Local non-RPi development tools
│   ├── run_server.py          # Launches server.py with simulated camera, GPIO, and motor HATs
│   ├── seed_images.py         # Generates sample scan images for local testing
│   └── fakes/                 # Mock RPi.GPIO, picamera2, and adafruit_motorkit modules
├── templates/
│   └── main.html              # Web dashboard UI
├── timing_data/               # Telemetry test suite & HTML performance report generators
└── archive/                   # Legacy scripts and historical reference files
```

---

## ⚙️ System Capabilities

### 🎥 1. Real-Time Remote Microscopy
- **Live Video Streaming**: Real-time preview powered by `Picamera2` (`hardware/camera.py`, 1024x1024 stream) delivered via multipart MJPEG (`/video`).
- **Illumination Control**: Remote toggleable LED system (`hardware/gpio_control.py`, GPIO 18) for sample illumination.

### 🕹️ 2. Precision 3-Axis (XYZ) Motion Control
- **Stepper Motor Stage**: Multi-axis positioning (`hardware/stepper_motors.py`, X, Y, Z) powered by Adafruit MotorHATs (`0x60` and `0x61`).
- **Hold-to-Move & Scan Lock**: UI directional arrow pad supports continuous hold-to-move bursts with per-axis locks and prevents accidental stage movement while a 6-well scan is running (`routes/motion_routes.py`).
- **Safety Endstop Limit Switches**: Hardware limit switches (GPIO 17 & 27) prevent over-travel and assist homing.

### 🌀 3. Suspended DC Shaker Motor Control
- **Agitation & Mixing**: Independent DC motor channels (`hardware/dc_motors.py`, `0x63`) to shake or agitate culture wells.
- **Speed & State Management**: Individual and global motor speed/state toggles via the web dashboard.

### 🔬 4. Automated Multi-Well Plate Scanning & Autofocus
- **6-Well Plate Scanning**: Automated grid movement (`services/scanner.py`) across 6-well plates to capture centered images of every well.
- **Scheduled Automated Scans**: Recurring interval-based automated scans for long-term organoid growth monitoring.
- **Autofocus & Z-Adjustment**: Programmatic focal plane adjustments for crisp imaging.

### 🧠 5. Real-Time Organoid Detection & Analysis
- **AI/ML Organoid Segmentation**: Integrated TensorFlow / OpenCV object detection routines (`services/detection.py`) to locate and count organoids.
- **Cloud Image Browser & Download**: Browse dates, scans, thumbnails, and download `.zip` archives directly from AWS S3 (`/captures/*`).

### ☁️ 6. Cloud Backup & Reproducible Action Logging
- **Automated Cloud Sync**: After each scan, `services/cloud_storage.py` uploads new images to the `realtime-organoid-xyz-data` S3 bucket (`us-east-2`) under `YYYY/MM/DD/HH/`, deleting local staging copies once uploaded.
- **Audit Trail (`logs/actions.csv`)**: Timestamped event log (`services/telemetry.py`) tracking every motor move, hold duration, scan, and user action to ensure high scientific reproducibility.

---
