"""FORVIZ face tracker using shared servo and OLED controllers.

Pan GPIO 12, tilt GPIO 19; OLED bus 1 and optional software bus 3.
Use --help for hardware-disable, display and mechanical calibration options.
"""
import argparse
import math
import os
from pathlib import Path
import sys
import time

import cv2
from servos import PanTiltTracker
from oled_face import OLEDDisplayController, RobotEyesRenderer

YUNET_MODEL_PATH = str(Path(__file__).resolve().with_name('face_detection_yunet_2023mar.onnx'))

try:
    from picamera2 import Picamera2
    PICAM2_AVAILABLE = True
except ImportError:
    PICAM2_AVAILABLE = False

class PiCameraStream:
    """Handles camera capture using Picamera2 or OpenCV fallback."""
    def __init__(self, width=640, height=480, fps=30):
        self.width = width
        self.height = height
        self.fps = fps
        self.use_picam2 = PICAM2_AVAILABLE
        self.picam2 = None
        self.cap = None

        if self.use_picam2:
            try:
                print("[CAM] Initializing Raspberry Pi Camera via Picamera2...")
                self.picam2 = Picamera2()
                config = self.picam2.create_preview_configuration(main={"size": (width, height), "format": "RGB888"})
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
            if not self.cap.isOpened():
                self.cap.release()
                raise RuntimeError("Failed to open camera! Check CSI ribbon cable or run 'rpicam-hello'.")

    def read(self):
        if self.use_picam2:
            # Picamera2 RGB888 arrays are BGR byte order, as OpenCV expects.
            # https://datasheets.raspberrypi.com/camera/picamera2-manual.pdf
            return True, self.picam2.capture_array()
        else:
            ret, frame = self.cap.read()
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
    def __init__(self, model_path=YUNET_MODEL_PATH, conf_threshold=0.6, nms_threshold=0.3):
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
        self.detector.setInputSize((w, h))
        t0 = time.perf_counter()
        _, faces = self.detector.detect(frame)
        latency_ms = (time.perf_counter() - t0) * 1000

        results = []
        if faces is not None:
            for face in faces:
                x, y, bw, bh = map(int, face[0:4])
                conf = float(face[14])
                landmarks = [(int(face[i]), int(face[i+1])) for i in range(4, 14, 2)]
                results.append({
                    "box": (x, y, bw, bh),
                    "confidence": conf,
                    "landmarks": landmarks
                })
        return results, latency_ms


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

    def update(self, faces, width, height, now):
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
            # Time-constant smoothing keeps the response comparable at different FPS.
            alpha = 1.0 - math.exp(-min(dt, 0.1) / 0.08)
            self.smooth_cx += alpha * (raw_x - self.smooth_cx)
            self.smooth_cy += alpha * (raw_y - self.smooth_cy)
        self.last_seen = now
        self.gaze_x = (self.smooth_cx - width / 2.0) / (width / 2.0)
        self.gaze_y = (self.smooth_cy - height / 2.0) / (height / 2.0)
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
    display = parser.add_mutually_exclusive_group()
    display.add_argument('--headless', action='store_true', help='Disable OpenCV preview')
    display.add_argument('--preview', action='store_true', help='Request OpenCV preview on a desktop')
    parser.add_argument('--model', default=YUNET_MODEL_PATH, help='YuNet ONNX model path')
    parser.add_argument('--pan-pin', type=int, default=12)
    parser.add_argument('--tilt-pin', type=int, default=19)
    parser.add_argument('--pan-min', type=float, default=40)
    parser.add_argument('--pan-max', type=float, default=140)
    parser.add_argument('--tilt-min', type=float, default=65)
    parser.add_argument('--tilt-max', type=float, default=115)
    parser.add_argument('--pan-center', type=float, default=90)
    parser.add_argument('--tilt-center', type=float, default=90)
    parser.add_argument('--servo-speed', type=float, default=36, help='Maximum servo speed in degrees/second')
    parser.add_argument('--scan-speed', type=float, default=18, help='Pan scan speed in degrees/second')
    parser.add_argument('--face-loss-sec', type=float, default=1.5, help='Hold position before resuming scan')
    parser.add_argument('--idle-detach-after', type=float, default=None,
                        help='Optional idle PWM timeout in seconds; releases head holding torque')
    args = parser.parse_args(argv)
    try:
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
        detector = FaceDetectorYuNet(args.model)
        camera = PiCameraStream(width=640, height=480, fps=30)
        tracker = PanTiltTracker(
            pan_pin=args.pan_pin, tilt_pin=args.tilt_pin,
            pan_range=(args.pan_min, args.pan_max), tilt_range=(args.tilt_min, args.tilt_max),
            pan_center=args.pan_center, tilt_center=args.tilt_center,
            max_speed_deg_per_sec=args.servo_speed, scan_speed_deg_per_sec=args.scan_speed,
            idle_timeout_sec=args.idle_detach_after, hardware=not args.no_servo)
        if not args.no_oled:
            mode = False if args.single_oled else (True if args.dual_oled else None)
            face_display = OLEDDisplayController(dual_screen=mode)
            face_display.start()
        state = FaceTrackingState(face_loss_sec=args.face_loss_sec)
        prev_time, last_telemetry = time.monotonic(), 0.0
        fps = 0.0
        while True:
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
            primary_face = state.update(faces, width, height, now)
            if primary_face is not None:
                pan, tilt = tracker.track_face(state.smooth_cx, state.smooth_cy, width, height, state.deadband)
            elif state.state_name == 'HOLDING':
                pan, tilt = tracker.hold()
            else:
                pan, tilt = tracker.step_scan()
            if face_display:
                face_display.set_expression(state.mood, state.gaze_x, state.gaze_y)
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
