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
    """Discover up to two SSD1306 displays and animate without blocking vision.

    dual_screen=False explicitly uses one screen. If only a secondary bus
    responds, that screen becomes the primary. A failed display is disabled
    while its surviving partner continues in single-screen mode.
    """
    def __init__(self, dual_screen=None, port_1=1, addr_1=0x3C,
                 port_2=None, addr_2=None, *, hardware=True):
        if (port_2 is None) != (addr_2 is None):
            raise ValueError('Specify both port_2 and addr_2, or neither')
        self.renderer = RobotEyesRenderer(128, 64)
        self.dev1 = self.dev2 = None
        self.dual_screen = False
        self.current_mood = 'NEUTRAL'
        self.gaze_x = self.gaze_y = 0.0
        self.running = False
        self.thread = None
        self._stop_event = threading.Event()
        self._expression_lock = threading.Lock()
        if not hardware or not LUMA_AVAILABLE:
            print('[OLED] No physical display output.')
            return

        candidates = [(port_1, addr_1)]
        candidates += ([(port_2, addr_2)] if port_2 is not None else
                       [(1, 0x3D), (3, 0x3C), (3, 0x3D), (6, 0x3C)])
        devices = []
        for port, address in dict.fromkeys(candidates):
            serial = None
            try:
                serial = i2c(port=port, address=address)
                device = ssd1306(serial)
            except Exception:
                if serial is not None:
                    try:
                        serial.cleanup()
                    except Exception:
                        pass
                continue
            devices.append(device)
            print(f'[OLED] Display detected on bus {port}, address 0x{address:X}')
            if len(devices) >= (1 if dual_screen is False else 2):
                break
        if devices:
            self.dev1 = devices[0]
        if len(devices) == 2:
            self.dev2 = devices[1]
            self.dual_screen = True
        if dual_screen is True and not self.dual_screen:
            print('[OLED] Two screens requested; using the displays detected.')

    def set_expression(self, mood='NEUTRAL', gaze_x=0.0, gaze_y=0.0):
        with self._expression_lock:
            self.current_mood = mood
            self.gaze_x = max(-1.0, min(1.0, gaze_x))
            self.gaze_y = max(-1.0, min(1.0, gaze_y))

    def start(self):
        if self.thread is not None and self.thread.is_alive():
            return
        if self.dev1 is None:
            return
        self._stop_event.clear()
        self.running = True
        self.thread = threading.Thread(target=self._animation_loop, daemon=True, name='forviz-eyes')
        self.thread.start()

    @staticmethod
    def _cleanup_device(device):
        if device is not None:
            for method in ('clear', 'cleanup'):
                try:
                    getattr(device, method)()
                except Exception:
                    pass

    def _display_frame(self, blink_pct):
        with self._expression_lock:
            expression = self.current_mood, self.gaze_x, self.gaze_y, blink_pct
        devices = [device for device in (self.dev1, self.dev2) if device is not None]
        frames = (self.renderer.render_dual_screen(*expression) if len(devices) == 2 else
                  [self.renderer.render_single_screen(*expression)])
        survivors = []
        for device, frame in zip(devices, frames):
            try:
                device.display(frame)
                survivors.append(device)
            except Exception as exc:
                print(f'[OLED WARNING] Display disconnected: {exc}')
                self._cleanup_device(device)
        self.dev1 = survivors[0] if survivors else None
        self.dev2 = survivors[1] if len(survivors) == 2 else None
        self.dual_screen = self.dev2 is not None

    def _animation_loop(self):
        last_blink_time = time.monotonic()
        blink_interval, blink_duration = 3.5, 0.18
        try:
            while not self._stop_event.is_set() and self.dev1 is not None:
                now = time.monotonic()
                phase = (now - last_blink_time - blink_interval) / blink_duration
                blink_pct = max(0.0, 1.0 - abs(2.0 * phase - 1.0)) if 0 <= phase <= 1 else 0.0
                if phase > 1:
                    last_blink_time = now
                self._display_frame(blink_pct)
                self._stop_event.wait(0.04)
        except Exception as exc:
            print(f'[OLED WARNING] Animation stopped: {exc}')
        finally:
            self.running = False
            self._cleanup_device(self.dev1)
            self._cleanup_device(self.dev2)
            self.dev1 = self.dev2 = None
            self.dual_screen = False

    def stop(self):
        self._stop_event.set()
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=1.0)
            if self.thread.is_alive():
                # Avoid concurrent I2C access; the worker owns cleanup.
                print('[OLED WARNING] Waiting for blocked I2C operation to finish.')
                return
        self.running = False
        self._cleanup_device(self.dev1)
        self._cleanup_device(self.dev2)
        self.dev1 = self.dev2 = None
        self.dual_screen = False
