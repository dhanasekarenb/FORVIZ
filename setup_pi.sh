#!/usr/bin/env bash
# Automated Setup Script for Raspberry Pi 4 (2GB) 64-bit OS
set -e

echo "=========================================================="
echo " Setting up AI Face Tracker for Raspberry Pi 4"
echo "=========================================================="

echo "[1/4] Updating system packages..."
sudo apt update
sudo apt install -y python3-pip python3-numpy python3-opencv python3-picamera2 libcamera-tools

echo "[2/4] Verifying Camera Connection..."
if command -v rpicam-hello &> /dev/null; then
    echo "Found rpicam-hello tool."
elif command -v libcamera-hello &> /dev/null; then
    echo "Found libcamera-hello tool."
fi

echo "[3/4] Checking YuNet model file..."
if [ ! -f "face_detection_yunet_2023mar.onnx" ]; then
    echo "Downloading YuNet ONNX model (232 KB)..."
    wget -q https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx
    echo "Downloaded face_detection_yunet_2023mar.onnx successfully."
else
    echo "Model file already present."
fi

echo "[4/4] Testing camera detection..."
libcamera-hello --list-cameras 2>/dev/null || rpicam-hello --list-cameras 2>/dev/null || true

echo "=========================================================="
echo " Setup complete! Run the tracker with:"
echo "   python3 pi_tracker.py"
echo "=========================================================="
