# FORVIZ: 360° AI Face Tracking Robot

An ultra-lightweight, real-time 360° face-tracking system tailored for the **Raspberry Pi 4 Model B (2 GB)** and **Raspberry Pi Camera Rev 1.3 (OV5647)**.

Designed for a stationary rotating robot/turret that smoothly turns to follow a person across a room without running heavy or unnecessary object detection pipelines.

---

## Architecture Overview

- **Embedded Hardware**: Raspberry Pi 4 Model B (2 GB RAM), 64-bit Raspberry Pi OS.
- **Vision Sensor**: Raspberry Pi Camera Module Rev 1.3 (CSI Ribbon cable).
- **Inference Engine**: OpenCV DNN with **YuNet Face Detector** (232 KB ONNX model).
  - Uses only ~40–60 MB RAM total.
  - Reaches **15–25 FPS** directly on the Pi 4 CPU cores (no TPU or extra accelerator needed).
- **Kinematics**: Pure horizontal yaw angle calculation with proportional angular velocity (20% – 100% PWM).
- **Target Lost Recovery**: Continuous 360° sweep scan until human face is re-acquired.

---

## Project Structure

```text
FORVIZ/
├── pi_tracker.py             # Optimized Raspberry Pi tracking script (Picamera2 + YuNet)
├── setup_pi.sh               # 1-click dependency installer for Raspberry Pi OS
├── test_vision.py            # PC test harness with simulated HUD and webcam support
├── run_pc_test.bat           # 1-click Windows launcher for PC testing
├── face_detection_yunet_*.onnx # (Auto-downloaded) 232 KB face detection weights
├── .gitignore                # Excludes heavy weights, caches, and test artifacts
└── README.md
```

---

## Quickstart

### 1. Test on PC (Windows / Linux / macOS)
To test the tracking logic and view the simulated robot HUD on your PC webcam:

```bash
python test_vision.py
```
*(On Windows, you can simply double-click `run_pc_test.bat`)*

**Controls**:
- `m`: Switch between Face Tracking (YuNet) and Object Detection (YOLO)
- `c`: Toggle HUD overlay
- `s`: Save snapshot image
- `q` / `ESC`: Exit

---

### 2. Deploy to Raspberry Pi 4

#### A. Hardware Connection
Connect your **Raspberry Pi Camera Rev 1.3** to the CSI port:
- Silver contacts facing the micro-HDMI ports.
- Blue backing facing the USB/Ethernet jacks.

#### B. Setup on Pi
Copy `pi_tracker.py` and `setup_pi.sh` to your Raspberry Pi, then run:

```bash
chmod +x setup_pi.sh
./setup_pi.sh
```

#### C. Run the Tracker
```bash
python3 pi_tracker.py
```

- **Connected to a screen**: Displays live video feed with bounding boxes, facial landmarks, and yaw error telemetry.
- **Running over SSH (Headless)**: Automatically logs real-time tracking direction, power percentage, and yaw angle to your terminal.

---

## Telemetry States

| State | Condition | Action |
| :--- | :--- | :--- |
| `LOCKED` | Face is within center deadband | 0% Power (Stand still, hold position) |
| `ROTATE_CCW` | Face is to the left | Rotate Counter-Clockwise (proportional speed) |
| `ROTATE_CW` | Face is to the right | Rotate Clockwise (proportional speed) |
| `SCAN_360` | No face detected | Gentle 360° sweep rotation to locate human |
