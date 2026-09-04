"""
Animated Robot Eyes & Expressions Engine for SSD1306 128x64 OLED(s).
Supports:
  - Single OLED Mode (Dual eyes rendered side-by-side on 1 screen)
  - Dual OLED Mode (Dedicated Left Eye on OLED 1, Right Eye on OLED 2)
  - Async Threading (Zero FPS impact on camera/vision pipeline)
  - Dynamic Gaze (Pupils physically track the user's face position)
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
    """Draws expressive procedural vector/pixel eyes onto PIL 128x64 canvas."""
    def __init__(self, width=128, height=64):
        self.w = width
        self.h = height

    def render_single_screen(self, mood="NEUTRAL", gaze_x=0.0, gaze_y=0.0, blink_pct=0.0):
        """
        Renders TWO eyes side-by-side on a single 128x64 display.
        gaze_x: -1.0 (far left) to +1.0 (far right)
        gaze_y: -1.0 (far up) to +1.0 (far down)
        blink_pct: 0.0 (fully open) to 1.0 (fully closed)
        """
        image = Image.new("1", (self.w, self.h), 0)
        draw = ImageDraw.Draw(image)

        # Eye dimensions (Single Screen: two 32x42 eyes)
        eye_w, eye_h = 32, 42
        eye_spacing = 18
        cy = self.h // 2
        left_cx = (self.w // 2) - (eye_spacing // 2) - (eye_w // 2)
        right_cx = (self.w // 2) + (eye_spacing // 2) + (eye_w // 2)

        # Draw left and right eyes
        self._draw_eye(draw, left_cx, cy, eye_w, eye_h, mood, gaze_x, gaze_y, blink_pct, is_left=True)
        self._draw_eye(draw, right_cx, cy, eye_w, eye_h, mood, gaze_x, gaze_y, blink_pct, is_left=False)

        return image

    def render_dual_screen(self, mood="NEUTRAL", gaze_x=0.0, gaze_y=0.0, blink_pct=0.0):
        """
        Renders dedicated Left and Right eye images for TWO independent 128x64 displays.
        Each eye is a big, detailed 64x50 expressive eye!
        """
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
        # Handle Happy Eyes (Arcs: ^ ^)
        if mood == "HAPPY":
            # Draw cute happy crescents
            line_w = 4 if w > 40 else 3
            bbox = [cx - w // 2, cy - h // 3, cx + w // 2, cy + h // 3]
            draw.arc(bbox, start=190, end=350, fill=1, width=line_w)
            # Add small blush lines underneath
            blush_x = cx - 10 if is_left else cx + 2
            draw.line([blush_x, cy + h // 3 + 4, blush_x + 8, cy + h // 3 + 4], fill=1, width=2)
            return

        # Handle Heart Eyes
        if mood == "HEART":
            self._draw_heart(draw, cx, cy, size=w // 2)
            return

        # Normal Eye with blink compression
        current_h = int(h * (1.0 - blink_pct))
        if current_h <= 3:
            # Fully closed blink slit
            draw.line([cx - w // 2, cy, cx + w // 2, cy], fill=1, width=2)
            return

        # Outer rounded eye box
        rx = 8 if w > 40 else 6
        x0, y0 = cx - w // 2, cy - current_h // 2
        x1, y1 = cx + w // 2, cy + current_h // 2
        draw.rounded_rectangle([x0, y0, x1, y1], radius=rx, fill=1, outline=1)

        # Pupil calculation (Cutout from white eye)
        if blink_pct < 0.6:
            pupil_w = int(w * 0.42)
            pupil_h = int(current_h * 0.55)
            max_offset_x = (w - pupil_w) // 2 - 2
            max_offset_y = (current_h - pupil_h) // 2 - 2

            px = cx + int(gaze_x * max_offset_x)
            py = cy + int(gaze_y * max_offset_y)

            # Pupil cutout (black)
            draw.rounded_rectangle(
                [px - pupil_w // 2, py - pupil_h // 2, px + pupil_w // 2, py + pupil_h // 2],
                radius=4, fill=0
            )

            # Little highlight reflection dot (white) in top-left
            dot_r = 3 if w > 40 else 2
            dot_x = px - pupil_w // 4
            dot_y = py - pupil_h // 4
            draw.ellipse([dot_x - dot_r, dot_y - dot_r, dot_x + dot_r, dot_y + dot_r], fill=1)

    def _draw_heart(self, draw, cx, cy, size):
        r = size // 2
        draw.ellipse([cx - r, cy - r, cx, cy], fill=1)
        draw.ellipse([cx, cy - r, cx + r, cy], fill=1)
        poly = [(cx - r, cy - r // 3), (cx + r, cy - r // 3), (cx, cy + r)]
        draw.polygon(poly, fill=1)


class OLEDDisplayController:
    """
    Manages 1 or 2 SSD1306 OLED displays asynchronously.
    """
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
                # Primary Display (Left eye or Single Screen) on i2c port 1
                serial1 = i2c(port=port_1, address=addr_1)
                self.dev1 = ssd1306(serial1)
                print(f"[OLED] Initialized Screen 1 on I2C Port {port_1} (Addr 0x{addr_1:X})")

                # Secondary Display (Right eye in dual mode)
                if dual_screen:
                    try:
                        serial2 = i2c(port=port_2, address=addr_2)
                        self.dev2 = ssd1306(serial2)
                        print(f"[OLED] Initialized Screen 2 on I2C Port {port_2} (Addr 0x{addr_2:X})")
                    except Exception as e:
                        print(f"[OLED WARNING] Screen 2 init failed ({e}). Reverting to single-screen mode.")
                        self.dual_screen = False
            except Exception as e:
                print(f"[OLED WARNING] OLED init failed ({e}). Running in headless mode.")
        else:
            print("[OLED WARNING] luma.oled not installed. Running in headless mode.")

    def set_expression(self, mood="NEUTRAL", gaze_x=0.0, gaze_y=0.0):
        self.current_mood = mood
        self.gaze_x = max(-1.0, min(1.0, gaze_x))
        self.gaze_y = max(-1.0, min(1.0, gaze_y))

    def start(self):
        """Starts the background animation loop."""
        self.running = True
        self.thread = threading.Thread(target=self._animation_loop, daemon=True)
        self.thread.start()

    def _animation_loop(self):
        last_blink_time = time.time()
        blink_interval = 3.5  # blink every 3.5 seconds
        blink_duration = 0.18 # 180ms blink

        while self.running:
            now = time.time()
            elapsed_blink = now - last_blink_time

            # Compute procedural blink state
            blink_pct = 0.0
            if elapsed_blink > blink_interval:
                t = (elapsed_blink - blink_interval) / blink_duration
                if t <= 0.5:
                    blink_pct = t * 2.0  # Closing
                elif t <= 1.0:
                    blink_pct = (1.0 - t) * 2.0  # Opening
                else:
                    last_blink_time = now
                    blink_interval = 2.5 + (hash(str(now)) % 30) / 10.0

            # Render frames
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

            time.sleep(0.04)  # ~25 FPS OLED refresh is butter-smooth

    def stop(self):
        self.running = False
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=1.0)
        # Clear screen on exit
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
