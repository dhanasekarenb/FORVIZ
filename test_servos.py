"""Manual SG90 calibration demo; support the head before releasing servo PWM.

python test_servos.py --center-only   # Set calibrated neutral for horn assembly
python test_servos.py --dry-run      # Simulate the movement sequence without GPIO
"""
import argparse
import math
import time
from servos import PanTiltTracker

__test__ = False


def main(argv=None):
    parser = argparse.ArgumentParser(description='FORVIZ SG90 calibration')
    parser.add_argument('--center-only', action='store_true', help='Hold 90 degrees until Ctrl+C')
    parser.add_argument('--dry-run', action='store_true', help='Disable physical GPIO')
    args = parser.parse_args(argv)
    tracker = PanTiltTracker(hardware=not args.dry_run)
    print('Pan GPIO 12 / tilt GPIO 19. Use a regulated servo supply and common ground.')
    print('Support the head: stopping releases servo holding torque.')
    try:
        tracker.center()
        if args.center_only:
            print('Holding both shafts at 90 degrees. Ctrl+C releases PWM.')
            while True:
                time.sleep(0.1)
        print('Demo: smooth bounded motion (pan 55..125, tilt 70..110). Ctrl+C stops.')
        started = time.monotonic()
        # Continuous slow sine motion replaces the previous alternating angle jumps.
        while True:
            elapsed = time.monotonic() - started
            if elapsed >= 12.0:
                break
            tracker.set_direct(90 + 35 * math.sin(2 * math.pi * elapsed / 12),
                               90 + 20 * math.sin(2 * math.pi * elapsed / 6))
            time.sleep(0.02)
        print('Motion commands completed. Check physical response and cable clearance.')
    except KeyboardInterrupt:
        print('Interrupted.')
    finally:
        tracker.close()
        print('PWM released; servo supply remains connected.')


if __name__ == '__main__':
    main()
