# FORVIZ: AI Face-Tracking Robot with Expressive Animated Eyes

An ultra-lightweight, real-time face-tracking robot built for the **Raspberry Pi 4 Model B (2 GB)**, featuring a **Pan/Tilt 2-axis servo head** and **dual 0.96" SSD1306 I2C OLED screens** for expressive, dynamic robotic eyes.

The robot stays stationary, tracks your face as you move around the room, locks onto you with cute animated happy eyes (`^ ^`), and scans the room when searching.

---

## Hardware Bill of Materials (BOM)

| Component | Quantity | Role |
| :--- | :--- | :--- |
| **Raspberry Pi 4 Model B** (2 GB) | 1 | Main Controller & AI Inference |
| **Raspberry Pi Camera Rev 1.3** | 1 | 5MP CSI Video Stream |
| **SG90 9g Micro Servos** | 2 | Pan (Horizontal) & Tilt (Vertical) Gimbal |
| **0.96" 128x64 SSD1306 I2C OLED** | 2 | Dual Animated Expressive Eyes |
| **External 5V 2A-3A Power Supply / UBEC** | 1 (Recommended) | Power for servos (prevents Pi brownouts) |

---

## GPIO Pinout & Wiring Guide

### 1. Servos (2x SG90)
> [!IMPORTANT]
> **Power Tip**: SG90 servos can draw peak currents up to 600mA each when moving. While testing without load can be done from the Pi's 5V pins, connecting servos to an **external 5V supply** (with Pi GND and external GND tied together) is strongly recommended for smooth, reboot-free operation.

| Servo | Wire Color | Connects to Raspberry Pi Pin | Description |
| :--- | :--- | :--- | :--- |
| **Pan (Horizontal)** | Orange / Yellow (Signal) | **GPIO 12** (Physical Pin 32) | Hardware-timed PWM |
| | Red (VCC) | **5V** (External 5V or Pin 2/4) | Servo Power |
| | Brown / Black (GND) | **GND** (Physical Pin 6 or 14) | Common Ground |
| **Tilt (Vertical)** | Orange / Yellow (Signal) | **GPIO 19** (Physical Pin 35) | Hardware-timed PWM |
| | Red (VCC) | **5V** (External 5V or Pin 2/4) | Servo Power |
| | Brown / Black (GND) | **GND** (Physical Pin 6 or 14) | Common Ground |

---

### 2. OLED Displays (2x 0.96" SSD1306)

You can run **1 display** (dual eyes rendered side-by-side) or **2 displays** (one giant eye per screen).

#### Option A: Zero-Soldering Dual I2C (Recommended!)
Connect Display 1 to the default hardware I2C bus (`i2c-1`) and Display 2 to software I2C (`i2c-3`).

- **Display 1 (Left Eye - Hardware I2C)**:
  - `VCC` -> **3.3V** (Physical Pin 1)
  - `GND` -> **GND** (Physical Pin 9)
  - `SDA` -> **GPIO 2** (Physical Pin 3 - SDA1)
  - `SCL` -> **GPIO 3** (Physical Pin 5 - SCL1)

- **Display 2 (Right Eye - Software I2C)**:
  - `VCC` -> **3.3V** (Physical Pin 17)
  - `GND` -> **GND** (Physical Pin 25)
  - `SDA` -> **GPIO 23** (Physical Pin 16)
  - `SCL` -> **GPIO 24** (Physical Pin 18)

*(To enable software I2C on GPIO 23/24, add `dtoverlay=i2c-gpio,bus=3,i2c_gpio_sda=23,i2c_gpio_scl=24` to `/boot/firmware/config.txt` and reboot).*

#### Option B: Address Resistor Modification
If you prefer sharing SDA & SCL on the same bus:
- Leave Display 1 at address `0x3C`.
- On Display 2, desolder the 0-ohm jumper resistor on the back and move it from `0x78` to `0x7A` (address becomes `0x3D`). Both screens can now share GPIO 2 (SDA) and GPIO 3 (SCL).

---

## Project Structure

```text
FORVIZ/
├── pi_tracker.py             # Main robot coordinator (Camera + YuNet AI + Servos + OLED)
├── servos.py                 # Pan/Tilt controller with smooth proportional tracking & auto-scan
├── oled_face.py              # Procedural expressive eyes animation engine (async/threaded)
├── test_servos.py            # Interactive servo calibration & angle testing tool
├── test_oled.py              # OLED eyes preview & expression demo
├── setup_pi.sh               # 1-click Raspberry Pi OS package installer
├── test_vision.py            # PC test harness with simulated HUD
├── face_detection_yunet_*.onnx # Ultra-lightweight (232 KB) YuNet model
├── requirements.txt
└── README.md
```

---

## Step-by-Step Setup on Raspberry Pi

### Step 1: Install Dependencies
```bash
git pull   # or transfer updated files to your Pi
chmod +x setup_pi.sh
./setup_pi.sh
```

### Step 2: Test & Calibrate Servos
Mount your servo horns in the neutral 90° center position:
```bash
python3 test_servos.py
```
This centers both servos, tests range of motion (Pan 0°-180°, Tilt 50°-130°), and runs a 5-second simulated room sweep.

### Step 3: Test OLED Expressions
```bash
# Single OLED test:
python3 test_oled.py

# Dual OLED test:
python3 test_oled.py --dual
```
Cycles through neutral blinking, looking left/right/up, happy locked crescents (`^ ^`), and heart eyes (`<3 <3`).

### Step 4: Run the Complete Autonomous Robot!
```bash
python3 pi_tracker.py
```

#### Optional Flags:
- `--no-servo`: Runs vision and OLED without moving physical servos.
- `--no-oled`: Runs vision and servos without OLED screens.
- `--dual-oled`: Enables dual-screen eye rendering.
- `--pan-pin 12 --tilt-pin 19`: Custom GPIO pins for servos.

---

## Eye Expressions & Behavior Matrix

| Tracking State | Physical Servo Action | OLED Eyes Emotion |
| :--- | :--- | :--- |
| **`SCANNING`** | Smooth horizontal sweep search | Curious eyes looking left/right and blinking |
| **`TRACKING`** | Moves Pan & Tilt to center target | Pupils dynamically gaze toward your face coordinates |
| **`LOCKED`** | Holds position steadily | Cute happy arcs (`^ ^`) with pink blush lines |
| **`FACE GONE`** | Pauses 1.5s then resumes sweep | Eyes open wide questioning before scanning |


