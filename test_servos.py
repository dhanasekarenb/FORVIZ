"""
Interactive Servo Calibration & Test Script for 2x SG90 (Pan/Tilt)
Run this on your Raspberry Pi:
    python3 test_servos.py
"""
import sys
import time
from servos import PanTiltTracker, GPIOZERO_AVAILABLE

def main():
    print("=" * 60)
    print("      SG90 PAN & TILT SERVO TEST & CALIBRATION")
    print("=" * 60)
    print("Pinout:")
    print("  Pan  (Horizontal) : GPIO 18 (Pin 12) -> Servo Orange/Yellow Signal")
    print("  Tilt (Vertical)   : GPIO 13 (Pin 33) -> Servo Orange/Yellow Signal")
    print("  VCC               : 5V (Pin 2 or 4)   -> Servo Red Wire")
    print("  GND               : GND (Pin 6 or 14) -> Servo Brown/Black Wire")
    print("=" * 60)

    if not GPIOZERO_AVAILABLE:
        print("[WARNING] gpiozero is not installed! Run: sudo apt install python3-gpiozero")

    tracker = PanTiltTracker(pan_pin=18, tilt_pin=13)

    try:
        print("\n[Step 1] Centering both servos to 90 degrees...")
        tracker.center()
        print("  Servos are now at 90 deg (Neutral Center).")
        print("  Mount your servo horns / camera bracket facing straight forward now!")
        time.sleep(3)

        print("\n[Step 2] Testing Pan Range (0 -> 180 -> 90)...")
        for angle in range(90, 181, 5):
            tracker.set_direct(angle, 90)
            time.sleep(0.04)
        time.sleep(0.5)
        for angle in range(180, -1, -5):
            tracker.set_direct(angle, 90)
            time.sleep(0.04)
        time.sleep(0.5)
        for angle in range(0, 91, 5):
            tracker.set_direct(angle, 90)
            time.sleep(0.04)
        print("  Pan test complete.")

        print("\n[Step 3] Testing Tilt Range (50 -> 130 -> 90)...")
        for angle in range(90, 131, 5):
            tracker.set_direct(90, angle)
            time.sleep(0.05)
        time.sleep(0.5)
        for angle in range(130, 49, -5):
            tracker.set_direct(90, angle)
            time.sleep(0.05)
        time.sleep(0.5)
        for angle in range(50, 91, 5):
            tracker.set_direct(90, angle)
            time.sleep(0.05)
        print("  Tilt test complete.")

        print("\n[Step 4] Simulated Auto-Scan Sweep (Sweeping left & right for 5s)...")
        t_end = time.time() + 5.0
        while time.time() < t_end:
            p, t = tracker.step_scan()
            time.sleep(0.02)

        print("\n[Done] Returning to center.")
        tracker.center()
        time.sleep(1)

    except KeyboardInterrupt:
        print("\nExiting...")
    finally:
        tracker.close()
        print("Servos detached cleanly.")

if __name__ == "__main__":
    main()
