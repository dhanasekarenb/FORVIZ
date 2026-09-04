"""
Raspberry Pi 4 AI Face Tracker with Dual SG90 Servos & SSD1306 OLED Expressive Eyes
===================================================================================
Pipeline:
  1. Camera: Raspberry Pi Camera Rev 1.3 (via Picamera2 / OpenCV)
  2. Detector: YuNet ONNX (FaceDetectorYN) - ultra-fast ARM CPU inference
  3. Actuators: 2x SG90 Servos (Pan on GPIO 18, Tilt on GPIO 13)
  4. Display: 1x or 2x 0.96-inch SSD1306 I2C OLED (Expressive Animated Eyes)
"""

import cv2
import time
import numpy as np
import os
import sys
import math
import argparse

# Submodules
from servos import PanTiltTracker
from oled_face import OLEDDisplayController

# Model file path
YUNET_MODEL_PATH = "face_detection_yunet_2023mar.onnx"

# Try importing Picamera2
try:
    from picamera2 import Picamera2
    PICAM2_AVAILABLE = True
except ImportError:
    PICAM2_AVAILABLE = False


class PiCameraStream:
    """Handles camera capture using Picamera2 (recommended for Pi Camera Rev 1.3) or OpenCV fallback."""
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


class FaceDetectorYuNet:
    """Ultra-lightweight (232KB) Face Detector for Raspberry Pi 4 CPU."""
    def __init__(self, model_path=YUNET_MODEL_PATH, conf_threshold=0.6, nms_threshold=0.3):
        if not os.path.exists(model_path):
            raise FileNotFoundError(f"Model file '{model_path}' not found!")

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


def draw_hud(frame, primary_face, pan_deg, tilt_deg, state_name, fps, latency_ms):
    h, w = frame.shape[:2]
    cx, cy = w // 2, h // 2

    # Center crosshair & deadband
    cv2.drawMarker(frame, (cx, cy), (80, 80, 80), cv2.MARKER_CROSS, 20, 1)

    if primary_face:
        x, y, bw, bh = primary_face["box"]
        tcx, tcy = x + bw // 2, y + bh // 2
        color = (0, 255, 0) if state_name == "LOCKED" else (0, 220, 255)
        cv2.rectangle(frame, (x, y), (x + bw, y + bh), color, 2)
        cv2.circle(frame, (tcx, tcy), 4, (0, 0, 255), -1)
        cv2.arrowedLine(frame, (cx, cy), (tcx, tcy), (0, 255, 255), 2, tipLength=0.2)

    # Top stats
    cv2.rectangle(frame, (0, 0), (w, 40), (20, 20, 20), -1)
    cv2.putText(frame, f"Pi 4 (2GB) | FPS: {fps:4.1f} | Latency: {latency_ms:4.1f}ms", 
                (10, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 0), 1)

    # Bottom actuators & state
    cv2.rectangle(frame, (0, h - 45), (w, h), (20, 20, 20), -1)
    status_str = f"State: {state_name:8s} | Pan: {pan_deg:5.1f} deg | Tilt: {tilt_deg:5.1f} deg"
    cv2.putText(frame, status_str, (10, h - 16), cv2.FONT_HERSHEY_SIMPLEX, 0.52, (0, 220, 255), 2)

    return frame


def main():
    parser = argparse.ArgumentParser(description="Raspberry Pi 4 AI Face Tracking Robot")
    parser.add_argument("--no-servo", action="store_true", help="Disable physical servo hardware")
    parser.add_argument("--no-oled", action="store_true", help="Disable physical OLED hardware")
    parser.add_argument("--dual-oled", action="store_true", help="Enable 2x OLED screen mode (Left & Right eyes)")
    parser.add_argument("--pan-pin", type=int, default=18, help="GPIO pin for Pan servo (default: 18)")
    parser.add_argument("--tilt-pin", type=int, default=13, help="GPIO pin for Tilt servo (default: 13)")
    args = parser.parse_args()

    print("=" * 65)
    print("      FORVIZ - RASPBERRY PI 4 AI FACE TRACKING ROBOT")
    print("=" * 65)

    headless = os.environ.get("DISPLAY") is None
    if headless:
        print("[INFO] Headless mode (no monitor connected). Streaming telemetry.")

    # 1. Initialize Face Detector
    detector = FaceDetectorYuNet(YUNET_MODEL_PATH)
    print("[AI] YuNet Face Detector loaded.")

    # 2. Initialize Camera
    camera = PiCameraStream(width=640, height=480, fps=30)

    # 3. Initialize Servos
    tracker = None
    if not args.no_servo:
        tracker = PanTiltTracker(pan_pin=args.pan_pin, tilt_pin=args.tilt_pin)
        tracker.center()
    else:
        print("[SERVOS] Disabled via --no-servo.")

    # 4. Initialize OLED Face
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

            # Detect faces
            faces, latency_ms = detector.detect(frame)
            primary_face = None

            if faces:
                # Target the largest face
                faces.sort(key=lambda f: f["box"][2] * f["box"][3], reverse=True)
                primary_face = faces[0]

                x, y, bw, bh = primary_face["box"]
                target_cx, target_cy = x + bw // 2, y + bh // 2

                # Compute normalized error (-1.0 to +1.0)
                norm_x = (target_cx - cx) / (w / 2.0)
                norm_y = (target_cy - cy) / (h / 2.0)

                # Check if locked within center 12% deadzone
                if abs(norm_x) < 0.12 and abs(norm_y) < 0.12:
                    state_name = "LOCKED"
                    if lock_start_time is None:
                        lock_start_time = time.time()
                    
                    # Happy eyes if held for 1.2s+!
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

                # Move servos toward face
                if tracker:
                    pan_deg, tilt_deg = tracker.track_face(target_cx, target_cy, w, h)

            else:
                state_name = "SCANNING"
                lock_start_time = None

                # Servos sweep search pattern
                if tracker:
                    pan_deg, tilt_deg = tracker.step_scan()

                # Curious eye scanning
                if face_display:
                    scan_gaze = math.sin(time.time() * 2.5) * 0.7
                    face_display.set_expression("NEUTRAL", gaze_x=scan_gaze, gaze_y=0.0)

            # Display / Telemetry
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
