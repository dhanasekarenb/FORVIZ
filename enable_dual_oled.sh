#!/usr/bin/env bash
# Enables Software I2C on GPIO 23 (Pin 16) & GPIO 24 (Pin 18) for OLED Screen 2.
# Sets internal pull-ups and i2c_gpio_delay_us=10 to eliminate glitching.
set -e

echo "=========================================================="
echo "  ENABLING STABILIZED DUAL OLED SUPPORT (I2C-3 on Pin 16 & 18)"
echo "=========================================================="

echo "[1/4] Enabling internal pull-ups on GPIO 23 & 24..."
sudo pinctrl set 23,24 pu 2>/dev/null || raspi-gpio set 23,24 pu 2>/dev/null || true

echo "[2/4] Removing any previous I2C-3 overlay..."
sudo dtoverlay -r i2c-gpio 2>/dev/null || true

echo "[3/4] Enabling clean, noise-tolerant I2C-3 overlay..."
sudo dtoverlay i2c-gpio bus=3 i2c_gpio_sda=23 i2c_gpio_scl=24 i2c_gpio_delay_us=10 2>/dev/null || true

CONFIG_FILE="/boot/firmware/config.txt"
if [ ! -f "$CONFIG_FILE" ]; then
    CONFIG_FILE="/boot/config.txt"
fi

# Clean up any bad or old entries
sudo sed -i '/gpio=23,24=pu/d' "$CONFIG_FILE" 2>/dev/null || true
sudo sed -i '/dtoverlay=i2c-gpio/d' "$CONFIG_FILE" 2>/dev/null || true
sudo sed -i '/^123$/d' "$CONFIG_FILE" 2>/dev/null || true

echo "gpio=23,24=pu" | sudo tee -a "$CONFIG_FILE" >/dev/null
echo "dtoverlay=i2c-gpio,bus=3,i2c_gpio_sda=23,i2c_gpio_scl=24,i2c_gpio_delay_us=10" | sudo tee -a "$CONFIG_FILE" >/dev/null
echo "Configured persistent pull-up and 50kHz noise-free overlay in $CONFIG_FILE."

echo "[4/4] Scanning for connected displays..."
echo "--- Screen 1 Bus (I2C-1: SDA=Pin 3, SCL=Pin 5) ---"
sudo i2cdetect -y 1 || true

echo "--- Screen 2 Bus (I2C-3: SDA=Pin 16, SCL=Pin 18) ---"
sudo i2cdetect -y 3 || true

echo "=========================================================="
echo " Pins status:"
pinctrl get 23,24 2>/dev/null || true
echo " Done! Run test: python3 test_oled.py --rotate 180"
echo "=========================================================="
