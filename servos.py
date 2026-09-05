"""Shared SG90 pan/tilt control. PWM detach releases holding torque, not power."""
import math
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


class PanTiltTracker:
    """Time-based bounded motion, with conservative V3 operating limits.

    max_speed_deg is a legacy degrees/frame argument, converted at 30 FPS.
    New callers should use max_speed_deg_per_sec. A 100 ms elapsed-time cap
    prevents large moves after an inference stall. Idle detach is opt-in:
    a loaded head may drop when PWM stops.
    """
    def __init__(self, pan_pin=12, tilt_pin=19,
                 pan_range=(40, 140), tilt_range=(65, 115),
                 pan_center=90, tilt_center=90,
                 max_speed_deg=None, idle_timeout_sec=None, *,
                 max_speed_deg_per_sec=36.0, scan_speed_deg_per_sec=18.0,
                 hardware=True, clock=None):
        self.pan_min, self.pan_max = self._validate_range(pan_range)
        self.tilt_min, self.tilt_max = self._validate_range(tilt_range)
        for center, low, high in ((pan_center, self.pan_min, self.pan_max),
                                  (tilt_center, self.tilt_min, self.tilt_max)):
            if not math.isfinite(center) or not low <= center <= high:
                raise ValueError('Servo center must be inside its configured range')
        if max_speed_deg is not None:
            max_speed_deg_per_sec = max_speed_deg * 30.0
        if (not math.isfinite(max_speed_deg_per_sec) or max_speed_deg_per_sec <= 0
                or not math.isfinite(scan_speed_deg_per_sec) or scan_speed_deg_per_sec <= 0):
            raise ValueError('Servo speeds must be finite and positive')
        if idle_timeout_sec is not None and (not math.isfinite(idle_timeout_sec) or idle_timeout_sec <= 0):
            raise ValueError('Idle detach timeout must be positive or None')
        self.pan_pin, self.tilt_pin = pan_pin, tilt_pin
        self.pan_center, self.tilt_center = float(pan_center), float(tilt_center)
        self.current_pan = self.target_pan = self.pan_center
        self.current_tilt = self.target_tilt = self.tilt_center
        self.max_speed_deg_per_sec = float(max_speed_deg_per_sec)
        self.scan_speed_deg_per_sec = min(float(scan_speed_deg_per_sec), self.max_speed_deg_per_sec)
        self.idle_timeout_sec = idle_timeout_sec
        self.min_us, self.max_us = 600, 2300
        self._clock = clock or time.monotonic
        self._last_update = self.last_move_time = self._clock()
        self.is_sleeping = self._closed = False
        self.scan_direction = 1
        self.backend = 'DUMMY'
        self.pi = self.pan_servo = self.tilt_servo = self._factory = None
        if hardware:
            self._connect()
        if self.backend == 'DUMMY':
            print('[SERVOS] Simulation mode: no physical GPIO output.')
        try:
            self._write_angles(self.current_pan, self.current_tilt)
        except Exception:
            self.close()
            raise

    @staticmethod
    def _validate_range(limits):
        low, high = map(float, limits)
        if not all(math.isfinite(v) for v in (low, high)) or not 0 <= low < high <= 180:
            raise ValueError('Servo ranges must satisfy 0 <= minimum < maximum <= 180')
        return low, high

    def _connect(self):
        if PIGPIO_AVAILABLE:
            try:
                self.pi = pigpio.pi()
                if self.pi.connected:
                    self.backend = 'PIGPIO'
                else:
                    self.pi.stop()
                    self.pi = None
            except Exception:
                if self.pi is not None:
                    self.pi.stop()
                self.pi = None
        if self.backend == 'DUMMY' and GPIOZERO_AVAILABLE:
            try:
                try:
                    self._factory = PiGPIOFactory()
                except Exception:
                    self._factory = None
                for attr, pin in (('pan_servo', self.pan_pin), ('tilt_servo', self.tilt_pin)):
                    setattr(self, attr, AngularServo(
                        pin, initial_angle=None, min_angle=0, max_angle=180,
                        min_pulse_width=0.0006, max_pulse_width=0.0023,
                        pin_factory=self._factory))
                self.backend = 'GPIOZERO'
            except Exception as exc:
                self._close_gpiozero()
                print(f'[SERVOS WARNING] gpiozero unavailable: {exc}')
        if self.backend != 'DUMMY':
            print(f'[SERVOS] {self.backend}: pan GPIO {self.pan_pin}, tilt GPIO {self.tilt_pin}')

    def _elapsed(self):
        now = self._clock()
        dt = max(0.0, min(0.1, now - self._last_update))
        self._last_update = now
        return dt

    def angle_to_us(self, angle_deg):
        return int(self.min_us + max(0.0, min(180.0, angle_deg)) / 180.0 * (self.max_us - self.min_us))

    def _write_angles(self, pan_deg, tilt_deg):
        if self._closed:
            raise RuntimeError('Servo controller is closed')
        if self.backend == 'PIGPIO':
            self.pi.set_servo_pulsewidth(self.pan_pin, self.angle_to_us(pan_deg))
            self.pi.set_servo_pulsewidth(self.tilt_pin, self.angle_to_us(tilt_deg))
        elif self.backend == 'GPIOZERO':
            self.pan_servo.angle = pan_deg
            self.tilt_servo.angle = tilt_deg
        self.is_sleeping = False
        self.last_move_time = self._clock()

    def sleep_idle(self):
        """Optionally detach PWM after rest; the head then loses holding torque."""
        if (self._closed or self.is_sleeping or self.idle_timeout_sec is None
                or self._clock() - self.last_move_time < self.idle_timeout_sec):
            return
        self._detach()
        self.is_sleeping = True

    def hold(self):
        """Consume elapsed time without motion during a short detection gap."""
        self._elapsed()
        self.sleep_idle()
        return self.current_pan, self.current_tilt

    def _move(self, pan, tilt):
        pan = max(self.pan_min, min(self.pan_max, pan))
        tilt = max(self.tilt_min, min(self.tilt_max, tilt))
        self.target_pan, self.target_tilt = pan, tilt
        if abs(pan - self.current_pan) > 1e-9 or abs(tilt - self.current_tilt) > 1e-9:
            self._write_angles(pan, tilt)
            self.current_pan, self.current_tilt = pan, tilt
        else:
            self.sleep_idle()
        return self.current_pan, self.current_tilt

    def track_face(self, target_cx, target_cy, frame_w=640, frame_h=480, deadband=0.08):
        """Proportional velocity control with the same deadband used by face lock."""
        if (not all(math.isfinite(v) for v in (target_cx, target_cy, frame_w, frame_h, deadband))
                or frame_w <= 0 or frame_h <= 0 or not 0 <= deadband < 1):
            raise ValueError('Face coordinates and frame dimensions must be finite and valid')
        dt = self._elapsed()
        dx = (target_cx - frame_w / 2.0) / (frame_w / 2.0)
        dy = (target_cy - frame_h / 2.0) / (frame_h / 2.0)
        pan_velocity = 0.0 if abs(dx) <= deadband else -dx * 75.0
        tilt_velocity = 0.0 if abs(dy) <= deadband else dy * 60.0
        limit = self.max_speed_deg_per_sec
        return self._move(
            self.current_pan + max(-limit, min(limit, pan_velocity)) * dt,
            self.current_tilt + max(-limit, min(limit, tilt_velocity)) * dt)

    def step_scan(self):
        """Sweep pan and ease tilt toward the calibrated center, within limits."""
        dt = self._elapsed()
        pan = self.current_pan + self.scan_direction * self.scan_speed_deg_per_sec * dt
        if pan >= self.pan_max:
            pan, self.scan_direction = self.pan_max, -1
        elif pan <= self.pan_min:
            pan, self.scan_direction = self.pan_min, 1
        step = self.max_speed_deg_per_sec * dt
        tilt = self.current_tilt + max(-step, min(step, self.tilt_center - self.current_tilt))
        return self._move(pan, tilt)

    def set_direct(self, pan_deg, tilt_deg):
        """Immediate bounded command for supported-head calibration only."""
        if not math.isfinite(pan_deg) or not math.isfinite(tilt_deg):
            raise ValueError('Servo angles must be finite')
        self._elapsed()
        pan = max(self.pan_min, min(self.pan_max, pan_deg))
        tilt = max(self.tilt_min, min(self.tilt_max, tilt_deg))
        self._write_angles(pan, tilt)
        self.current_pan = self.target_pan = pan
        self.current_tilt = self.target_tilt = tilt
        return pan, tilt

    def center(self):
        return self.set_direct(self.pan_center, self.tilt_center)

    def _detach(self):
        if self.backend == 'PIGPIO' and self.pi is not None:
            try:
                self.pi.set_servo_pulsewidth(self.pan_pin, 0)
            finally:
                self.pi.set_servo_pulsewidth(self.tilt_pin, 0)
        elif self.backend == 'GPIOZERO':
            try:
                self.pan_servo.detach()
            finally:
                self.tilt_servo.detach()

    def _close_gpiozero(self):
        for name in ('pan_servo', 'tilt_servo', '_factory'):
            device = getattr(self, name)
            if device is not None:
                try:
                    device.close()
                except Exception:
                    pass
                setattr(self, name, None)

    def close(self):
        """Release GPIO resources without moving the head on shutdown."""
        if self._closed:
            return
        try:
            self._detach()
        finally:
            self._closed = self.is_sleeping = True
            if self.pi is not None:
                self.pi.stop()
                self.pi = None
            self._close_gpiozero()
