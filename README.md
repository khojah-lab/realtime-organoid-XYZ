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

## 📋 TODO & Documentation Links

The following guides and SOPs will be linked below for lab onboarding and knowledge transfer:

- [ ] **TODO**: Link to Web Dashboard UI & Automated Scan SOP
- [ ] **TODO**: Link to Hardware Pinout & Motor HAT Schematic (Adafruit MotorHAT 0x60 / GPIO limit switches)
- [ ] **TODO**: Link to Cloud Upload & Data Storage Guide (OpenStack / Swift sync)
- [ ] **TODO**: Link to Device Troubleshooting & FAQ Guide

---

## ⚙️ System Capabilities

MOST OF THIS DOES NOT WORK THIS WAS WHAT WAS INTENDED WE NEED TO REFACTOR THE CODE SIGNIFICANTLY

### 🎥 1. Real-Time Remote Microscopy
- **Live Video Streaming**: Real-time preview powered by `Picamera2` (1024x1024 stream) delivered over WebSockets via SocketIO.
- **Illumination Control**: Remote toggleable LED system (GPIO 18) for sample illumination.

### 🕹️ 2. Precision 3-Axis (XYZ) Motion Control
- **Stepper Motor Stage**: Multi-axis positioning (X, Y, Z) powered by Adafruit MotorHATs.
- **Variable Fine/Coarse Control**: UI directional arrow pad and step sliders for micrometer-level adjustments.
- **Safety Endstop Limit Switches**: Hardware limit switches (GPIO 17 & 27) prevent over-travel and assist homing.

### 🌀 3. Suspended DC Shaker Motor Control
- **Agitation & Mixing**: Independent DC motor channels (`dc_motor_control.py`) to shake or agitate culture wells.
- **Speed & State Management**: Individual and global motor speed/state toggles via the web dashboard.

### 🔬 4. Automated Multi-Well Plate Scanning & Autofocus
- **6-Well Plate Scanning**: Automated grid movement across 6-well plates to capture centered images of every well.
- **Scheduled Automated Scans**: Recurring interval-based automated scans for long-term organoid growth monitoring.
- **Autofocus & Z-Adjustment**: Programmatic focal plane adjustments for crisp imaging.

### 🧠 5. Real-Time Organoid Detection & Analysis
- **AI/ML Organoid Segmentation**: Integrated YOLO / OpenCV object detection routines (`organoid_detection_script.py`) to locate and count organoids.
- **Image History & Download**: Browse and download historical experiment captures directly from the web interface.

### ☁️ 6. Cloud Backup & Reproducible Action Logging
- **Automated Cloud Sync**: Background threads (`image_upload_script.py`) zip and sync image datasets to OpenStack / Swift object storage.
- **Audit Trail (`actions.csv`)**: Timestamped event log tracking every motor move, scan, and user action to ensure high scientific reproducibility.

---

