"""FORVIZ face tracker using shared servo and OLED controllers.

Pan GPIO 12, tilt GPIO 19; OLED bus 1 and optional software bus 3.
Use --help for hardware-disable, display and mechanical calibration options.
"""
import argparse
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

import cv2
from servos import PanTiltTracker
from oled_face import DEFAULT_OLED_ROTATION, OLEDDisplayController, RobotEyesRenderer

YUNET_MODEL_PATH = str(Path(__file__).resolve().with_name('face_detection_yunet_2023mar.onnx'))

try:
    from picamera2 import Picamera2
    PICAM2_AVAILABLE = True
except ImportError:
    PICAM2_AVAILABLE = False

class PiCameraStream:
    """Handles camera capture using Picamera2 or OpenCV fallback."""
    def __init__(self, width=320, height=240, fps=15, hflip=True, vflip=False):
        self.width = width
        self.height = height
        self.fps = fps
        self.hflip = hflip
        self.vflip = vflip
        self.use_picam2 = PICAM2_AVAILABLE
        self.picam2 = None
        self.cap = None

        if self.use_picam2:
            try:
                print("[CAM] Initializing Raspberry Pi Camera via Picamera2...")
                self.picam2 = Picamera2()
                frame_us = round(1_000_000 / fps)
                config = self.picam2.create_preview_configuration(
                    main={"size": (width, height), "format": "RGB888"},
                    controls={"FrameDurationLimits": (frame_us, frame_us)},
                    queue=False,
                )
                self.picam2.configure(config)
                self.picam2.start()
                time.sleep(1.0)
                print("[CAM] Picamera2 started successfully.")
            except Exception as e:
                print(f"[CAM WARNING] Picamera2 failed ({e}). Falling back to cv2.VideoCapture...")
                if self.picam2 is not None:
                    self.picam2.close()
                    self.picam2 = None
                self.use_picam2 = False

        if not self.use_picam2:
            print("[CAM] Opening camera via OpenCV VideoCapture(0)...")
            self.cap = cv2.VideoCapture(0)
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
            self.cap.set(cv2.CAP_PROP_FPS, fps)
            self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # Best effort; backend dependent.
            if not self.cap.isOpened():
                self.cap.release()
                raise RuntimeError("Failed to open camera! Check CSI ribbon cable or run 'rpicam-hello'.")

    def read(self):
        if self.use_picam2:
            # Picamera2 RGB888 arrays are BGR byte order, as OpenCV expects.
            # https://datasheets.raspberrypi.com/camera/picamera2-manual.pdf
            frame = self.picam2.capture_array()
            ret = True
        else:
            ret, frame = self.cap.read()
        if ret and frame is not None:
            hflip = getattr(self, 'hflip', False)
            vflip = getattr(self, 'vflip', False)
            if hflip and vflip:
                frame = cv2.flip(frame, -1)
            elif hflip:
                frame = cv2.flip(frame, 1)
            elif vflip:
                frame = cv2.flip(frame, 0)
        return ret, frame

    def release(self):
        if self.use_picam2 and self.picam2 is not None:
            try:
                self.picam2.stop()
            finally:
                self.picam2.close()
        elif self.cap is not None:
            self.cap.release()


# ---------------------------------------------------------------------------
# 3. YUNET FACE DETECTOR (ONNX CPU INFERENCE)
# ---------------------------------------------------------------------------
class FaceDetectorYuNet:
    """Ultra-lightweight (232KB) Face Detector for Raspberry Pi 4 CPU."""
    def __init__(self, model_path=YUNET_MODEL_PATH, conf_threshold=0.6, nms_threshold=0.3,
                 max_input_size=320):
        if max_input_size < 64:
            raise ValueError('Detection input size must be at least 64 pixels')
        self.max_input_size = max_input_size
        self._input_size = None
        if not os.path.exists(model_path):
            raise FileNotFoundError(f"Model file '{model_path}' not found! Run setup_pi.sh to download it.")

        self.detector = cv2.FaceDetectorYN.create(
            model=str(model_path),
            config="",
            input_size=(320, 320),
            score_threshold=conf_threshold,
            nms_threshold=nms_threshold,
            top_k=2000,
            backend_id=cv2.dnn.DNN_BACKEND_OPENCV,
            target_id=cv2.dnn.DNN_TARGET_CPU
        )

    def detect(self, frame):
        h, w = frame.shape[:2]
        t0 = time.perf_counter()
        # Bound inference cost even when a USB camera ignores the requested size.
        scale = min(1.0, self.max_input_size / max(w, h))
        dw, dh = max(1, round(w * scale)), max(1, round(h * scale))
        small = frame if (dw, dh) == (w, h) else cv2.resize(frame, (dw, dh), interpolation=cv2.INTER_AREA)
        if self._input_size != (dw, dh):
            self.detector.setInputSize((dw, dh))
            self._input_size = (dw, dh)
        _, faces = self.detector.detect(small)
        latency_ms = (time.perf_counter() - t0) * 1000

        results = []
        if faces is not None:
            for face in faces:
                sx, sy = w / dw, h / dh
                x, y, bw, bh = [int(round(float(v) * s)) for v, s in zip(face[0:4], (sx, sy, sx, sy))]
                conf = float(face[14])
                landmarks = [(int(round(float(face[i]) * sx)), int(round(float(face[i+1]) * sy)))
                             for i in range(4, 14, 2)]
                results.append({
                    "box": (x, y, bw, bh),
                    "confidence": conf,
                    "landmarks": landmarks
                })
        return results, latency_ms


class FrameRateLimiter:
    """Sleep between loop starts; never burst to catch up after slow inference."""
    def __init__(self, fps, clock=time.monotonic, sleep=time.sleep):
        if not math.isfinite(fps) or fps <= 0:
            raise ValueError('Frame rate must be finite and positive')
        self.period, self.clock, self.sleep = 1.0 / fps, clock, sleep
        self.next_start = clock()

    def wait(self):
        delay = self.next_start - self.clock()
        if delay > 0:
            self.sleep(delay)
        self.next_start = self.clock() + self.period


class ThermalMonitor:
    """Read Pi temperature and firmware flags at most once every ten seconds."""
    def __init__(self):
        self.path = Path('/sys/class/thermal/thermal_zone0/temp')
        self.command = shutil.which('vcgencmd') if sys.platform.startswith('linux') else None
        self.next_read = 0.0

    def report(self, now):
        if now < self.next_read:
            return None
        self.next_read = now + 10.0
        info = []
        try:
            temp = float(self.path.read_text().strip()) / 1000.0
            if math.isfinite(temp):
                info.append(f'CPU {temp:.1f} C')
                if temp >= 75:
                    info.append('HOT: check airflow/cooling; lower --camera-fps and --detect-fps')
        except (OSError, ValueError):
            pass
        if self.command:
            try:
                result = subprocess.run([self.command, 'get_throttled'], capture_output=True,
                                        text=True, timeout=0.25, check=True)
                flags = int(result.stdout.strip().split('=', 1)[1], 16)
                labels = ('undervoltage', 'frequency capped', 'throttled', 'soft temperature limit')
                active = [label for bit, label in enumerate(labels) if flags & (1 << bit)]
                past = [label for bit, label in enumerate(labels) if flags & (1 << (bit + 16))]
                info.append('now: ' + (', '.join(active) or 'no flags'))
                if past:
                    info.append('earlier this boot: ' + ', '.join(past))
            except (OSError, subprocess.SubprocessError, ValueError, IndexError):
                info.append('firmware flags unavailable')
        return '[THERMAL] ' + ' | '.join(info) if info else None


def draw_hud(frame, primary_face, pan_deg, tilt_deg, state_name, fps, latency_ms):
    h, w = frame.shape[:2]
    cx, cy = w // 2, h // 2

    cv2.drawMarker(frame, (cx, cy), (80, 80, 80), cv2.MARKER_CROSS, 20, 1)

    if primary_face:
        x, y, bw, bh = primary_face["box"]
        tcx, tcy = x + bw // 2, y + bh // 2
        color = (0, 255, 0) if state_name == "LOCKED" else (0, 220, 255)
        cv2.rectangle(frame, (x, y), (x + bw, y + bh), color, 2)
        cv2.circle(frame, (tcx, tcy), 4, (0, 0, 255), -1)
        cv2.arrowedLine(frame, (cx, cy), (tcx, tcy), (0, 255, 255), 2, tipLength=0.2)

    cv2.rectangle(frame, (0, 0), (w, 40), (20, 20, 20), -1)
    cv2.putText(frame, f"Pi 4 (2GB) | FPS: {fps:4.1f} | Latency: {latency_ms:4.1f}ms", 
                (10, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 0), 1)

    cv2.rectangle(frame, (0, h - 45), (w, h), (20, 20, 20), -1)
    status_str = f"State: {state_name:8s} | Pan: {pan_deg:5.1f} deg | Tilt: {tilt_deg:5.1f} deg"
    cv2.putText(frame, status_str, (10, h - 16), cv2.FONT_HERSHEY_SIMPLEX, 0.52, (0, 220, 255), 2)

    return frame


class FaceTrackingState:
    """Pure tracking state, shared by the runtime and hardware-free tests."""
    def __init__(self, face_loss_sec=1.5, deadband=0.08):
        if not math.isfinite(face_loss_sec) or face_loss_sec < 0:
            raise ValueError('Face-loss hold must be finite and nonnegative')
        if not math.isfinite(deadband) or not 0 <= deadband < 1:
            raise ValueError('Deadband must be between 0 and 1')
        self.face_loss_sec, self.deadband = face_loss_sec, deadband
        self.last_seen = self.last_update = self.lock_start_time = None
        self.smooth_cx = self.smooth_cy = None
        self.state_name, self.mood = 'SCANNING', 'NEUTRAL'
        self.gaze_x = self.gaze_y = 0.0

    def update(self, faces, width, height, now, invert_gaze_x=False, invert_gaze_y=False):
        dt = 1.0 / 30.0 if self.last_update is None else max(0.0, now - self.last_update)
        self.last_update = now
        self.mood = 'NEUTRAL'
        if not faces:
            self.lock_start_time = None
            if self.last_seen is not None and now - self.last_seen < self.face_loss_sec:
                self.state_name = 'HOLDING'
            else:
                self.state_name = 'SCANNING'
                self.smooth_cx = self.smooth_cy = None
                self.gaze_x, self.gaze_y = math.sin(now * 2.5) * 0.7, 0.0
            return None

        primary_face = max(faces, key=lambda face: face['box'][2] * face['box'][3])
        x, y, box_w, box_h = primary_face['box']
        raw_x, raw_y = x + box_w / 2.0, y + box_h / 2.0
        if self.smooth_cx is None or self.last_seen is None:
            self.smooth_cx, self.smooth_cy = raw_x, raw_y
        else:
            # Two-stage adaptive filter: suppresses camera sensor jitter (< 3px)
            # while providing ultra-smooth, responsive motion for real head movements
            # Keep the same normalized jitter filtering after reducing resolution.
            dist = math.hypot((raw_x - self.smooth_cx) * 640 / width,
                              (raw_y - self.smooth_cy) * 480 / height)
            if dist > 3.0:
                factor = min(1.0, dist / 80.0)
                tc = 0.09 * (1.0 - 0.55 * factor)  # 0.09s for subtle glide, 0.04s for fast tracking
                alpha = 1.0 - math.exp(-min(dt, 0.1) / tc)
                self.smooth_cx += alpha * (raw_x - self.smooth_cx)
                self.smooth_cy += alpha * (raw_y - self.smooth_cy)
        self.last_seen = now
        gx = (self.smooth_cx - width / 2.0) / (width / 2.0)
        gy = (self.smooth_cy - height / 2.0) / (height / 2.0)
        self.gaze_x = -gx if invert_gaze_x else gx
        self.gaze_y = gy if invert_gaze_y else -gy
        if abs(self.gaze_x) <= self.deadband and abs(self.gaze_y) <= self.deadband:
            self.state_name = 'LOCKED'
            if self.lock_start_time is None:
                self.lock_start_time = now
            if now - self.lock_start_time >= 1.0:
                self.mood = 'HAPPY'
        else:
            self.state_name = 'TRACKING'
            self.lock_start_time = None
        return primary_face


def default_headless():
    gui_lines = [line for line in cv2.getBuildInformation().splitlines() if line.strip().startswith('GUI:')]
    no_gui = any('NONE' in line for line in gui_lines)
    return no_gui or (sys.platform.startswith('linux') and not
                      (os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY')))


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description='FORVIZ Raspberry Pi face tracker')
    parser.add_argument('--no-servo', action='store_true', help='Simulate servo angles without GPIO output')
    parser.add_argument('--no-oled', action='store_true', help='Disable physical OLED hardware')
    oled = parser.add_mutually_exclusive_group()
    oled.add_argument('--dual-oled', action='store_true', help='Request two OLEDs; fall back to available screens')
    oled.add_argument('--single-oled', action='store_true', help='Use one OLED, rendering both eyes on it')
    oled.add_argument('--mirror-eye', '--single-eye', dest='mirror_eye', action='store_true', help='Render ONE big centered eye (use when both OLEDs share Pin 3 and Pin 5 on 0x3C)')
    parser.add_argument('--oled-rotate', type=int, default=DEFAULT_OLED_ROTATION,
                        choices=[0, 90, 180, 270],
                        help='Rotate all OLED displays (default: 180 for the installed panels)')
    parser.add_argument('--oled1-rotate', type=int, default=None, choices=[0, 90, 180, 270],
                        help='Rotate screen 1 specifically (0, 90, 180, or 270 degrees)')
    parser.add_argument('--oled2-rotate', type=int, default=None, choices=[0, 90, 180, 270],
                        help='Rotate screen 2 specifically (0, 90, 180, or 270 degrees)')
    display = parser.add_mutually_exclusive_group()
    display.add_argument('--headless', action='store_true', help='Disable OpenCV preview')
    display.add_argument('--preview', action='store_true', help='Request OpenCV preview on a desktop')
    parser.add_argument('--model', default=YUNET_MODEL_PATH, help='YuNet ONNX model path')
    parser.add_argument('--camera-width', type=int, default=320, help='Requested camera width (default: 320)')
    parser.add_argument('--camera-height', type=int, default=240, help='Requested camera height (default: 240)')
    parser.add_argument('--camera-fps', type=float, default=15, help='Requested camera frame rate (default: 15)')
    parser.add_argument('--detect-fps', type=float, default=15, help='Maximum detection/servo loop rate (default: 15)')
    parser.add_argument('--detect-size', type=int, default=320, help='Maximum inference image dimension (default: 320)')
    parser.add_argument('--cv-threads', type=int, default=1, help='OpenCV worker threads (default: 1)')
    parser.add_argument('--no-hflip', dest='hflip', action='store_false', default=True,
                        help='Disable horizontal camera flip (mirror preview)')
    parser.add_argument('--hflip', dest='hflip', action='store_true', default=True,
                        help='Horizontally flip camera for natural mirror view (default: True)')
    parser.add_argument('--vflip', action='store_true', default=False,
                        help='Enable vertical camera flip (default: False)')
    parser.add_argument('--pan-pin', type=int, default=12)
    parser.add_argument('--tilt-pin', type=int, default=19)
    parser.add_argument('--pan-min', type=float, default=40)
    parser.add_argument('--pan-max', type=float, default=140)
    parser.add_argument('--tilt-min', type=float, default=65)
    parser.add_argument('--tilt-max', type=float, default=115)
    parser.add_argument('--invert-tilt', action='store_true', help='Invert vertical tilt servo (Up <-> Down)')
    parser.add_argument('--invert-pan', action='store_true', help='Invert horizontal pan servo (Left <-> Right)')
    parser.add_argument('--invert-gaze-y', action='store_true', help='Invert eye pupil vertical gaze')
    parser.add_argument('--invert-gaze-x', action='store_true', help='Invert eye pupil horizontal gaze')
    parser.add_argument('--invert-y', action='store_true', help='Invert both vertical tilt servo and eye gaze')
    parser.add_argument('--pan-center', type=float, default=90)
    parser.add_argument('--tilt-center', type=float, default=90)
    parser.add_argument('--servo-speed', type=float, default=120, help='Maximum servo speed in degrees/second (fast & smooth)')
    parser.add_argument('--gain-pan', type=float, default=140.0, help='Pan tracking sensitivity')
    parser.add_argument('--gain-tilt', type=float, default=110.0, help='Tilt tracking sensitivity')
    parser.add_argument('--reverse-pan', action='store_true', help='Reverse horizontal pan servo direction')
    parser.add_argument('--reverse-tilt', action='store_true', help='Reverse vertical tilt servo direction')
    parser.add_argument('--scan-speed', type=float, default=18, help='Pan scan speed in degrees/second')
    parser.add_argument('--face-loss-sec', type=float, default=1.5, help='Hold position before resuming scan')
    parser.add_argument('--idle-detach-after', type=float, default=None,
                        help='Optional idle PWM timeout in seconds; releases head holding torque')
    args = parser.parse_args(argv)
    try:
        if not all(64 <= value <= 4096 for value in (args.camera_width, args.camera_height, args.detect_size)):
            raise ValueError('Camera and detection dimensions must be between 64 and 4096 pixels')
        if not all(math.isfinite(value) and 1 <= value <= 60 for value in (args.camera_fps, args.detect_fps)):
            raise ValueError('Camera and detection rates must be between 1 and 60 FPS')
        if not 1 <= args.cv_threads <= 16:
            raise ValueError('OpenCV threads must be between 1 and 16')
        for axis in ('pan', 'tilt'):
            low, high = PanTiltTracker._validate_range((getattr(args, axis + '_min'), getattr(args, axis + '_max')))
            center = getattr(args, axis + '_center')
            if not math.isfinite(center) or not low <= center <= high:
                raise ValueError(f'{axis} center must be within its limits')
        for value in (args.servo_speed, args.scan_speed):
            if not math.isfinite(value) or value <= 0:
                raise ValueError('Servo and scan speeds must be finite and positive')
        if args.idle_detach_after is not None and (not math.isfinite(args.idle_detach_after) or args.idle_detach_after <= 0):
            raise ValueError('Idle detach timeout must be finite and positive')
        if not math.isfinite(args.face_loss_sec) or args.face_loss_sec < 0:
            raise ValueError('Face-loss hold must be finite and nonnegative')
        if not 0 <= args.pan_pin <= 27 or not 0 <= args.tilt_pin <= 27 or args.pan_pin == args.tilt_pin:
            raise ValueError('Use two distinct BCM GPIO pins between 0 and 27')
    except ValueError as exc:
        parser.error(str(exc))
    return args


def main(argv=None):
    args = parse_args(argv)
    headless = args.headless or (not args.preview and default_headless())
    print('FORVIZ - Raspberry Pi face tracking robot')
    if headless:
        print('[INFO] Headless telemetry active. Use Ctrl+C to stop.')
    print(f'[SERVOS] Limits: pan {args.pan_min:g}..{args.pan_max:g}, tilt {args.tilt_min:g}..{args.tilt_max:g} degrees')
    camera = tracker = face_display = None
    try:
        cv2.setNumThreads(args.cv_threads)
        print(f'[PERF] Camera {args.camera_width}x{args.camera_height} @ {args.camera_fps:g} FPS; '
              f'detection <= {min(args.detect_fps, args.camera_fps):g} FPS, max {args.detect_size}px; '
              f'OpenCV threads={args.cv_threads}')
        detector = FaceDetectorYuNet(args.model, max_input_size=args.detect_size)
        camera = PiCameraStream(width=args.camera_width, height=args.camera_height, fps=args.camera_fps,
                                hflip=args.hflip, vflip=args.vflip)
        # Defaults are inverted to match the physical Pan/Tilt gimbal assembly:
        # Face UP -> Head UP, Face DOWN -> Head DOWN, Face LEFT -> Head LEFT, Face RIGHT -> Head RIGHT
        invert_tilt = False if args.reverse_tilt else True
        invert_pan = False if args.reverse_pan else True
        invert_gaze_y = args.invert_gaze_y or args.invert_y
        invert_gaze_x = args.invert_gaze_x

        tracker = PanTiltTracker(
            pan_pin=args.pan_pin, tilt_pin=args.tilt_pin,
            pan_range=(args.pan_min, args.pan_max), tilt_range=(args.tilt_min, args.tilt_max),
            pan_center=args.pan_center, tilt_center=args.tilt_center,
            max_speed_deg_per_sec=args.servo_speed, scan_speed_deg_per_sec=args.scan_speed,
            idle_timeout_sec=args.idle_detach_after, hardware=not args.no_servo,
            invert_pan=invert_pan, invert_tilt=invert_tilt)
        if not args.no_oled:
            mode = False if args.single_oled else (True if args.dual_oled else None)
            face_display = OLEDDisplayController(
                dual_screen=mode,
                rotate=args.oled_rotate,
                rotate_1=args.oled1_rotate,
                rotate_2=args.oled2_rotate,
                single_eye=args.mirror_eye,
            )
            face_display.start()
        state = FaceTrackingState(face_loss_sec=args.face_loss_sec)
        prev_time, last_telemetry = time.monotonic(), 0.0
        fps = 0.0
        limiter = FrameRateLimiter(min(args.detect_fps, args.camera_fps))
        thermal = ThermalMonitor()
        while True:
            limiter.wait()
            ret, frame = camera.read()
            if not ret:
                print('[ERROR] Camera stream interrupted.')
                break
            height, width = frame.shape[:2]
            faces, latency_ms = detector.detect(frame)
            now = time.monotonic()
            dt, prev_time = now - prev_time, now
            if dt > 0:
                fps = 0.85 * fps + 0.15 / dt if fps > 0 else 1.0 / dt
            primary_face = state.update(faces, width, height, now, invert_gaze_x=invert_gaze_x, invert_gaze_y=invert_gaze_y)
            if primary_face is not None:
                pan, tilt = tracker.track_face(state.smooth_cx, state.smooth_cy, width, height, state.deadband, gain_pan=args.gain_pan, gain_tilt=args.gain_tilt)
            elif state.state_name == 'HOLDING':
                pan, tilt = tracker.hold()
            else:
                pan, tilt = tracker.step_scan()
            if face_display:
                face_display.set_expression(state.mood, state.gaze_x, state.gaze_y)
            thermal_status = thermal.report(now)
            if thermal_status:
                print(thermal_status)
            if not headless:
                try:
                    cv2.imshow('FORVIZ Robot Tracker', draw_hud(frame, primary_face, pan, tilt, state.state_name, fps, latency_ms))
                    if cv2.waitKey(1) & 0xFF in (ord('q'), 27):
                        break
                except cv2.error as exc:
                    print(f'[PREVIEW WARNING] Preview unavailable; continuing headless: {exc}')
                    headless = True
            elif now - last_telemetry >= 0.5:
                print(f'FPS {fps:4.1f} | {state.state_name:8s} | Pan {pan:5.1f} | Tilt {tilt:5.1f}')
                last_telemetry = now
    except KeyboardInterrupt:
        print('[STOP] Stopping robot...')
    finally:
        # No automatic center jump: release motion at its current position.
        for resource, method in ((tracker, 'close'), (face_display, 'stop'), (camera, 'release')):
            if resource is not None:
                try:
                    getattr(resource, method)()
                except Exception as exc:
                    print(f'[CLEANUP WARNING] {method}: {exc}')
        if not headless:
            cv2.destroyAllWindows()
        print('Robot shut down; servo PWM released.')


if __name__ == '__main__':
    main()
