import cv2
import time
import numpy as np
import os

# Paths to models
YUNET_MODEL_PATH = "face_detection_yunet_2023mar.onnx"
YOLO_MODEL_PATH = "yolov8n.pt"

# Try loading Ultralytics YOLO
try:
    from ultralytics import YOLO
    YOLO_AVAILABLE = True
except ImportError:
    YOLO_AVAILABLE = False


class FaceDetectorYuNet:
    """Lightweight 232KB deep learning face detector using OpenCV DNN."""
    def __init__(self, model_path=YUNET_MODEL_PATH, conf_threshold=0.6, nms_threshold=0.3):
        if not os.path.exists(model_path):
            raise FileNotFoundError(f"Model file not found: {model_path}")
        self.conf_threshold = conf_threshold
        self.nms_threshold = nms_threshold
        self.detector = cv2.FaceDetectorYN.create(
            model=model_path,
            config="",
            input_size=(320, 320),
            score_threshold=conf_threshold,
            nms_threshold=nms_threshold,
            top_k=5000,
            backend_id=cv2.dnn.DNN_BACKEND_OPENCV,
            target_id=cv2.dnn.DNN_TARGET_CPU
        )

    def detect(self, frame):
        h, w = frame.shape[:2]
        self.detector.setInputSize((w, h))
        
        start_time = time.perf_counter()
        _, faces = self.detector.detect(frame)
        latency_ms = (time.perf_counter() - start_time) * 1000

        results = []
        if faces is not None:
            for face in faces:
                x, y, bw, bh = map(int, face[0:4])
                conf = float(face[14])
                landmarks = [(int(face[i]), int(face[i+1])) for i in range(4, 14, 2)]
                results.append({
                    "box": (x, y, bw, bh),
                    "confidence": conf,
                    "landmarks": landmarks,
                    "label": "Face"
                })
        return results, latency_ms


class ObjectDetectorYOLO:
    """YOLOv8 Nano object detector."""
    def __init__(self, model_path=YOLO_MODEL_PATH, conf_threshold=0.45):
        if not YOLO_AVAILABLE:
            raise RuntimeError("Ultralytics library not installed.")
        self.model = YOLO(model_path)
        self.conf_threshold = conf_threshold

    def detect(self, frame):
        start_time = time.perf_counter()
        results = self.model(frame, conf=self.conf_threshold, verbose=False)[0]
        latency_ms = (time.perf_counter() - start_time) * 1000

        detections = []
        for box in results.boxes:
            x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
            conf = float(box.conf[0])
            cls_id = int(box.cls[0])
            label = results.names[cls_id]
            detections.append({
                "box": (x1, y1, x2 - x1, y2 - y1),
                "confidence": conf,
                "label": label
            })
        return detections, latency_ms


def draw_hud_and_telemetry(frame, primary_target, latency_ms, fps, mode_name, show_hud=True):
    """
    HUD and Telemetry tailored for a STATIONARY 360-DEGREE ROTATING TURRET / ROBOT.
    No forward/backward translation — only pure Pan / Yaw rotation tracking.
    """
    h, w = frame.shape[:2]
    frame_cx = w // 2
    frame_cy = h // 2
    
    # Camera horizontal field of view assumption (~65 degrees for typical webcams/Pi camera)
    H_FOV_DEG = 65.0
    
    # Deadband tolerance in pixels (center zone where the robot stays still and doesn't jitter)
    deadband_x = int(w * 0.08) # 8% deadband zone
    
    # Rotation command & LCD telemetry defaults
    rotation_cmd = "360 SWEEP SCAN (SEEKING HUMAN)"
    cmd_color = (0, 165, 255)  # Orange
    yaw_angle_str = "TARGET: NONE"
    rotation_speed_pct = 25    # gentle search sweep speed
    expr_art = "[ o   o ]\n  ---  "
    expr_text = "Scanning 360..."

    if primary_target is not None:
        x, y, bw, bh = primary_target["box"]
        target_cx = x + bw // 2
        target_cy = y + bh // 2
        
        # Pixel offset from frame center
        dx_pixels = target_cx - frame_cx
        
        # Calculate angular offset in degrees
        yaw_deg = (dx_pixels / (w / 2.0)) * (H_FOV_DEG / 2.0)
        
        # Area percentage of frame occupied by the target
        area_ratio = (bw * bh) / (w * h)

        # Proportional rotation speed (0% to 100%)
        # The further the face is from center, the faster the robot spins
        abs_err = abs(dx_pixels) / (w / 2.0)
        rotation_speed_pct = int(min(100, max(15, abs_err * 100)))

        # Steering decision
        if target_cx < (frame_cx - deadband_x):
            rotation_cmd = f"ROTATE LEFT (CCW) <<  [PWR: {rotation_speed_pct}%]"
            cmd_color = (0, 220, 255) # Yellow/Cyan
            yaw_angle_str = f"Yaw Error: {yaw_deg:+.1f} deg (Turn Left)"
            expr_art = "[ <   < ]\n  ___/ "
            expr_text = "Tracking left..."
        elif target_cx > (frame_cx + deadband_x):
            rotation_cmd = f"ROTATE RIGHT (CW) >>  [PWR: {rotation_speed_pct}%]"
            cmd_color = (0, 220, 255)
            yaw_angle_str = f"Yaw Error: {yaw_deg:+.1f} deg (Turn Right)"
            expr_art = "[ >   > ]\n \\___  "
            expr_text = "Tracking right..."
        else:
            rotation_cmd = "LOCKED ON TARGET -- [STAND STILL / 0%]"
            cmd_color = (0, 255, 0) # Solid Green
            yaw_angle_str = f"Yaw Error: {yaw_deg:+.1f} deg (Centered)"
            expr_art = "[ ^   ^ ]\n \\___/ "
            expr_text = "Locked on you!"

        # Draw Target Box & Crosshair
        cv2.rectangle(frame, (x, y), (x + bw, y + bh), cmd_color, 2)
        cv2.line(frame, (target_cx - 15, target_cy), (target_cx + 15, target_cy), (0, 255, 255), 2)
        cv2.line(frame, (target_cx, target_cy - 15), (target_cx, target_cy + 15), (0, 255, 255), 2)
        cv2.circle(frame, (target_cx, target_cy), 4, (0, 0, 255), -1)
        
        # Horizontal heading deviation bar (shows rotation direction on target)
        cv2.arrowedLine(frame, (frame_cx, target_cy), (target_cx, target_cy), (0, 255, 255), 2, tipLength=0.2)

    if not show_hud:
        return frame

    # --- Draw Center Deadband Zone Guides ---
    left_bound = frame_cx - deadband_x
    right_bound = frame_cx + deadband_x
    cv2.line(frame, (left_bound, 0), (left_bound, h), (80, 80, 80), 1, cv2.LINE_AA)
    cv2.line(frame, (right_bound, 0), (right_bound, h), (80, 80, 80), 1, cv2.LINE_AA)
    cv2.drawMarker(frame, (frame_cx, frame_cy), (100, 100, 100), cv2.MARKER_CROSS, 20, 1)

    # --- Top Info Banner (Semi-transparent) ---
    banner_h = 75
    overlay = frame.copy()
    cv2.rectangle(overlay, (0, 0), (w, banner_h), (20, 20, 20), -1)
    # Bottom Telemetry Bar
    cv2.rectangle(overlay, (0, h - 70), (w, h), (20, 20, 20), -1)
    
    # Mini LCD Expression Box (Top Right)
    lcd_box_w, lcd_box_h = 220, 110
    lcd_x1 = w - lcd_box_w - 15
    lcd_y1 = banner_h + 10
    cv2.rectangle(overlay, (lcd_x1, lcd_y1), (lcd_x1 + lcd_box_w, lcd_y1 + lcd_box_h), (10, 25, 35), -1)
    
    cv2.addWeighted(overlay, 0.75, frame, 0.25, 0, frame)

    # Border for Mini LCD
    cv2.rectangle(frame, (lcd_x1, lcd_y1), (lcd_x1 + lcd_box_w, lcd_y1 + lcd_box_h), (0, 200, 255), 1)
    cv2.putText(frame, "ROBOT LCD FACE", (lcd_x1 + 10, lcd_y1 + 18), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 200, 255), 1)

    # Render Expression in Mini LCD
    lines = expr_art.split('\n')
    cv2.putText(frame, lines[0], (lcd_x1 + 45, lcd_y1 + 50), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 255, 255), 2)
    cv2.putText(frame, lines[1], (lcd_x1 + 55, lcd_y1 + 75), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 255, 255), 2)
    cv2.putText(frame, expr_text, (lcd_x1 + 10, lcd_y1 + 98), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (200, 255, 200), 1)

    # Top Banner Text
    cv2.putText(frame, f"MODE: {mode_name}", (15, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.62, (255, 255, 255), 2)
    cv2.putText(frame, f"FPS: {fps:4.1f} | Latency: {latency_ms:4.1f} ms", (15, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 0), 1)
    cv2.putText(frame, "STATIONARY 360 TURRET", (w - 230, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 255), 1)

    # Bottom Telemetry Bar Text
    cv2.putText(frame, f"ROTATION: {rotation_cmd}", (15, h - 42), cv2.FONT_HERSHEY_SIMPLEX, 0.65, cmd_color, 2)
    cv2.putText(frame, f"{yaw_angle_str} | [M] Mode | [C] HUD | [S] Snap | [Q] Quit", 
                (15, h - 15), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (200, 200, 200), 1)

    return frame


def main():
    print("=" * 68)
    print("  STATIONARY 360-DEGREE ROTATING ROBOT - VISION TRACKING HARNESS")
    print("=" * 68)
    print("Loading models...")
    
    yunet = None
    yolo = None
    active_mode = "YUNET_FACE"

    try:
        yunet = FaceDetectorYuNet(YUNET_MODEL_PATH)
        print("  [✓] YuNet Face Detector initialized (232 KB ONNX)")
    except Exception as e:
        print(f"  [!] Failed to load YuNet: {e}")

    try:
        yolo = ObjectDetectorYOLO(YOLO_MODEL_PATH)
        print("  [✓] YOLOv8 Nano Object Detector initialized")
    except Exception as e:
        print(f"  [!] Failed to load YOLO: {e}")

    if yunet is None and yolo is None:
        print("Error: No models available. Exiting.")
        return

    if yunet is None:
        active_mode = "YOLO_OBJECT"

    print("\nStarting Camera Capture (Device 0)...")
    cap = cv2.VideoCapture(0)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

    if not cap.isOpened():
        print("Error: Could not open webcam at index 0.")
        return

    print("Camera stream active! Controls:")
    print("  - 'm' : Switch between Face (YuNet) and Object (YOLO)")
    print("  - 'c' : Toggle HUD overlay")
    print("  - 's' : Save snapshot")
    print("  - 'q' or ESC : Exit")
    print("-" * 68)

    show_hud = True
    prev_time = time.time()
    fps = 0.0

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                print("Failed to grab frame.")
                break

            # Mirror for intuitive tracking view
            frame = cv2.flip(frame, 1)

            curr_time = time.time()
            dt = curr_time - prev_time
            prev_time = curr_time
            if dt > 0:
                current_fps = 1.0 / dt
                fps = 0.85 * fps + 0.15 * current_fps if fps > 0 else current_fps

            primary_target = None
            latency_ms = 0.0

            if active_mode == "YUNET_FACE" and yunet is not None:
                mode_name = "YuNet Face Detector (Pi 4 Optimized)"
                detections, latency_ms = yunet.detect(frame)
                
                if detections:
                    detections.sort(key=lambda d: d["box"][2] * d["box"][3], reverse=True)
                    primary_target = detections[0]
                    
                    for d in detections:
                        if "landmarks" in d:
                            for lm in d["landmarks"]:
                                cv2.circle(frame, lm, 3, (0, 255, 0), -1)

            elif active_mode == "YOLO_OBJECT" and yolo is not None:
                mode_name = "YOLOv8 Nano (General Object)"
                detections, latency_ms = yolo.detect(frame)
                
                persons = [d for d in detections if d["label"] == "person"]
                if persons:
                    persons.sort(key=lambda d: d["box"][2] * d["box"][3], reverse=True)
                    primary_target = persons[0]
                elif detections:
                    detections.sort(key=lambda d: d["box"][2] * d["box"][3], reverse=True)
                    primary_target = detections[0]

                for d in detections:
                    if d != primary_target:
                        bx, by, bw, bh = d["box"]
                        cv2.rectangle(frame, (bx, by), (bx + bw, by + bh), (180, 180, 180), 1)
                        cv2.putText(frame, f"{d['label']} {d['confidence']:.2f}", 
                                    (bx, max(15, by - 5)), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (180, 180, 180), 1)

            frame = draw_hud_and_telemetry(frame, primary_target, latency_ms, fps, mode_name, show_hud)

            cv2.imshow("Stationary 360 Robot Tracker", frame)

            key = cv2.waitKey(1) & 0xFF
            if key == ord('q') or key == 27:
                break
            elif key == ord('m'):
                if active_mode == "YUNET_FACE" and yolo is not None:
                    active_mode = "YOLO_OBJECT"
                elif active_mode == "YOLO_OBJECT" and yunet is not None:
                    active_mode = "YUNET_FACE"
                print(f"Switched mode to: {active_mode}")
            elif key == ord('c'):
                show_hud = not show_hud
            elif key == ord('s'):
                filename = f"snapshot_{int(time.time())}.jpg"
                cv2.imwrite(filename, frame)
                print(f"Snapshot saved to {filename}")

    finally:
        cap.release()
        cv2.destroyAllWindows()
        print("Session ended cleanly.")


if __name__ == "__main__":
    main()
