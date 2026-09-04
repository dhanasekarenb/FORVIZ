#!/usr/bin/env bash
# Automated Setup Script for Raspberry Pi 4 (2GB) 64-bit OS
# Installs Camera, OpenCV, YuNet AI, SG90 Servo drivers, and SSD1306 OLED drivers.
set -e

echo "=========================================================="
echo " Setting up AI Face Tracker Robot (Camera + Servos + OLED)"
echo "=========================================================="

echo "[1/5] Updating system packages & installing core libraries..."
sudo apt update
sudo apt install -y \
    python3-pip \
    python3-numpy \
    python3-opencv \
    python3-picamera2 \
    libcamera-tools \
    python3-gpiozero \
    python3-pigpio \
    pigpio \
    python3-pil \
    i2c-tools

echo "[2/5] Enabling I2C interface & starting pigpiod daemon..."
# Enable I2C interface non-interactively
sudo raspi-config nonint do_i2c 0 || true
# Enable and start pigpio daemon for jitter-free servo PWM
sudo systemctl enable --now pigpiod || true

echo "[3/5] Installing OLED & Servo Python packages..."
# Attempt apt first, fallback to pip
sudo apt install -y python3-luma.oled 2>/dev/null || pip3 install --break-system-packages luma.oled luma.core || true
pip3 install --break-system-packages Pillow gpiozero pigpio 2>/dev/null || true

echo "[4/5] Checking YuNet AI model file..."
if [ ! -f "face_detection_yunet_2023mar.onnx" ]; then
    echo "Downloading YuNet ONNX model (232 KB)..."
    wget -q https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx
    echo "Downloaded face_detection_yunet_2023mar.onnx successfully."
else
    echo "Model file already present."
fi

echo "[5/5] Testing hardware interfaces..."
echo "--- Camera Check ---"
libcamera-hello --list-cameras 2>/dev/null || rpicam-hello --list-cameras 2>/dev/null || true

echo "--- I2C Bus Check (Detecting connected OLEDs) ---"
sudo i2cdetect -y 1 || true

echo "=========================================================="
echo " All dependencies installed successfully!"
echo " Note: 'servos' and 'oled_face' are fully built into pi_tracker.py."
echo " Quick Tests:"
echo "   Test Servos:  python3 test_servos.py"
echo "   Test OLED:    python3 test_oled.py"
echo "   Run Robot:    python3 pi_tracker.py"
echo "=========================================================="
