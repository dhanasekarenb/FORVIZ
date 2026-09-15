"""Render the old and enlarged mirrored OLED eyes without using hardware."""
from pathlib import Path
import sys
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from oled_face import RobotEyesRenderer

renderer = RobotEyesRenderer()
old = Image.new('1', (128, 64))
renderer._draw_eye(ImageDraw.Draw(old), 64, 32, 64, 50, 'NEUTRAL', 0, 0, 0, True)
new = renderer.render_single_eye()
sheet = Image.new('RGB', (1120, 680), '#f3f1eb')
draw = ImageDraw.Draw(sheet)
path = Path('C:/Windows/Fonts/segoeui.ttf')
def font(size):
    return ImageFont.truetype(str(path), size) if path.exists() else ImageFont.load_default()
for row, (label, frame) in enumerate([('BEFORE / original size', old), ('AFTER / enlarged, same eye style', new)]):
    y = 22 + row * 330
    draw.text((32, y), label, font=font(26), fill='#22252b')
    for x in (32, 576):
        sheet.paste(frame.convert('RGB').resize((512, 256), Image.Resampling.NEAREST), (x, y + 46))
sheet.save(ROOT / 'docs/eye_size_comparison.png')
print('Created docs/eye_size_comparison.png')
