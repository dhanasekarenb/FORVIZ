"""
Interactive Servo Test & Calibration for Pan (GPIO 12) & Tilt (GPIO 19)
=======================================================================
Pinout:
  Pan  (Horizontal) : GPIO 12 (Physical Pin 32) -> Orange/Yellow Signal
  Tilt (Vertical)   : GPIO 19 (Physical Pin 35) -> Orange/Yellow Signal
  GND               : Physical Pin 34 (Between Pins 32 and 35!)
  5V (Power)        : Physical Pin 2 or 4 (or external 5V)
"""
import sys
import time
from servos import PanTiltTracker

def main():
    print("=" * 65)
    print("      PAN (GPIO 12) & TILT (GPIO 19) SERVO TEST")
    print("=" * 65)
    print("Header Pin Connections:")
    print("  Pin 32 -> Pan Servo (GPIO 12)")
    print("  Pin 34 -> Ground (GND)")
    print("  Pin 35 -> Tilt Servo (GPIO 19)")
    print("  Pin 2/4-> 5V Power (Red)")
    print("=" * 65)

    tracker = PanTiltTracker(pan_pin=12, tilt_pin=19)

    try:
        print("\n[Step 1] Centering both servos to 90 degrees...")
        tracker.center()
        print("  Both servos holding at 90 deg (Neutral Center).")
        time.sleep(2)

        print("\n[Step 2] Testing TILT Servo on GPIO 19 (Pin 35)...")
        print("  Nodding Up and Down (65 -> 115 deg)...")
        for angle in range(90, 116, 1):
            tracker.set_direct(90, angle)
            time.sleep(0.025)
        time.sleep(0.4)
        for angle in range(115, 64, -1):
            tracker.set_direct(90, angle)
            time.sleep(0.025)
        time.sleep(0.4)
        for angle in range(65, 91, 1):
            tracker.set_direct(90, angle)
            time.sleep(0.025)
        print("  Tilt (GPIO 19) test passed!")
        time.sleep(1)

        print("\n[Step 3] Testing PAN Servo on GPIO 12 (Pin 32)...")
        print("  Turning Left and Right (40 -> 140 deg)...")
        for angle in range(90, 141, 1):
            tracker.set_direct(angle, 90)
            time.sleep(0.02)
        time.sleep(0.4)
        for angle in range(140, 39, -1):
            tracker.set_direct(angle, 90)
            time.sleep(0.02)
        time.sleep(0.4)
        for angle in range(40, 91, 1):
            tracker.set_direct(angle, 90)
            time.sleep(0.02)
        print("  Pan (GPIO 12) test passed!")
        time.sleep(1)

        print("\n[Step 4] Testing Anti-Overheat Auto-Rest...")
        tracker.center()
        time.sleep(0.8)
        tracker.sleep_idle()
        print("  PWM pulses detached! The motors should be silent, zero hum, completely cool.")
        time.sleep(2.5)

        print("\n[Step 5] Smooth Simultaneous Pan & Tilt Movement...")
        for i in range(50):
            # Smooth circle/figure motion
            pan_angle = 90 + 35 * (1 if i % 2 == 0 else -1) * (i / 50.0)
            tilt_angle = 90 + 20 * (1 if (i // 2) % 2 == 0 else -1) * (i / 50.0)
            tracker.set_direct(pan_angle, tilt_angle)
            time.sleep(0.03)

        print("\n[Done] Returning to neutral 90 deg and cutting power.")
        tracker.center()
        time.sleep(0.5)
        tracker.sleep_idle()

    except KeyboardInterrupt:
        print("\nInterrupted by user.")
    finally:
        tracker.close()
        print("Servos detached safely.")

if __name__ == "__main__":
    main()
