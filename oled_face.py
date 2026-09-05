"""
Animated Robot Eyes & Expressions Engine for SSD1306 128x64 OLED(s).
====================================================================
Features:
  - Smart Auto-Detection: Automatically detects 1 or 2 OLED displays!
    * If 2 screens are detected -> Dual Eyes (Large Left Eye on Screen 1, Right Eye on Screen 2)
    * If 1 screen is detected  -> Single Screen (Cute dual eyes side-by-side)
  - Supports Port 1 (0x3C & 0x3D) and Port 3 (Software I2C on GPIO 23 & 24)
  - Async Background Threading (Zero FPS impact on AI vision)
  - Dynamic Gaze: Pupils physically follow the user's face position
"""
import time
import math
import threading
from PIL import Image, ImageDraw

try:
    from luma.core.interface.serial import i2c
    from luma.oled.device import ssd1306
    LUMA_AVAILABLE = True
except ImportError:
    LUMA_AVAILABLE = False


class RobotEyesRenderer:
    """Draws expressive vector/pixel eyes onto PIL 128x64 canvas."""
    def __init__(self, width=128, height=64):
        self.w = width
        self.h = height

    def render_single_screen(self, mood="NEUTRAL", gaze_x=0.0, gaze_y=0.0, blink_pct=0.0):
        """Renders TWO eyes side-by-side on a single 128x64 display."""
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
        """Renders dedicated Left and Right eye images for TWO independent 128x64 displays."""
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
    """
    Manages 1 or 2 SSD1306 OLED displays asynchronously with auto-detection.
    """
    def __init__(self, dual_screen=None, port_1=1, addr_1=0x3C, port_2=None, addr_2=None):
        self.renderer = RobotEyesRenderer(128, 64)
        self.dev1 = None
        self.dev2 = None
        self.dual_screen = False

        self.current_mood = "NEUTRAL"
        self.gaze_x = 0.0
        self.gaze_y = 0.0
        self.running = False
        self.thread = None

        if not LUMA_AVAILABLE:
            print("[OLED INFO] luma.oled not installed. Running without physical display.")
            return

        # 1. Initialize Screen 1
        try:
            serial1 = i2c(port=port_1, address=addr_1)
            self.dev1 = ssd1306(serial1)
            print(f"[OLED] Screen 1 detected on I2C Bus {port_1} (Addr 0x{addr_1:X})")
        except Exception as e:
            print(f"[OLED WARNING] Screen 1 not detected on Bus {port_1} (Addr 0x{addr_1:X}): {e}")

        # 2. Probe for Screen 2 (Auto-Detection)
        candidates = []
        if port_2 is not None and addr_2 is not None:
            candidates.append((port_2, addr_2))
        else:
            # Check common multi-OLED configurations:
            candidates = [
                (1, 0x3D),  # Jumper modification on Bus 1
                (3, 0x3C),  # Software I2C on Bus 3 (GPIO 23/24)
                (3, 0x3D),  # Software I2C with modified address
                (6, 0x3C),  # Hardware I2C 6 (GPIO 22/23)
            ]

        for p, a in candidates:
            if p == port_1 and a == addr_1:
                continue
            try:
                serial_candidate = i2c(port=p, address=a)
                dev_candidate = ssd1306(serial_candidate)
                self.dev2 = dev_candidate
                self.dual_screen = True
                print(f"[OLED] Screen 2 AUTO-DETECTED on I2C Bus {p} (Addr 0x{a:X})! Dual Eyes Active.")
                break
            except Exception:
                continue

        if not self.dual_screen:
            if dual_screen is True:
                print("[OLED NOTE] Dual-screen requested, but 2nd OLED was not detected on (Bus 1, 0x3D) or (Bus 3, 0x3C).")
                print("            Displaying dual eyes side-by-side on Screen 1.")
            else:
                print("[OLED INFO] 1 OLED display active. Dual eyes rendered side-by-side on Screen 1.")

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
