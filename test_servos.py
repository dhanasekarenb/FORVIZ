"""
Interactive Smooth Servo Calibration & Anti-Overheat Test Script
Pan:  GPIO 12 (Physical Pin 32)
Tilt: GPIO 13 (Physical Pin 33)
"""
import sys
import time
from servos import PanTiltTracker

def main():
    print("=" * 65)
    print("     SMOOTH & ANTI-OVERHEAT SG90 SERVO CALIBRATION")
    print("=" * 65)
    print("Wiring:")
    print("  Pan  (Horizontal) : GPIO 12 (Physical Pin 32) -> Orange/Yellow Signal")
    print("  Tilt (Vertical)   : GPIO 13 (Physical Pin 33) -> Orange/Yellow Signal")
    print("  GND               : Physical Pin 34 (Right next to pin 32/33!)")
    print("  VCC (Power)       : 5V (Pin 2 or 4, or external 5V)")
    print("=" * 65)

    tracker = PanTiltTracker(pan_pin=12, tilt_pin=13)

    try:
        print("\n[Step 1] Centering both servos to 90 degrees...")
        tracker.center()
        print("  Servos are now at 90 deg (Neutral Center).")
        print("  Mount your camera bracket facing straight forward now!")
        time.sleep(3)

        print("\n[Step 2] Testing Smooth Pan Sweep (40 -> 140 deg)...")
        # Sweep Pan smoothly in 1.5 deg steps
        for angle in range(90, 141, 1):
            tracker.set_direct(angle, 90)
            time.sleep(0.02)
        time.sleep(0.5)
        for angle in range(140, 39, -1):
            tracker.set_direct(angle, 90)
            time.sleep(0.02)
        time.sleep(0.5)
        for angle in range(40, 91, 1):
            tracker.set_direct(angle, 90)
            time.sleep(0.02)
        print("  Pan sweep complete.")

        print("\n[Step 3] Testing Smooth Tilt Sweep (60 -> 120 deg)...")
        for angle in range(90, 121, 1):
            tracker.set_direct(90, angle)
            time.sleep(0.02)
        time.sleep(0.5)
        for angle in range(120, 59, -1):
            tracker.set_direct(90, angle)
            time.sleep(0.02)
        time.sleep(0.5)
        for angle in range(60, 91, 1):
            tracker.set_direct(90, angle)
            time.sleep(0.02)
        print("  Tilt sweep complete.")

        print("\n[Step 4] Testing Anti-Overheat Auto-Rest (Waiting 3s stationary)...")
        tracker.center()
        time.sleep(1.0)
        tracker.sleep_idle()
        print("  PWM signal detached! Touch the servos: they should NOT buzz or get hot.")
        time.sleep(3.0)

        print("\n[Step 5] Testing Gentle Auto-Scan Sweep (5 seconds)...")
        t_end = time.time() + 5.0
        while time.time() < t_end:
            p, t = tracker.step_scan()
            time.sleep(0.03)

        print("\n[Done] Returning to center and cutting power to cool down.")
        tracker.center()
        time.sleep(0.5)
        tracker.sleep_idle()

    except KeyboardInterrupt:
        print("\nInterrupted by user.")
    finally:
        tracker.close()
        print("Servos detached cleanly.")

if __name__ == "__main__":
    main()
