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
import math
import time

import threading
from PIL import Image, ImageDraw

try:
    from luma.core.interface.serial import i2c
    from luma.oled.device import ssd1306
    LUMA_AVAILABLE = True
except ImportError:
    LUMA_AVAILABLE = False


# Both OLED boards in the robot are installed upside down.  Keeping this as a
# shared default makes asymmetric expressions and gaze direction agree in the
# tracker and in the standalone OLED test.
DEFAULT_OLED_ROTATION = 180
UCHIHA_ACTIVATION_SECONDS = 1.25


class RobotEyesRenderer:
    """Draws expressive vector/pixel eyes onto PIL 128x64 canvas."""
    def __init__(self, width=128, height=64):
        self.w = width
        self.h = height

    def render_single_screen(self, mood="NEUTRAL", gaze_x=0.0, gaze_y=0.0,
                             blink_pct=0.0, effect_progress=1.0):
        """Renders TWO eyes side-by-side on a single 128x64 display."""
        image = Image.new("1", (self.w, self.h), 0)
        draw = ImageDraw.Draw(image)

        eye_w, eye_h = 32, 42
        eye_spacing = 18
        cy = self.h // 2
        left_cx = (self.w // 2) - (eye_spacing // 2) - (eye_w // 2)
        right_cx = (self.w // 2) + (eye_spacing // 2) + (eye_w // 2)

        self._draw_eye(draw, left_cx, cy, eye_w, eye_h, mood, gaze_x, gaze_y,
                       blink_pct, is_left=True, effect_progress=effect_progress)
        self._draw_eye(draw, right_cx, cy, eye_w, eye_h, mood, gaze_x, gaze_y,
                       blink_pct, is_left=False, effect_progress=effect_progress)
        return image

    def render_single_eye(self, mood="NEUTRAL", gaze_x=0.0, gaze_y=0.0,
                          blink_pct=0.0, effect_progress=1.0):
        """Renders ONE centered eye spanning the screen with a small border.
        
        Used when dual physical OLEDs share Pin 3 and Pin 5 on address 0x3C without soldering.
        Both displays receive the exact same big eye and animate in perfect sync.
        """
        image = Image.new("1", (self.w, self.h), 0)
        draw = ImageDraw.Draw(image)
        eye_w, eye_h = self.w - 4, self.h - 4
        cx, cy = self.w // 2, self.h // 2
        self._draw_eye(draw, cx, cy, eye_w, eye_h, mood, gaze_x, gaze_y,
                       blink_pct, is_left=True, effect_progress=effect_progress)
        return image

    def render_dual_screen(self, mood="NEUTRAL", gaze_x=0.0, gaze_y=0.0,
                           blink_pct=0.0, effect_progress=1.0):
        """Renders dedicated Left and Right eye images for TWO independent 128x64 displays."""
        img_left = Image.new("1", (self.w, self.h), 0)
        img_right = Image.new("1", (self.w, self.h), 0)
        draw_l = ImageDraw.Draw(img_left)
        draw_r = ImageDraw.Draw(img_right)

        eye_w, eye_h = self.w - 4, self.h - 4
        cx, cy = self.w // 2, self.h // 2

        self._draw_eye(draw_l, cx, cy, eye_w, eye_h, mood, gaze_x, gaze_y,
                       blink_pct, is_left=True, effect_progress=effect_progress)
        self._draw_eye(draw_r, cx, cy, eye_w, eye_h, mood, gaze_x, gaze_y,
                       blink_pct, is_left=False, effect_progress=effect_progress)
        return img_left, img_right

    def _draw_eye(self, draw, cx, cy, w, h, mood, gaze_x, gaze_y,
                  blink_pct, is_left, effect_progress=1.0):
        if mood == "UCHIHA":
            self._draw_uchiha_eye(
                draw, cx, cy, w, h, gaze_x, gaze_y, blink_pct, is_left,
                effect_progress)
            return

        if mood == "NARUTO":
            self._draw_naruto_eye(
                draw, cx, cy, w, h, gaze_x, gaze_y, blink_pct, is_left)
            return

        if mood == "NIGHTMARE":
            self._draw_nightmare_eye(
                draw, cx, cy, w, h, gaze_x, gaze_y, blink_pct, is_left)
            return

        if mood == "HAPPY":
            line_w = 4 if w > 40 else 3
            bbox = [cx - w // 2, cy - h // 3, cx + w // 2, cy + h // 3]
            draw.arc(bbox, start=190, end=350, fill=1, width=line_w)
            blush_x = cx - 10 if is_left else cx + 2
            draw.line([blush_x, cy + h // 3 + 4, blush_x + 8, cy + h // 3 + 4], fill=1, width=2)
            return

        if mood == "HEART":
            # Wide full-screen eyes must not make the heart taller than the panel.
            r = min(w // 4, h // 2 - 1)
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

    @staticmethod
    def _draw_uchiha_eye(draw, cx, cy, w, h, gaze_x, gaze_y,
                         blink_pct, is_left, effect_progress=1.0):
        """Fill the normal eye body and replace only its pupil with Sharingan."""
        progress = max(0.0, min(1.0, effect_progress))
        opening = min(1.0, progress / 0.30)
        activation_blink = 1.0 - opening
        current_h = int(h * (1.0 - max(blink_pct, activation_blink)))
        x0, x1 = cx - w // 2, cx + w // 2
        if current_h <= 3:
            draw.line([x0, cy, x1, cy], fill=1, width=2)
            return

        y0, y1 = cy - current_h // 2, cy + current_h // 2
        rx = 8 if w > 40 else 6
        draw.rounded_rectangle([x0, y0, x1, y1], radius=rx, fill=1, outline=1)
        pattern_progress = max(0.0, min(1.0, (progress - 0.16) / 0.64))
        if blink_pct >= 0.6 or pattern_progress <= 0.0:
            return

        final_iris_r = max(5, min(current_h // 2 - 3, w // 5 + 1))
        iris_r = max(2, int(final_iris_r * pattern_progress))
        max_offset_x = max(0, w // 2 - iris_r - 4)
        max_offset_y = max(0, current_h // 2 - iris_r - 3)
        px = cx + int(gaze_x * max_offset_x)
        py = cy + int(gaze_y * max_offset_y)

        # The eye remains fully lit like NEUTRAL; only the ring, centre and
        # three tomoe are dark pupil details.
        draw.ellipse([px - iris_r, py - iris_r,
                      px + iris_r, py + iris_r], outline=0,
                     width=max(2, iris_r // 8))
        pupil_r = max(1, iris_r // 5)
        draw.ellipse([px - pupil_r, py - pupil_r,
                      px + pupil_r, py + pupil_r], fill=0)

        # Three tomoe placed around the pupil. Each dot has a short tangential
        # tail so it remains recognizable on a 128x64 one-bit display.
        orbit = max(pupil_r + 2, int(iris_r * 0.60))
        tomoe_r = max(1, iris_r // 7)
        rotation = 360.0 * (1.0 - pattern_progress) ** 2
        for angle in (-90, 30, 150):
            radians = math.radians(angle + rotation)
            tx = px + int(orbit * math.cos(radians))
            ty = py + int(orbit * math.sin(radians))
            draw.ellipse([tx - tomoe_r, ty - tomoe_r,
                          tx + tomoe_r, ty + tomoe_r], fill=0)
            tangent_x = int((tomoe_r + 3) * -math.sin(radians))
            tangent_y = int((tomoe_r + 3) * math.cos(radians))
            draw.polygon([(tx, ty),
                          (tx + tangent_x, ty + tangent_y),
                          (tx + tangent_x // 2 - int(math.cos(radians) * tomoe_r),
                           ty + tangent_y // 2 - int(math.sin(radians) * tomoe_r))],
                         fill=0)

    @staticmethod
    def _draw_naruto_eye(draw, cx, cy, w, h, gaze_x, gaze_y,
                         blink_pct, is_left):
        """Draw a monochrome Sage-style ninja eye and horizontal pupil."""
        current_h = int(h * (1.0 - blink_pct))
        x0, x1 = cx - w // 2, cx + w // 2
        if current_h <= 3:
            draw.line([x0, cy, x1, cy], fill=1, width=2)
            return

        y0, y1 = cy - current_h // 2, cy + current_h // 2
        third = max(3, w // 3)
        outer = [
            (x0, cy), (cx - third, y0 + 4), (cx, y0 + 1),
            (cx + third, y0 + 4), (x1, cy),
            (cx + third, y1 - 4), (cx, y1 - 1),
            (cx - third, y1 - 4),
        ]
        draw.polygon(outer, fill=1)

        # A slightly lowered inner corner gives dedicated eyes opposing ninja
        # brows. Same-address mirrored OLEDs deliberately show the same eye.
        cut = max(2, current_h // 8)
        if is_left:
            draw.polygon([(x0, y0), (x1, y0), (x1, y0 + cut),
                          (x0, y0 + cut * 2)], fill=0)
        else:
            draw.polygon([(x0, y0), (x1, y0), (x1, y0 + cut * 2),
                          (x0, y0 + cut)], fill=0)

        iris_r = max(4, min(current_h // 3, w // 7))
        max_offset_x = max(0, w // 2 - iris_r - max(5, w // 9))
        max_offset_y = max(0, current_h // 2 - iris_r - 3)
        px = cx + int(gaze_x * max_offset_x)
        py = cy + int(gaze_y * max_offset_y)
        draw.ellipse([px - iris_r, py - iris_r,
                      px + iris_r, py + iris_r], fill=0)
        inner_r = max(2, iris_r - max(2, iris_r // 4))
        draw.ellipse([px - inner_r, py - inner_r,
                      px + inner_r, py + inner_r], fill=1)

        pupil_w = max(6, int(iris_r * 1.55))
        pupil_h = max(2, iris_r // 4)
        draw.rounded_rectangle(
            [px - pupil_w // 2, py - pupil_h,
             px + pupil_w // 2, py + pupil_h],
            radius=max(1, pupil_h // 2), fill=0)

        if w > 40:
            # Short dark marks suggest the heavy Sage eye outline without
            # sacrificing the limited 128x64 display area.
            mark_y = min(y1 - 2, cy + current_h // 3)
            if is_left:
                draw.line([(x0 + 9, mark_y), (x0 + 22, mark_y + 3)],
                          fill=0, width=2)
            else:
                draw.line([(x1 - 9, mark_y), (x1 - 22, mark_y + 3)],
                          fill=0, width=2)

    @staticmethod
    def _draw_nightmare_eye(draw, cx, cy, w, h, gaze_x, gaze_y,
                            blink_pct, is_left):
        """Draw a pointed monster eye with a moving vertical slit pupil."""
        current_h = int(h * (1.0 - blink_pct))
        x0, x1 = cx - w // 2, cx + w // 2
        if current_h <= 3:
            draw.line([x0, cy, x1, cy], fill=1, width=2)
            return

        y0, y1 = cy - current_h // 2, cy + current_h // 2
        quarter = max(2, w // 4)
        outer = [
            (x0, cy), (cx - quarter, y0 + 2), (cx, y0),
            (cx + quarter, y0 + 2), (x1, cy),
            (cx + quarter, y1 - 2), (cx, y1),
            (cx - quarter, y1 - 2),
        ]
        draw.polygon(outer, fill=1)

        # Cut a hard diagonal brow into the bright eye. Dedicated left/right
        # displays get mirrored brows; same-bus mirrored displays stay synced.
        brow_depth = max(4, current_h // 4)
        if is_left:
            brow = [(x0, y0), (x1, y0), (x1, y0 + 2),
                    (x0, y0 + brow_depth)]
        else:
            brow = [(x0, y0), (x1, y0), (x1, y0 + brow_depth),
                    (x0, y0 + 2)]
        draw.polygon(brow, fill=0)

        pupil_w = max(3, w // 10)
        pupil_h = max(8, int(current_h * 0.64))
        max_offset_x = max(0, (w - pupil_w) // 2 - max(5, w // 8))
        max_offset_y = max(0, (current_h - pupil_h) // 2 - 2)
        px = cx + int(gaze_x * max_offset_x)
        py = cy + int(gaze_y * max_offset_y)
        slit = [(px, py - pupil_h // 2),
                (px + pupil_w // 2, py),
                (px, py + pupil_h // 2),
                (px - pupil_w // 2, py)]
        draw.polygon(slit, fill=0)

        draw.point((px - 1, py - pupil_h // 4), fill=1)
        if w > 40:
            crack = max(5, w // 10)
            draw.line([(x0 + 3, cy), (x0 + crack, cy - 5),
                       (x0 + crack + 5, cy - 3)], fill=0, width=2)
            draw.line([(x1 - 3, cy + 2), (x1 - crack, cy + 7),
                       (x1 - crack - 5, cy + 5)], fill=0, width=2)


def parse_rotation(val):
    if val is None:
        return 0
    if val in (0, 360):
        return 0
    if val in (1, 90):
        return 1
    if val in (2, 180):
        return 2
    if val in (3, 270):
        return 3
    return 0


class OLEDDisplayController:
    """Discover up to two SSD1306 displays and animate without blocking vision.

    dual_screen=False explicitly uses one screen. If only a secondary bus
    responds, that screen becomes the primary. A failed display is disabled
    while its surviving partner continues in single-screen mode.
    """
    def __init__(self, dual_screen=None, port_1=1, addr_1=0x3C,
                 port_2=None, addr_2=None, *, hardware=True,
                 rotate=DEFAULT_OLED_ROTATION, rotate_1=None, rotate_2=None,
                 single_eye=False):
        if (port_2 is None) != (addr_2 is None):
            raise ValueError('Specify both port_2 and addr_2, or neither')
        self.renderer = RobotEyesRenderer(128, 64)
        self.single_eye = single_eye
        self.dev1 = self.dev2 = None
        self.dual_screen = False
        self.current_mood = 'NEUTRAL'
        self._expression_started_at = time.monotonic()
        self.gaze_x = self.gaze_y = 0.0
        self.running = False
        self.thread = None
        self._stop_event = threading.Event()
        self._expression_lock = threading.Lock()
        if not hardware or not LUMA_AVAILABLE:
            print('[OLED] No physical display output.')
            return

        r1 = parse_rotation(rotate if rotate_1 is None else rotate_1)
        r2 = parse_rotation(rotate if rotate_2 is None else rotate_2)
        rotations = [r1, r2]

        candidates = [(port_1, addr_1)]
        candidates += ([(port_2, addr_2)] if port_2 is not None else
                       [(1, 0x3D), (3, 0x3C), (3, 0x3D), (6, 0x3C)])
        devices = []
        for port, address in dict.fromkeys(candidates):
            serial = None
            try:
                rot = rotations[len(devices)] if len(devices) < len(rotations) else r1
                serial = i2c(port=port, address=address)
                device = ssd1306(serial, rotate=rot) if rot else ssd1306(serial)
            except Exception:
                if serial is not None:
                    try:
                        serial.cleanup()
                    except Exception:
                        pass
                continue
            devices.append(device)
            rot_deg = rot * 90
            print(f'[OLED] Display detected on bus {port}, address 0x{address:X}' +
                  (f' (rotated {rot_deg} deg)' if rot_deg else ''))
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
            if mood != self.current_mood:
                self._expression_started_at = time.monotonic()
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
            effect_progress = 1.0
            if self.current_mood == 'UCHIHA':
                elapsed = time.monotonic() - self._expression_started_at
                effect_progress = min(1.0, elapsed / UCHIHA_ACTIVATION_SECONDS)
            expression = (self.current_mood, self.gaze_x, self.gaze_y,
                          blink_pct, effect_progress)
        devices = [device for device in (self.dev1, self.dev2) if device is not None]
        if len(devices) == 2:
            frames = self.renderer.render_dual_screen(*expression)
        elif self.single_eye:
            frames = [self.renderer.render_single_eye(*expression)]
        else:
            frames = [self.renderer.render_single_screen(*expression)]
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
