# XYZ Organoid Remote Imaging Device

This repository contains the software for controlling the **XYZ Organoid Imaging System**, a custom remote microscopy platform built with Raspberry Pi, Python, stepper/DC motors, and a web interface.

Lab drive: https://drive.google.com/drive/folders/1pTi2H-WdkrL60x7fensSTAS5a-E9sUcp?usp=drive_link

lab secrets: https://docs.google.com/spreadsheets/d/1VQD1994L5gKGxoP8PO2QHVpyDeTH2WBEH_3-IMPY0Ls/edit?usp=sharing

^^^ todo: fix authorizations... should probably make it more robust
## 🚀 Quick Start Guide

### 0. Connect to Tailscale
Go to https://tailscale.com/download, and follow the instructions for your respective OS. When prompted to sign in, use the `khojahlab@gmail.com` credentials. Do not use your own credentials on Tailscale. Once you are connected, you should see your device on the admin console.

### 1. SSH into the Raspberry Pi (via Tailscale)
Ensure your computer is connected to the lab's **Tailscale** network, then SSH into the Raspberry Pi:

```bash
ssh khojahlab@100.112.125.34
```

---

### 2. Start the Web Server
To ensure that the server is already started, or if it needs to be started, run this command:

```bash
ss -lptn 'sport = :3000'
```

If there is an entry, the server is up. If there are no entries, the server needs to be started.

---

To start the server, navigate to the project directory, activate the Python virtual environment, and launch the server:

```bash
cd SpringXYZ
source venv/bin/activate
python3 server.py
```

---
Open the site here (your device must be connected to tailscale): http://100.112.125.34:3000/

---

## 📋 TODO & Documentation Links

The following guides and SOPs will be linked below for lab onboarding and knowledge transfer:

- [ ] **TODO**: Link to Web Dashboard UI & Automated Scan SOP
- [ ] **TODO**: Link to Hardware Pinout & Motor HAT Schematic (Adafruit MotorHAT 0x60 / GPIO limit switches)
- [ ] **TODO**: Link to Cloud Upload & Data Storage Guide (OpenStack / Swift sync)
- [ ] **TODO**: Link to Device Troubleshooting & FAQ Guide

---

## 🗂️ Codebase Structure

```text
realtime-organoid-XYZ/
├── server.py                  # Application entrypoint (Flask + SocketIO + background threads)
├── config.py                  # Central paths, GPIO pins, I2C addresses, scan & Swift settings
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
│   └── cloud_storage.py       # OpenStack Swift cloud upload/download & zip bundling
├── routes/                    # Modular Flask route blueprints
│   ├── main_routes.py         # Dashboard UI, MJPEG /video feed, LED toggle, hardware status
│   ├── motion_routes.py       # XYZ stepper movement, DC shaker controls, zoom/focus
│   └── analysis_routes.py     # Manual scan trigger, organoid detection, cloud image retrieval
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
- **Variable Fine/Coarse Control**: UI directional arrow pad and step sliders for micrometer-level adjustments.
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
- **Image History & Download**: Browse and download historical experiment captures directly from the web interface.

### ☁️ 6. Cloud Backup & Reproducible Action Logging
- **Automated Cloud Sync**: Cloud storage utilities (`services/cloud_storage.py`) zip and sync image datasets to OpenStack / Swift object storage.
- **Audit Trail (`logs/actions.csv`)**: Timestamped event log (`services/telemetry.py`) tracking every motor move, scan, and user action to ensure high scientific reproducibility.

---

