"""
Servo Controller for 2x SG90 (Pan & Tilt) on Raspberry Pi
Supports gpiozero (AngularServo) with smooth PID/proportional tracking
and auto-sweep scanning.
"""
import time
import math

try:
    from gpiozero import AngularServo
    from gpiozero.pins.pigpio import PiGPIOFactory
    GPIOZERO_AVAILABLE = True
except ImportError:
    GPIOZERO_AVAILABLE = False


class DummyServo:
    """Fallback dummy servo for testing on PC or when GPIO is uninitialized."""
    def __init__(self, name):
        self.name = name
        self.angle = 90.0

    def set_angle(self, angle):
        self.angle = angle
        # print(f"[{self.name}] Angle -> {angle:.1f} deg")

    def close(self):
        pass


class PanTiltTracker:
    """
    Controls Pan (horizontal) and Tilt (vertical) SG90 servos.
    Default pinout:
      - Pan (Yaw):   GPIO 18 (Pin 12)
      - Tilt (Pitch): GPIO 13 (Pin 33)
    """
    def __init__(self, pan_pin=18, tilt_pin=13, use_hardware_pwm=True,
                 pan_range=(0, 180), tilt_range=(35, 145),
                 pan_center=90, tilt_center=90):
        self.pan_pin = pan_pin
        self.tilt_pin = tilt_pin
        self.pan_min, self.pan_max = pan_range
        self.tilt_min, self.tilt_max = tilt_range
        
        self.current_pan = float(pan_center)
        self.current_tilt = float(tilt_center)
        self.target_pan = float(pan_center)
        self.target_tilt = float(tilt_center)

        # Auto scan state
        self.scan_direction = 1
        self.scan_speed = 1.2  # deg per tick
        self.last_face_time = time.time()
        self.scan_delay_sec = 1.5

        self.hardware_active = False

        if GPIOZERO_AVAILABLE:
            try:
                # Use pigpio factory for jitter-free hardware-timed PWM if available
                factory = None
                if use_hardware_pwm:
                    try:
                        factory = PiGPIOFactory()
                    except Exception:
                        factory = None

                # SG90 typical pulse widths: ~0.5ms (0 deg) to ~2.4ms (180 deg)
                self.pan_servo = AngularServo(
                    self.pan_pin,
                    min_angle=0,
                    max_angle=180,
                    min_pulse_width=0.0005,
                    max_pulse_width=0.0024,
                    pin_factory=factory
                )
                self.tilt_servo = AngularServo(
                    self.tilt_pin,
                    min_angle=0,
                    max_angle=180,
                    min_pulse_width=0.0005,
                    max_pulse_width=0.0024,
                    pin_factory=factory
                )
                self.hardware_active = True
                self.pan_servo.angle = self.current_pan
                self.tilt_servo.angle = self.current_tilt
                print(f"[SERVOS] Initialized Pan (GPIO {pan_pin}) & Tilt (GPIO {tilt_pin}) successfully.")
            except Exception as e:
                print(f"[SERVOS WARNING] GPIO Servo init failed ({e}). Falling back to dummy mode.")
                self.pan_servo = DummyServo("PAN")
                self.tilt_servo = DummyServo("TILT")
        else:
            print("[SERVOS WARNING] gpiozero not installed. Falling back to dummy mode.")
            self.pan_servo = DummyServo("PAN")
            self.tilt_servo = DummyServo("TILT")

    def track_face(self, target_cx, target_cy, frame_width=640, frame_height=480, smoothing=0.18):
        """
        Updates target pan and tilt angles based on normalized face center offset.
        - target_cx, target_cy: Pixel coordinates of detected face center
        """
        self.last_face_time = time.time()

        # Compute normalized errors from center (-1.0 to +1.0)
        norm_dx = (target_cx - (frame_width / 2.0)) / (frame_width / 2.0)
        norm_dy = (target_cy - (frame_height / 2.0)) / (frame_height / 2.0)

        # Deadband threshold to eliminate micro-vibrations
        deadband = 0.06
        if abs(norm_dx) < deadband:
            norm_dx = 0.0
        if abs(norm_dy) < deadband:
            norm_dy = 0.0

        # Step angle proportionally (camera is mounted on pan/tilt head)
        # Inverted or direct depending on physical servo orientation:
        pan_step = -norm_dx * 3.5
        tilt_step = norm_dy * 2.8

        self.target_pan = max(self.pan_min, min(self.pan_max, self.current_pan + pan_step))
        self.target_tilt = max(self.tilt_min, min(self.tilt_max, self.current_tilt + tilt_step))

        # Smooth interpolation
        self.current_pan += (self.target_pan - self.current_pan) * smoothing
        self.current_tilt += (self.target_tilt - self.current_tilt) * smoothing

        self._apply_angles()
        return self.current_pan, self.current_tilt

    def step_scan(self):
        """Smoothly sweeps pan servo back and forth to search for a face."""
        if (time.time() - self.last_face_time) < self.scan_delay_sec:
            return self.current_pan, self.current_tilt

        self.current_pan += self.scan_direction * self.scan_speed
        if self.current_pan >= self.pan_max:
            self.current_pan = self.pan_max
            self.scan_direction = -1
        elif self.current_pan <= self.pan_min:
            self.current_pan = self.pan_min
            self.scan_direction = 1

        # Keep tilt slightly up during scanning
        self.current_tilt = 85.0
        self._apply_angles()
        return self.current_pan, self.current_tilt

    def set_direct(self, pan_deg, tilt_deg):
        """Directly command target angles (clamped to safe ranges)."""
        self.current_pan = max(self.pan_min, min(self.pan_max, pan_deg))
        self.current_tilt = max(self.tilt_min, min(self.tilt_max, tilt_deg))
        self._apply_angles()

    def _apply_angles(self):
        if self.hardware_active:
            try:
                self.pan_servo.angle = self.current_pan
                self.tilt_servo.angle = self.current_tilt
            except Exception:
                pass

    def center(self):
        """Returns servos to neutral 90-degree center position."""
        self.set_direct(90, 90)

    def close(self):
        """Detaches and releases servo PWM."""
        if self.hardware_active:
            try:
                self.pan_servo.close()
                self.tilt_servo.close()
            except Exception:
                pass
