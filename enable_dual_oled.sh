#!/usr/bin/env bash
# Enables Software I2C on GPIO 23 (Pin 16) & GPIO 24 (Pin 18) for OLED Screen 2.
# Includes i2c_gpio_delay_us=5 to stabilize signal timing and eliminate glitching.
set -e

echo "=========================================================="
echo "  ENABLING STABILIZED DUAL OLED SUPPORT (I2C-3 on Pin 16 & 18)"
echo "=========================================================="

echo "[1/3] Removing any previous noisy I2C-3 overlay..."
sudo dtoverlay -r i2c-gpio 2>/dev/null || true

echo "[2/3] Enabling clean, stabilized I2C-3 overlay (100kHz standard mode)..."
sudo dtoverlay i2c-gpio bus=3 i2c_gpio_sda=23 i2c_gpio_scl=24 i2c_gpio_delay_us=5 2>/dev/null || true

CONFIG_FILE="/boot/firmware/config.txt"
if [ ! -f "$CONFIG_FILE" ]; then
    CONFIG_FILE="/boot/config.txt"
fi

# Remove old overlay entry if present
sudo sed -i '/dtoverlay=i2c-gpio/d' "$CONFIG_FILE" 2>/dev/null || true
echo "dtoverlay=i2c-gpio,bus=3,i2c_gpio_sda=23,i2c_gpio_scl=24,i2c_gpio_delay_us=5" | sudo tee -a "$CONFIG_FILE" >/dev/null
echo "Configured persistent 100kHz stabilized overlay in $CONFIG_FILE."

echo "[3/3] Scanning for connected displays..."
echo "--- Screen 1 Bus (I2C-1: SDA=Pin 3, SCL=Pin 5) ---"
sudo i2cdetect -y 1 || true

echo "--- Screen 2 Bus (I2C-3: SDA=Pin 16, SCL=Pin 18) ---"
sudo i2cdetect -y 3 || true

echo "=========================================================="
echo " Done! Run test: python3 test_oled.py --rotate 180"
echo "=========================================================="
