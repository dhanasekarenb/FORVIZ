"""
High-Precision, Anti-Overheat, Jitter-Free Servo Controller for 2x SG90.
========================================================================
Default Pinout:
  - Pan  (Horizontal): GPIO 12 (Physical Pin 32) -> PWM0
  - Tilt (Vertical):   GPIO 19 (Physical Pin 35) -> PWM1
  - Ground:            Physical Pin 34
  - Power:             5V (Physical Pin 2 or 4)
"""
import time
import math

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


class PanTiltTracker:
    """
    Controls Pan (GPIO 12) and Tilt (GPIO 19) SG90 servos.
    Features:
      - Hardware DMA PWM via pigpio (zero jitter)
      - Anti-overheat auto-rest (detaches PWM when stationary)
      - Slew-rate limiting for cinematic smooth motion
      - Safe angle clamping (Pan: 20-160 deg, Tilt: 45-135 deg)
    """
    def __init__(self, pan_pin=12, tilt_pin=19,
                 pan_range=(20, 160), tilt_range=(45, 135),
                 pan_center=90, tilt_center=90,
                 max_speed_deg=1.6, idle_timeout_sec=0.6):
        self.pan_pin = pan_pin
        self.tilt_pin = tilt_pin
        self.pan_min, self.pan_max = pan_range
        self.tilt_min, self.tilt_max = tilt_range
        self.max_speed_deg = max_speed_deg
        self.idle_timeout_sec = idle_timeout_sec

        self.current_pan = float(pan_center)
        self.current_tilt = float(tilt_center)
        self.target_pan = float(pan_center)
        self.target_tilt = float(tilt_center)

        # SG90 safe microsecond pulse widths
        self.min_us = 600
        self.max_us = 2300

        self.last_move_time = time.time()
        self.is_sleeping = False
        self.backend = "DUMMY"
        self.pi = None
        self.pan_servo = None
        self.tilt_servo = None

        self.scan_direction = 1
        self.scan_speed = 0.8

        # 1. Native pigpio Hardware DMA (Primary)
        if PIGPIO_AVAILABLE:
            try:
                self.pi = pigpio.pi()
                if self.pi.connected:
                    self.backend = "PIGPIO"
                    print(f"[SERVOS] pigpio Hardware DMA active.")
                    print(f"         Pan:  GPIO {pan_pin} (Pin 32)")
                    print(f"         Tilt: GPIO {tilt_pin} (Pin 35)")
                else:
                    self.pi = None
            except Exception:
                self.pi = None

        # 2. Fallback gpiozero
        if self.backend == "DUMMY" and GPIOZERO_AVAILABLE:
            try:
                factory = None
                try:
                    factory = PiGPIOFactory()
                except Exception:
                    pass

                self.pan_servo = AngularServo(
                    self.pan_pin, min_angle=0, max_angle=180,
                    min_pulse_width=0.0006, max_pulse_width=0.0023,
                    pin_factory=factory
                )
                self.tilt_servo = AngularServo(
                    self.tilt_pin, min_angle=0, max_angle=180,
                    min_pulse_width=0.0006, max_pulse_width=0.0023,
                    pin_factory=factory
                )
                self.backend = "GPIOZERO"
                print(f"[SERVOS] Initialized via gpiozero (Pan: GPIO {pan_pin}, Tilt: GPIO {tilt_pin})")
            except Exception as e:
                print(f"[SERVOS WARNING] gpiozero init failed ({e}).")

        if self.backend == "DUMMY":
            print("[SERVOS INFO] Running in simulation mode (no physical GPIO hardware detected).")

        # Command initial center
        self._write_angles(self.current_pan, self.current_tilt)

    def angle_to_us(self, angle_deg):
        """Converts angle (0-180 deg) to pulse width in microseconds (600-2300 us)."""
        clamped = max(0.0, min(180.0, angle_deg))
        return int(self.min_us + (clamped / 180.0) * (self.max_us - self.min_us))

    def _write_angles(self, pan_deg, tilt_deg):
        """Sends PWM signals to the hardware."""
        self.is_sleeping = False
        self.last_move_time = time.time()

        if self.backend == "PIGPIO" and self.pi is not None:
            pan_us = self.angle_to_us(pan_deg)
            tilt_us = self.angle_to_us(tilt_deg)
            self.pi.set_servo_pulsewidth(self.pan_pin, pan_us)
            self.pi.set_servo_pulsewidth(self.tilt_pin, tilt_us)

        elif self.backend == "GPIOZERO" and self.pan_servo is not None:
            try:
                self.pan_servo.angle = pan_deg
                self.tilt_servo.angle = tilt_deg
            except Exception:
                pass

    def sleep_idle(self):
        """
        ANTI-OVERHEAT PROTECTION:
        Detaches the PWM pulses when stationary. The servo stops humming, draws 0 mA
        stall current, and remains completely cool.
        """
        if self.is_sleeping:
            return
        if (time.time() - self.last_move_time) > self.idle_timeout_sec:
            if self.backend == "PIGPIO" and self.pi is not None:
                self.pi.set_servo_pulsewidth(self.pan_pin, 0)
                self.pi.set_servo_pulsewidth(self.tilt_pin, 0)
            elif self.backend == "GPIOZERO" and self.pan_servo is not None:
                try:
                    self.pan_servo.detach()
                    self.tilt_servo.detach()
                except Exception:
                    pass
            self.is_sleeping = True

    def track_face(self, target_cx, target_cy, frame_w=640, frame_h=480, deadband=0.08):
        """
        Smoothly adjusts pan and tilt angles to center the target face.
        """
        norm_dx = (target_cx - (frame_w / 2.0)) / (frame_w / 2.0)
        norm_dy = (target_cy - (frame_h / 2.0)) / (frame_h / 2.0)

        # Ignore micro-movements within deadband to stop twitching
        if abs(norm_dx) < deadband and abs(norm_dy) < deadband:
            self.sleep_idle()
            return self.current_pan, self.current_tilt

        step_pan = -norm_dx * 2.5
        step_tilt = norm_dy * 2.0

        self.target_pan = max(self.pan_min, min(self.pan_max, self.current_pan + step_pan))
        self.target_tilt = max(self.tilt_min, min(self.tilt_max, self.current_tilt + step_tilt))

        # Slew-rate limiter prevents sudden jerking
        delta_p = self.target_pan - self.current_pan
        delta_t = self.target_tilt - self.current_tilt

        delta_p = max(-self.max_speed_deg, min(self.max_speed_deg, delta_p))
        delta_t = max(-self.max_speed_deg, min(self.max_speed_deg, delta_t))

        if abs(delta_p) > 0.25 or abs(delta_t) > 0.25:
            self.current_pan += delta_p
            self.current_tilt += delta_t
            self._write_angles(self.current_pan, self.current_tilt)
        else:
            self.sleep_idle()

        return self.current_pan, self.current_tilt

    def step_scan(self):
        """Smooth and gentle sweep search pattern."""
        delta = self.scan_direction * self.scan_speed
        self.current_pan += delta

        if self.current_pan >= self.pan_max:
            self.current_pan = self.pan_max
            self.scan_direction = -1
        elif self.current_pan <= self.pan_min:
            self.current_pan = self.pan_min
            self.scan_direction = 1

        self.current_tilt = 85.0
        self._write_angles(self.current_pan, self.current_tilt)
        return self.current_pan, self.current_tilt

    def set_direct(self, pan_deg, tilt_deg):
        """Commands specific angles safely."""
        self.current_pan = max(self.pan_min, min(self.pan_max, pan_deg))
        self.current_tilt = max(self.tilt_min, min(self.tilt_max, tilt_deg))
        self._write_angles(self.current_pan, self.current_tilt)

    def center(self):
        self.set_direct(90, 90)

    def close(self):
        """Clean shutdown and cut power."""
        if self.backend == "PIGPIO" and self.pi is not None:
            self.pi.set_servo_pulsewidth(self.pan_pin, 0)
            self.pi.set_servo_pulsewidth(self.tilt_pin, 0)
            self.pi.stop()
        elif self.backend == "GPIOZERO":
            if self.pan_servo:
                self.pan_servo.close()
            if self.tilt_servo:
                self.tilt_servo.close()
