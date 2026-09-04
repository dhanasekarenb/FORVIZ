import cv2
import time
import numpy as np
import os
import sys

# Model file path (must be in the same folder or specified)
YUNET_MODEL_PATH = "face_detection_yunet_2023mar.onnx"

# Try importing Picamera2 (standard for modern Raspberry Pi OS)
try:
    from picamera2 import Picamera2
    PICAM2_AVAILABLE = True
except ImportError:
    PICAM2_AVAILABLE = False


class PiCameraStream:
    """Handles camera capture using either Picamera2 (recommended for Pi Camera Rev 1.3) or OpenCV VideoCapture."""
    def __init__(self, width=640, height=480, fps=30):
        self.width = width
        self.height = height
        self.fps = fps
        self.use_picam2 = PICAM2_AVAILABLE
        self.picam2 = None
        self.cap = None

        if self.use_picam2:
            try:
                print("Initializing Raspberry Pi Camera via Picamera2...")
                self.picam2 = Picamera2()
                config = self.picam2.create_preview_configuration(main={"size": (width, height), "format": "RGB888"})
                self.picam2.configure(config)
                self.picam2.start()
                time.sleep(1.0)  # Camera warm-up
                print("Picamera2 started successfully.")
            except Exception as e:
                print(f"Picamera2 initialization failed ({e}). Falling back to cv2.VideoCapture...")
                self.use_picam2 = False

        if not self.use_picam2:
            print("Opening camera via OpenCV VideoCapture...")
            self.cap = cv2.VideoCapture(0)
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
            if not self.cap.isOpened():
                raise RuntimeError("Failed to open any camera device. Check CSI cable connection or run 'rpicam-hello'.")

    def read(self):
        if self.use_picam2:
            # Picamera2 outputs RGB888, OpenCV expects BGR
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
            raise FileNotFoundError(f"Model file '{model_path}' not found! Place it in the script directory.")
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


def compute_360_rotation_telemetry(frame, primary_face):
    """
    Computes horizontal yaw angle and motor rotational power (0-100%)
    for a stationary 360-degree rotating base.
    """
    h, w = frame.shape[:2]
    frame_cx = w // 2
    H_FOV_DEG = 62.2  # Approximate horizontal FOV for Pi Camera Rev 1.3 (OV5647)
    deadband_x = int(w * 0.08)  # 8% deadband to avoid motor jitter

    if primary_face is None:
        return {
            "state": "SCAN_360",
            "direction": "CW",
            "speed_pct": 25,
            "yaw_deg": 0.0,
            "lcd_text": "Scanning 360...",
            "lcd_art": "[ o   o ]\n  ---  ",
            "color": (0, 165, 255) # Orange
        }

    x, y, bw, bh = primary_face["box"]
    target_cx = x + bw // 2
    dx = target_cx - frame_cx
    yaw_deg = (dx / (w / 2.0)) * (H_FOV_DEG / 2.0)

    # Proportional motor power based on angular error
    abs_err_ratio = abs(dx) / (w / 2.0)
    speed_pct = int(min(100, max(20, abs_err_ratio * 100)))

    if target_cx < (frame_cx - deadband_x):
        return {
            "state": "ROTATE_CCW",
            "direction": "LEFT",
            "speed_pct": speed_pct,
            "yaw_deg": yaw_deg,
            "lcd_text": "Tracking left...",
            "lcd_art": "[ <   < ]\n  ___/ ",
            "color": (0, 220, 255) # Cyan
        }
    elif target_cx > (frame_cx + deadband_x):
        return {
            "state": "ROTATE_CW",
            "direction": "RIGHT",
            "speed_pct": speed_pct,
            "yaw_deg": yaw_deg,
            "lcd_text": "Tracking right...",
            "lcd_art": "[ >   > ]\n \\___  ",
            "color": (0, 220, 255)
        }
    else:
        return {
            "state": "LOCKED",
            "direction": "STILL",
            "speed_pct": 0,
            "yaw_deg": yaw_deg,
            "lcd_text": "Locked on you!",
            "lcd_art": "[ ^   ^ ]\n \\___/ ",
            "color": (0, 255, 0) # Green
        }


def draw_hud(frame, primary_face, telemetry, fps, latency_ms):
    h, w = frame.shape[:2]
    frame_cx = w // 2
    deadband_x = int(w * 0.08)

    # Deadband guides
    cv2.line(frame, (frame_cx - deadband_x, 0), (frame_cx - deadband_x, h), (70, 70, 70), 1)
    cv2.line(frame, (frame_cx + deadband_x, 0), (frame_cx + deadband_x, h), (70, 70, 70), 1)

    if primary_face:
        x, y, bw, bh = primary_face["box"]
        tcx, tcy = x + bw // 2, y + bh // 2
        cv2.rectangle(frame, (x, y), (x + bw, y + bh), telemetry["color"], 2)
        cv2.circle(frame, (tcx, tcy), 4, (0, 0, 255), -1)
        cv2.arrowedLine(frame, (frame_cx, tcy), (tcx, tcy), (0, 255, 255), 2, tipLength=0.2)
        if "landmarks" in primary_face:
            for lm in primary_face["landmarks"]:
                cv2.circle(frame, lm, 2, (0, 255, 0), -1)

    # Top overlay bar
    cv2.rectangle(frame, (0, 0), (w, 45), (20, 20, 20), -1)
    cv2.putText(frame, f"Pi 4 (2GB) | FPS: {fps:4.1f} | Latency: {latency_ms:4.1f}ms", 
                (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 0), 1)

    # Bottom telemetry bar
    cv2.rectangle(frame, (0, h - 50), (w, h), (20, 20, 20), -1)
    status_str = f"{telemetry['state']} | Dir: {telemetry['direction']} | Pwr: {telemetry['speed_pct']}% | Yaw: {telemetry['yaw_deg']:+.1f} deg"
    cv2.putText(frame, status_str, (10, h - 20), cv2.FONT_HERSHEY_SIMPLEX, 0.52, telemetry["color"], 2)

    return frame


def main():
    print("=" * 60)
    print("  RASPBERRY PI 4 - 360 DEGREE FACE TRACKER")
    print("=" * 60)

    # Check headless mode (if running via SSH without desktop display)
    headless = os.environ.get("DISPLAY") is None
    if headless:
        print("[INFO] Running in HEADLESS mode (no HDMI/X11 display).")
        print("       Telemetry will be printed to terminal.")

    detector = FaceDetectorYuNet(YUNET_MODEL_PATH)
    print("[✓] YuNet face detector loaded.")

    camera = PiCameraStream(width=640, height=480, fps=30)
    print("[✓] Camera stream initialized.")

    prev_time = time.time()
    fps = 0.0

    try:
        while True:
            ret, frame = camera.read()
            if not ret:
                print("Failed to read frame from camera.")
                break

            curr_time = time.time()
            dt = curr_time - prev_time
            prev_time = curr_time
            if dt > 0:
                fps = 0.85 * fps + 0.15 * (1.0 / dt) if fps > 0 else (1.0 / dt)

            faces, latency_ms = detector.detect(frame)
            primary_face = None
            if faces:
                # Pick largest face
                faces.sort(key=lambda f: f["box"][2] * f["box"][3], reverse=True)
                primary_face = faces[0]

            telemetry = compute_360_rotation_telemetry(frame, primary_face)

            if not headless:
                frame = draw_hud(frame, primary_face, telemetry, fps, latency_ms)
                cv2.imshow("Raspberry Pi 4 - 360 Face Tracker", frame)
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    break
            else:
                # Terminal output for SSH sessions
                print(f"\r[FPS: {fps:4.1f} | Latency: {latency_ms:4.1f}ms] -> Action: {telemetry['state']:10s} | Dir: {telemetry['direction']:5s} | Pwr: {telemetry['speed_pct']:3d}% | Yaw: {telemetry['yaw_deg']:+5.1f}° | Face: {'YES' if primary_face else 'NO '}", end="", flush=True)

    finally:
        camera.release()
        if not headless:
            cv2.destroyAllWindows()
        print("\nShutdown complete.")


if __name__ == "__main__":
    main()
