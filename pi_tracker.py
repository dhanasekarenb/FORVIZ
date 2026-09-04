"""
Raspberry Pi 4 AI Face Tracker with Dual SG90 Servos & SSD1306 OLED Expressive Eyes
===================================================================================
All-In-One Self-Contained Script.
Dependencies:
  - opencv, numpy, picamera2 (Vision)
  - gpiozero, pigpio (SG90 Servos on GPIO 18 & 13)
  - Pillow, luma.oled (SSD1306 128x64 OLED Animated Eyes)
"""

import cv2
import time
import numpy as np
import os
import sys
import math
import argparse
import threading
from PIL import Image, ImageDraw

# Model file path
YUNET_MODEL_PATH = "face_detection_yunet_2023mar.onnx"

# ---------------------------------------------------------------------------
# 1. OPTIONAL HARDWARE DRIVER IMPORTS (GRACEFUL FALLBACKS)
# ---------------------------------------------------------------------------
try:
    from picamera2 import Picamera2
    PICAM2_AVAILABLE = True
except ImportError:
    PICAM2_AVAILABLE = False

try:
    from gpiozero import AngularServo
    from gpiozero.pins.pigpio import PiGPIOFactory
    GPIOZERO_AVAILABLE = True
except ImportError:
    GPIOZERO_AVAILABLE = False

try:
    from luma.core.interface.serial import i2c
    from luma.oled.device import ssd1306
    LUMA_AVAILABLE = True
except ImportError:
    LUMA_AVAILABLE = False


# ---------------------------------------------------------------------------
# 2. CAMERA STREAM (PICAMERA2 / OPENCV)
# ---------------------------------------------------------------------------
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
                self.use_picam2 = False

        if not self.use_picam2:
            print("[CAM] Opening camera via OpenCV VideoCapture(0)...")
            self.cap = cv2.VideoCapture(0)
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
            if not self.cap.isOpened():
                raise RuntimeError("Failed to open camera! Check CSI rib cable or run 'rpicam-hello'.")

    def read(self):
        if self.use_picam2:
            frame_rgb = self.picam2.capture_array()
            frame_bgr = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)
            return True, frame_bgr
        else:
            ret, frame = self.cap.read()
            return ret, frame

    def release(self):
        if self.use_picam2 and self.picam2 is not None:
            self.picam2.stop()
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
            model=model_path,
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


# ---------------------------------------------------------------------------
# 4. SERVO CONTROLLER (SG90 PAN & TILT)
# ---------------------------------------------------------------------------
class DummyServo:
    def __init__(self, name):
        self.name = name
        self.angle = 90.0

    def set_angle(self, angle):
        self.angle = angle

    def close(self):
        pass


class PanTiltTracker:
    """Controls Pan (GPIO 18) and Tilt (GPIO 13) SG90 servos with auto-sweep."""
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

        self.scan_direction = 1
        self.scan_speed = 1.2
        self.last_face_time = time.time()
        self.scan_delay_sec = 1.5

        self.hardware_active = False

        if GPIOZERO_AVAILABLE:
            try:
                factory = None
                if use_hardware_pwm:
                    try:
                        factory = PiGPIOFactory()
                    except Exception:
                        factory = None

                self.pan_servo = AngularServo(
                    self.pan_pin,
                    min_angle=0, max_angle=180,
                    min_pulse_width=0.0005, max_pulse_width=0.0024,
                    pin_factory=factory
                )
                self.tilt_servo = AngularServo(
                    self.tilt_pin,
                    min_angle=0, max_angle=180,
                    min_pulse_width=0.0005, max_pulse_width=0.0024,
                    pin_factory=factory
                )
                self.hardware_active = True
                self.pan_servo.angle = self.current_pan
                self.tilt_servo.angle = self.current_tilt
                print(f"[SERVOS] Active: Pan(GPIO {pan_pin}), Tilt(GPIO {tilt_pin})")
            except Exception as e:
                print(f"[SERVOS WARNING] Init failed ({e}). Running in simulation mode.")
                self.pan_servo = DummyServo("PAN")
                self.tilt_servo = DummyServo("TILT")
        else:
            print("[SERVOS INFO] 'gpiozero' not installed. Running in simulation mode.")
            self.pan_servo = DummyServo("PAN")
            self.tilt_servo = DummyServo("TILT")

    def track_face(self, target_cx, target_cy, frame_width=640, frame_height=480, smoothing=0.18):
        self.last_face_time = time.time()
        norm_dx = (target_cx - (frame_width / 2.0)) / (frame_width / 2.0)
        norm_dy = (target_cy - (frame_height / 2.0)) / (frame_height / 2.0)

        deadband = 0.06
        if abs(norm_dx) < deadband:
            norm_dx = 0.0
        if abs(norm_dy) < deadband:
            norm_dy = 0.0

        pan_step = -norm_dx * 3.5
        tilt_step = norm_dy * 2.8

        self.target_pan = max(self.pan_min, min(self.pan_max, self.current_pan + pan_step))
        self.target_tilt = max(self.tilt_min, min(self.tilt_max, self.current_tilt + tilt_step))

        self.current_pan += (self.target_pan - self.current_pan) * smoothing
        self.current_tilt += (self.target_tilt - self.current_tilt) * smoothing

        self._apply_angles()
        return self.current_pan, self.current_tilt

    def step_scan(self):
        if (time.time() - self.last_face_time) < self.scan_delay_sec:
            return self.current_pan, self.current_tilt

        self.current_pan += self.scan_direction * self.scan_speed
        if self.current_pan >= self.pan_max:
            self.current_pan = self.pan_max
            self.scan_direction = -1
        elif self.current_pan <= self.pan_min:
            self.current_pan = self.pan_min
            self.scan_direction = 1

        self.current_tilt = 85.0
        self._apply_angles()
        return self.current_pan, self.current_tilt

    def set_direct(self, pan_deg, tilt_deg):
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
        self.set_direct(90, 90)

    def close(self):
        if self.hardware_active:
            try:
                self.pan_servo.close()
                self.tilt_servo.close()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# 5. OLED DISPLAY ANIMATED EYES (SSD1306)
# ---------------------------------------------------------------------------
class RobotEyesRenderer:
    def __init__(self, width=128, height=64):
        self.w = width
        self.h = height

    def render_single_screen(self, mood="NEUTRAL", gaze_x=0.0, gaze_y=0.0, blink_pct=0.0):
        image = Image.new("1", (self.w, self.h), 0)
        draw = ImageDraw.Draw(image)
        eye_w, eye_h = 32, 42
        eye_spacing = 18
        cy = self.h // 2
        left_cx = (self.w // 2) - (eye_spacing // 2) - (eye_w // 2)
        right_cx = (self.w // 2) + (eye_spacing // 2) + (eye_w // 2)

        self._draw_eye(draw, left_cx, cy, eye_w, eye_h, mood, gaze_x, gaze_y, blink_pct, is_left=True)
        self._draw_eye(draw, right_cx, cy, eye_w, eye_h, mood, gaze_x, gaze_y, blink_pct, is_left=False)
        return image

    def render_dual_screen(self, mood="NEUTRAL", gaze_x=0.0, gaze_y=0.0, blink_pct=0.0):
        img_left = Image.new("1", (self.w, self.h), 0)
        img_right = Image.new("1", (self.w, self.h), 0)
        draw_l = ImageDraw.Draw(img_left)
        draw_r = ImageDraw.Draw(img_right)
        eye_w, eye_h = 64, 50
        cx, cy = self.w // 2, self.h // 2

        self._draw_eye(draw_l, cx, cy, eye_w, eye_h, mood, gaze_x, gaze_y, blink_pct, is_left=True)
        self._draw_eye(draw_r, cx, cy, eye_w, eye_h, mood, gaze_x, gaze_y, blink_pct, is_left=False)
        return img_left, img_right

    def _draw_eye(self, draw, cx, cy, w, h, mood, gaze_x, gaze_y, blink_pct, is_left):
        if mood == "HAPPY":
            line_w = 4 if w > 40 else 3
            bbox = [cx - w // 2, cy - h // 3, cx + w // 2, cy + h // 3]
            draw.arc(bbox, start=190, end=350, fill=1, width=line_w)
            blush_x = cx - 10 if is_left else cx + 2
            draw.line([blush_x, cy + h // 3 + 4, blush_x + 8, cy + h // 3 + 4], fill=1, width=2)
            return

        if mood == "HEART":
            r = w // 4
            draw.ellipse([cx - r, cy - r, cx, cy], fill=1)
            draw.ellipse([cx, cy - r, cx + r, cy], fill=1)
            poly = [(cx - r, cy - r // 3), (cx + r, cy - r // 3), (cx, cy + r)]
            draw.polygon(poly, fill=1)
            return

        current_h = int(h * (1.0 - blink_pct))
        if current_h <= 3:
            draw.line([cx - w // 2, cy, cx + w // 2, cy], fill=1, width=2)
            return

        rx = 8 if w > 40 else 6
        x0, y0 = cx - w // 2, cy - current_h // 2
        x1, y1 = cx + w // 2, cy + current_h // 2
        draw.rounded_rectangle([x0, y0, x1, y1], radius=rx, fill=1, outline=1)

        if blink_pct < 0.6:
            pupil_w = int(w * 0.42)
            pupil_h = int(current_h * 0.55)
            max_offset_x = (w - pupil_w) // 2 - 2
            max_offset_y = (current_h - pupil_h) // 2 - 2

            px = cx + int(gaze_x * max_offset_x)
            py = cy + int(gaze_y * max_offset_y)

            draw.rounded_rectangle(
                [px - pupil_w // 2, py - pupil_h // 2, px + pupil_w // 2, py + pupil_h // 2],
                radius=4, fill=0
            )

            dot_r = 3 if w > 40 else 2
            dot_x = px - pupil_w // 4
            dot_y = py - pupil_h // 4
            draw.ellipse([dot_x - dot_r, dot_y - dot_r, dot_x + dot_r, dot_y + dot_r], fill=1)


class OLEDDisplayController:
    """Controls 1 or 2 SSD1306 OLED displays in a non-blocking background thread."""
    def __init__(self, dual_screen=False, port_1=1, addr_1=0x3C, port_2=3, addr_2=0x3C):
        self.dual_screen = dual_screen
        self.renderer = RobotEyesRenderer(128, 64)
        self.dev1 = None
        self.dev2 = None

        self.current_mood = "NEUTRAL"
        self.gaze_x = 0.0
        self.gaze_y = 0.0
        self.running = False
        self.thread = None

        if LUMA_AVAILABLE:
            try:
                serial1 = i2c(port=port_1, address=addr_1)
                self.dev1 = ssd1306(serial1)
                print(f"[OLED] Screen 1 initialized (I2C Bus {port_1}, Addr 0x{addr_1:X})")

                if dual_screen:
                    try:
                        serial2 = i2c(port=port_2, address=addr_2)
                        self.dev2 = ssd1306(serial2)
                        print(f"[OLED] Screen 2 initialized (I2C Bus {port_2}, Addr 0x{addr_2:X})")
                    except Exception as e:
                        print(f"[OLED WARNING] Screen 2 failed ({e}). Reverting to 1 screen.")
                        self.dual_screen = False
            except Exception as e:
                print(f"[OLED WARNING] OLED hardware init failed ({e}). Running headless.")
        else:
            print("[OLED INFO] 'luma.oled' not installed. Running without physical display.")

    def set_expression(self, mood="NEUTRAL", gaze_x=0.0, gaze_y=0.0):
        self.current_mood = mood
        self.gaze_x = max(-1.0, min(1.0, gaze_x))
        self.gaze_y = max(-1.0, min(1.0, gaze_y))

    def start(self):
        self.running = True
        self.thread = threading.Thread(target=self._animation_loop, daemon=True)
        self.thread.start()

    def _animation_loop(self):
        last_blink_time = time.time()
        blink_interval = 3.5
        blink_duration = 0.18

        while self.running:
            now = time.time()
            elapsed_blink = now - last_blink_time

            blink_pct = 0.0
            if elapsed_blink > blink_interval:
                t = (elapsed_blink - blink_interval) / blink_duration
                if t <= 0.5:
                    blink_pct = t * 2.0
                elif t <= 1.0:
                    blink_pct = (1.0 - t) * 2.0
                else:
                    last_blink_time = now
                    blink_interval = 2.5 + (hash(str(now)) % 30) / 10.0

            if self.dual_screen and self.dev1 and self.dev2:
                img_l, img_r = self.renderer.render_dual_screen(
                    self.current_mood, self.gaze_x, self.gaze_y, blink_pct
                )
                self.dev1.display(img_l)
                self.dev2.display(img_r)
            elif self.dev1:
                img = self.renderer.render_single_screen(
                    self.current_mood, self.gaze_x, self.gaze_y, blink_pct
                )
                self.dev1.display(img)

            time.sleep(0.04)

    def stop(self):
        self.running = False
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=1.0)
        if self.dev1:
            try:
                self.dev1.clear()
            except Exception:
                pass
        if self.dev2:
            try:
                self.dev2.clear()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# 6. HUD OVERLAY
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# 7. MAIN CONTROL LOOP
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Raspberry Pi 4 AI Face Tracking Robot")
    parser.add_argument("--no-servo", action="store_true", help="Disable physical servo hardware")
    parser.add_argument("--no-oled", action="store_true", help="Disable physical OLED hardware")
    parser.add_argument("--dual-oled", action="store_true", help="Enable 2x OLED screen mode")
    parser.add_argument("--pan-pin", type=int, default=18, help="GPIO pin for Pan servo (default: 18)")
    parser.add_argument("--tilt-pin", type=int, default=13, help="GPIO pin for Tilt servo (default: 13)")
    args = parser.parse_args()

    print("=" * 65)
    print("      FORVIZ - RASPBERRY PI 4 AI FACE TRACKING ROBOT")
    print("=" * 65)

    headless = os.environ.get("DISPLAY") is None
    if headless:
        print("[INFO] Headless mode (no monitor connected). Streaming telemetry.")

    detector = FaceDetectorYuNet(YUNET_MODEL_PATH)
    print("[AI] YuNet Face Detector loaded.")

    camera = PiCameraStream(width=640, height=480, fps=30)

    tracker = None
    if not args.no_servo:
        tracker = PanTiltTracker(pan_pin=args.pan_pin, tilt_pin=args.tilt_pin)
        tracker.center()
    else:
        print("[SERVOS] Disabled via --no-servo.")

    face_display = None
    if not args.no_oled:
        face_display = OLEDDisplayController(dual_screen=args.dual_oled)
        face_display.start()
        face_display.set_expression("NEUTRAL", 0.0, 0.0)
    else:
        print("[OLED] Disabled via --no-oled.")

    prev_time = time.time()
    fps = 0.0
    pan_deg, tilt_deg = 90.0, 90.0
    state_name = "SCANNING"
    lock_start_time = None

    try:
        while True:
            ret, frame = camera.read()
            if not ret:
                print("[ERROR] Camera stream interrupted.")
                break

            h, w = frame.shape[:2]
            cx, cy = w // 2, h // 2

            curr_time = time.time()
            dt = curr_time - prev_time
            prev_time = curr_time
            if dt > 0:
                fps = 0.85 * fps + 0.15 * (1.0 / dt) if fps > 0 else (1.0 / dt)

            faces, latency_ms = detector.detect(frame)
            primary_face = None

            if faces:
                faces.sort(key=lambda f: f["box"][2] * f["box"][3], reverse=True)
                primary_face = faces[0]

                x, y, bw, bh = primary_face["box"]
                target_cx, target_cy = x + bw // 2, y + bh // 2

                norm_x = (target_cx - cx) / (w / 2.0)
                norm_y = (target_cy - cy) / (h / 2.0)

                if abs(norm_x) < 0.12 and abs(norm_y) < 0.12:
                    state_name = "LOCKED"
                    if lock_start_time is None:
                        lock_start_time = time.time()
                    
                    if (time.time() - lock_start_time) > 1.2:
                        if face_display:
                            face_display.set_expression("HAPPY", 0.0, 0.0)
                    else:
                        if face_display:
                            face_display.set_expression("NEUTRAL", norm_x * 0.8, norm_y * 0.8)
                else:
                    state_name = "TRACKING"
                    lock_start_time = None
                    if face_display:
                        face_display.set_expression("NEUTRAL", norm_x * 0.9, norm_y * 0.9)

                if tracker:
                    pan_deg, tilt_deg = tracker.track_face(target_cx, target_cy, w, h)

            else:
                state_name = "SCANNING"
                lock_start_time = None

                if tracker:
                    pan_deg, tilt_deg = tracker.step_scan()

                if face_display:
                    scan_gaze = math.sin(time.time() * 2.5) * 0.7
                    face_display.set_expression("NEUTRAL", gaze_x=scan_gaze, gaze_y=0.0)

            if not headless:
                hud = draw_hud(frame, primary_face, pan_deg, tilt_deg, state_name, fps, latency_ms)
                cv2.imshow("Raspberry Pi 4 - Robot Tracker", hud)
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    break
            else:
                print(f"\r[FPS: {fps:4.1f}] State: {state_name:8s} | Pan: {pan_deg:5.1f} deg | Tilt: {tilt_deg:5.1f} deg | Face: {'YES' if primary_face else 'NO '}", end="", flush=True)

    except KeyboardInterrupt:
        print("\n[STOP] Stopping robot...")
    finally:
        if tracker:
            tracker.center()
            time.sleep(0.3)
            tracker.close()
        if face_display:
            face_display.stop()
        camera.release()
        if not headless:
            cv2.destroyAllWindows()
        print("Robot gracefully shut down.")


if __name__ == "__main__":
    main()
