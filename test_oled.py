"""
Interactive OLED Robot Eyes Test Script & I2C Bus Diagnostic Tool
=================================================================
Usage:
  python3 test_oled.py          # Auto-detects 1 or 2 screens and runs eye animations
  python3 test_oled.py --scan   # Scans all I2C ports and diagnoses display connections
  python3 test_oled.py --dual   # Requests two screens; falls back if unavailable
  python3 test_oled.py --single # Renders both eyes on one detected screen
  python3 test_oled.py --mirror-eye # Same-address, same-bus OLEDs show one mirrored eye
"""
__test__ = False  # Interactive hardware demo, excluded from pytest collection.
import time
import argparse
from oled_face import DEFAULT_OLED_ROTATION, OLEDDisplayController

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
        d = None
        try:
            s = i2c(port=port, address=addr)
            d = ssd1306(s)
            d.clear()
            print(f"  [SUCCESS] Found SSD1306 on Port {port}, Addr 0x{addr:X} -> {desc}")
            found.append((port, addr))
        except Exception:
            # Not found or port doesn't exist
            pass
        finally:
            if d is not None:
                try:
                    d.cleanup()
                except Exception:
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
        print(f"[STATUS] 1 I2C address responded (Port {port}, Addr 0x{addr:X}).")
        print("A scan cannot count physical OLEDs sharing the same bus and address.")
        print("If both OLEDs share SDA/SCL and 0x3C, run: python3 test_oled.py --mirror-eye")
        print("Both screens should show the same centered eye; verify both visually.")
        print("For independent left/right eyes, use different addresses or separate buses.")
    else:
        print(f"[STATUS] 2 OLED displays detected! Dual Eyes are ready to roll!")
        for p, a in found:
            print(f"  - Screen on Port {p}, Addr 0x{a:X}")
    print("=" * 65)

def run_hardware_demo(dual_mode=None, rotate=DEFAULT_OLED_ROTATION,
                      rotate_1=None, rotate_2=None, single_eye=False):
    print("=" * 65)
    print("        ROBOT OLED EYES EXPRESSION DEMO")
    print("=" * 65)

    face = OLEDDisplayController(dual_screen=dual_mode, rotate=rotate, rotate_1=rotate_1, rotate_2=rotate_2, single_eye=single_eye)
    face.start()

    if face.dual_screen:
        mode_str = "Dual Screens (Left Eye on #1, Right Eye on #2)"
    elif face.single_eye:
        mode_str = "Mirrored Single Eye (same image sent to one I2C address; check both screens visually)"
    else:
        mode_str = "Single Screen (Both eyes on 1 display)"
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

        print("[6/6] Heart Eyes (Demo Expression)...")
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
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--dual", action="store_true", help="Request two OLED screens")
    modes.add_argument("--single", action="store_true", help="Use one OLED screen")
    modes.add_argument("--mirror-eye", "--single-eye", dest="mirror_eye", action="store_true",
                       help="Render ONE big centered eye for mirrored dual-display on Pin 3 & Pin 5")
    parser.add_argument("--rotate", type=int, default=DEFAULT_OLED_ROTATION,
                        choices=[0, 90, 180, 270],
                        help="Rotate all OLED displays (default: 180 for the installed panels)")
    parser.add_argument("--rotate1", type=int, default=None, choices=[0, 90, 180, 270],
                        help="Rotate screen 1 specifically (0, 90, 180, 270 deg)")
    parser.add_argument("--rotate2", type=int, default=None, choices=[0, 90, 180, 270],
                        help="Rotate screen 2 specifically (0, 90, 180, 270 deg)")
    args = parser.parse_args()

    if args.scan:
        scan_i2c()
    else:
        run_hardware_demo(
            dual_mode=False if (args.single or args.mirror_eye) else (True if args.dual else None),
            rotate=args.rotate,
            rotate_1=args.rotate1,
            rotate_2=args.rotate2,
            single_eye=args.mirror_eye,
        )
