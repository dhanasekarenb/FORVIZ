#!/usr/bin/env bash
# Enables Software I2C on GPIO 23 (Pin 16) & GPIO 24 (Pin 18) for OLED Screen 2.
# 100% Plug-and-play, ZERO soldering required!
set -e

echo "=========================================================="
echo "  ENABLING DUAL OLED SUPPORT (I2C-3 on GPIO 23 & 24)"
echo "=========================================================="

echo "[1/3] Enabling live I2C-3 overlay without rebooting..."
sudo dtoverlay i2c-gpio bus=3 i2c_gpio_sda=23 i2c_gpio_scl=24 2>/dev/null || true

echo "[2/3] Adding persistent overlay to config.txt..."
CONFIG_FILE="/boot/firmware/config.txt"
if [ ! -f "$CONFIG_FILE" ]; then
    CONFIG_FILE="/boot/config.txt"
fi

if ! grep -q "dtoverlay=i2c-gpio,bus=3,i2c_gpio_sda=23,i2c_gpio_scl=24" "$CONFIG_FILE" 2>/dev/null; then
    echo "dtoverlay=i2c-gpio,bus=3,i2c_gpio_sda=23,i2c_gpio_scl=24" | sudo tee -a "$CONFIG_FILE"
    echo "Added persistent entry to $CONFIG_FILE."
else
    echo "Overlay already configured in $CONFIG_FILE."
fi

echo "[3/3] Scanning for connected displays..."
echo "--- Screen 1 Bus (I2C-1: SDA=Pin 3, SCL=Pin 5) ---"
sudo i2cdetect -y 1 || true

echo "--- Screen 2 Bus (I2C-3: SDA=Pin 16, SCL=Pin 18) ---"
sudo i2cdetect -y 3 || true

echo "=========================================================="
echo " Done! You can now run: python3 pi_tracker.py"
echo "=========================================================="
