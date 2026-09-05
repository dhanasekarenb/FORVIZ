"""
Interactive OLED Robot Eyes Test Script & I2C Bus Diagnostic Tool
=================================================================
Usage:
  python3 test_oled.py          # Auto-detects 1 or 2 screens and runs eye animations
  python3 test_oled.py --scan   # Scans all I2C ports and diagnoses display connections
  python3 test_oled.py --dual   # Forces dual-screen mode
"""
import sys
import time
import argparse
from oled_face import OLEDDisplayController, RobotEyesRenderer

def scan_i2c():
    print("=" * 65)
    print("           I2C OLED DISPLAY DIAGNOSTIC SCANNER")
    print("=" * 65)

    try:
        from luma.core.interface.serial import i2c
        from luma.oled.device import ssd1306
    except ImportError:
        print("[ERROR] 'luma.oled' is not installed! Run: pip3 install luma.oled")
        return

    found = []
    # Test ports and addresses
    probes = [
        (1, 0x3C, "I2C Bus 1 (Default: SDA=GPIO 2/Pin 3, SCL=GPIO 3/Pin 5)"),
        (1, 0x3D, "I2C Bus 1 (Jumper modified to 0x3D)"),
        (3, 0x3C, "I2C Bus 3 (Software: SDA=GPIO 23/Pin 16, SCL=GPIO 24/Pin 18)"),
        (3, 0x3D, "I2C Bus 3 (Software: Addr 0x3D)"),
    ]

    for port, addr, desc in probes:
        try:
            s = i2c(port=port, address=addr)
            d = ssd1306(s)
            d.clear()
            print(f"  [SUCCESS] Found SSD1306 on Port {port}, Addr 0x{addr:X} -> {desc}")
            found.append((port, addr))
        except Exception as e:
            # Not found or port doesn't exist
            pass

    print("-" * 65)
    if len(found) == 0:
        print("[WARNING] No OLED displays detected!")
        print("Check wiring:")
        print("  VCC -> 3.3V (Pin 1)")
        print("  GND -> GND (Pin 9)")
        print("  SDA -> GPIO 2 (Pin 3)")
        print("  SCL -> GPIO 3 (Pin 5)")
    elif len(found) == 1:
        port, addr = found[0]
        print(f"[STATUS] 1 OLED display detected (Port {port}, Addr 0x{addr:X}).")
        print("\nTo enable your 2nd OLED display without soldering:")
        print("  1. Connect Screen 2 to GPIO 23 (Pin 16 - SDA) and GPIO 24 (Pin 18 - SCL).")
        print("  2. Run: ./enable_dual_oled.sh")
    else:
        print(f"[STATUS] 2 OLED displays detected! Dual Eyes are ready to roll!")
        for p, a in found:
            print(f"  - Screen on Port {p}, Addr 0x{a:X}")
    print("=" * 65)

def test_on_hardware(dual_mode=None):
    print("=" * 65)
    print("        ROBOT OLED EYES EXPRESSION DEMO")
    print("=" * 65)

    face = OLEDDisplayController(dual_screen=dual_mode)
    face.start()

    mode_str = "Dual Screens (Left Eye on #1, Right Eye on #2)" if face.dual_screen else "Single Screen (Both eyes on 1 display)"
    print(f"Active Mode: {mode_str}")
    print("Running expression cycle...")
    print("=" * 65)

    try:
        print("[1/6] Neutral Eyes (Idle blinking)...")
        face.set_expression("NEUTRAL", gaze_x=0.0, gaze_y=0.0)
        time.sleep(3)

        print("[2/6] Tracking Left...")
        face.set_expression("NEUTRAL", gaze_x=-0.9, gaze_y=0.0)
        time.sleep(2)

        print("[3/6] Tracking Right...")
        face.set_expression("NEUTRAL", gaze_x=0.9, gaze_y=0.0)
        time.sleep(2)

        print("[4/6] Looking Up...")
        face.set_expression("NEUTRAL", gaze_x=0.0, gaze_y=-0.8)
        time.sleep(2)

        print("[5/6] Happy Face (Target Locked!)...")
        face.set_expression("HAPPY", gaze_x=0.0, gaze_y=0.0)
        time.sleep(3)

        print("[6/6] Heart Eyes (Face Recognized!)...")
        face.set_expression("HEART", gaze_x=0.0, gaze_y=0.0)
        time.sleep(3)

        print("[Done] Demo completed.")
    except KeyboardInterrupt:
        print("\nExiting...")
    finally:
        face.stop()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--scan", action="store_true", help="Diagnose connected I2C OLED screens")
    parser.add_argument("--dual", action="store_true", help="Force dual OLED mode")
    args = parser.parse_args()

    if args.scan:
        scan_i2c()
    else:
        test_on_hardware(dual_mode=args.dual if args.dual else None)
