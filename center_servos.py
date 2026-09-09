"""
Zero / Center Servos Utility for Robot Head Assembly
====================================================
Pins:
  Pan  (Horizontal) : GPIO 12 (Pin 32)
  Tilt (Vertical)   : GPIO 19 (Pin 35)

Run this BEFORE mounting the head:
  python3 center_servos.py
"""
import sys
import time

try:
    import pigpio
    PIGPIO_AVAILABLE = True
except ImportError:
    PIGPIO_AVAILABLE = False

try:
    from gpiozero import AngularServo
    from gpiozero.pins.pigpio import PiGPIOFactory
    GPIOZERO_AVAILABLE = True
except ImportError:
    GPIOZERO_AVAILABLE = False

PAN_PIN = 12
TILT_PIN = 19
CENTER_US = 1450 # 90 degrees neutral pulse width (standard 1450-1500us)

def main():
    print("=" * 65)
    print("       SERVO ZERO / CENTER ALIGNMENT UTILITY")
    print("=" * 65)
    print(f"Pan Pin:  GPIO {PAN_PIN} (Physical Pin 32)")
    print(f"Tilt Pin: GPIO {TILT_PIN} (Physical Pin 35)")
    print("=" * 65)

    pi = None
    if PIGPIO_AVAILABLE:
        try:
            pi = pigpio.pi()
            if not pi.connected:
                pi = None
        except Exception:
            pi = None

    if pi is not None:
        print("[1/3] Connected to pigpio daemon.")
        print("[2/3] Powering Pan and Tilt servos to 90 deg NEUTRAL CENTER...")
        # 1450us - 1500us is exact 90 deg center for SG90
        pi.set_servo_pulsewidth(PAN_PIN, 1450)
        pi.set_servo_pulsewidth(TILT_PIN, 1450)
    elif GPIOZERO_AVAILABLE:
        print("[1/3] Using gpiozero fallback...")
        factory = None
        try:
            factory = PiGPIOFactory()
        except Exception:
            pass
        pan = AngularServo(PAN_PIN, min_angle=0, max_angle=180, min_pulse_width=0.0006, max_pulse_width=0.0023, pin_factory=factory)
        tilt = AngularServo(TILT_PIN, min_angle=0, max_angle=180, min_pulse_width=0.0006, max_pulse_width=0.0023, pin_factory=factory)
        pan.angle = 90
        tilt.angle = 90
    else:
        print("[ERROR] Neither pigpio nor gpiozero is available! Run: ./setup_pi.sh")
        return

    print("\n" + "#" * 65)
    print("  >>> BOTH SERVOS ARE NOW ELECTRONICALLY LOCKED AT 90 DEG! <<<")
    print("#" * 65)
    print("\nWHILE THIS SCRIPT IS RUNNING (SERVOS ARE HOLDING POSITION):")
    print("  1. Take the Pan servo horn / neck bracket:")
    print("     -> Push it onto the Pan shaft facing STRAIGHT FORWARD.")
    print("     -> Tighten the small center gear screw.")
    print("  2. Take the Tilt servo horn / head shell:")
    print("     -> Push it onto the Tilt shaft facing STRAIGHT LEVEL (eyes horizontal).")
    print("     -> Tighten the small center gear screw.")
    print("\nWhen you have tightened both screws and the head is aligned,")
    input("Press [ENTER] to release the servos and finish... ")

    # Cleanup and release
    if pi is not None:
        pi.set_servo_pulsewidth(PAN_PIN, 0)
        pi.set_servo_pulsewidth(TILT_PIN, 0)
        pi.stop()
    print("\n[DONE] Servos zeroed, aligned, and power detached safely.")

if __name__ == "__main__":
    main()
