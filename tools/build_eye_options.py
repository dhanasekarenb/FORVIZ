"""Build a standalone OLED style gallery without changing robot runtime code."""
import base64
import io
import json
from pathlib import Path
import sys

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from oled_face import RobotEyesRenderer

STYLES = [
    ('Current eye', 'Your existing rounded eye, preserved exactly.'),
    ('Round explorer', 'Circular eyes with a large pupil and a small glint.'),
    ('Soft blocks', 'Solid rounded eyes for a clean, friendly expression.'),
    ('Tall capsules', 'Slim vertical eyes with a playful character.'),
    ('Pixel buddy', 'Stepped corners and a square pupil, like a retro game.'),
    ('Halo', 'A bright outer ring with a small floating pupil.'),
]
RENDERER = RobotEyesRenderer()


def eye(style, mood='NEUTRAL', gaze=0, blink=0):
    if style == 0:
        return RENDERER.render_single_eye(mood, gaze, 0, blink)
    image = Image.new('1', (128, 64))
    draw = ImageDraw.Draw(image)
    cx, cy = 64 + int(gaze * 10), 32
    if mood == 'HEART':
        return RENDERER.render_single_eye(mood)
    if mood == 'HAPPY':
        if style == 4:
            draw.line([(cx-21,37),(cx-21,29),(cx-13,29),(cx-13,21),
                       (cx+13,21),(cx+13,29),(cx+21,29),(cx+21,37)],fill=1,width=5)
        else:
            draw.arc((cx-24,18,cx+24,49),190,350,fill=1,width=5 if style==5 else 8)
        return image
    if blink >= .95:
        draw.line((cx-23,cy,cx+23,cy),fill=1,width=3)
        return image
    if style == 1:
        draw.ellipse((cx-24,8,cx+24,56),fill=1)
        px = cx + int(gaze*5)
        draw.ellipse((px-12,20,px+12,44),fill=0)
        draw.ellipse((px-7,22,px-2,27),fill=1)
    elif style in (2,3):
        width, height, radius = (48,44,12) if style==2 else (26,48,13)
        draw.rounded_rectangle((cx-width//2,cy-height//2,cx+width//2,cy+height//2),radius,fill=1)
    elif style == 4:
        draw.polygon([(cx-17,9),(cx+17,9),(cx+17,15),(cx+23,15),
                      (cx+23,49),(cx+17,49),(cx+17,55),(cx-17,55),
                      (cx-17,49),(cx-23,49),(cx-23,15),(cx-17,15)],fill=1)
        px=cx+int(gaze*4)
        draw.rectangle((px-9,23,px+9,41),fill=0)
        draw.rectangle((px-6,24,px-2,28),fill=1)
    elif style == 5:
        draw.ellipse((cx-24,8,cx+24,56),outline=1,width=4)
        px=cx+int(gaze*6)
        draw.ellipse((px-7,25,px+7,39),fill=1)
    if blink:
        half=max(2,int(25*(1-blink)))
        draw.rectangle((0,0,127,cy-half-1),fill=0)
        draw.rectangle((0,cy+half+1,127,63),fill=0)
    return image


def uri(image):
    out=io.BytesIO()
    image.save(out,format='PNG')
    return 'data:image/png;base64,'+base64.b64encode(out.getvalue()).decode()


def main():
    frames=[(0,0)]*12+[(0,.5),(0,1),(0,.5)]+[(0,0)]*5
    frames += [(-.25,0),(-.5,0),(-.75,0),(-1,0)]+[(-1,0)]*6
    frames += [(-.5,0),(0,0),(.5,0),(1,0)]+[(1,0)]*6+[(.5,0),(0,0)]
    data=[]
    for i,(name,description) in enumerate(STYLES):
        data.append(dict(name=name,description=description,
                         neutral=uri(eye(i)),happy=uri(eye(i,'HAPPY')),
                         heart=uri(eye(i,'HEART')),
                         frames=[uri(eye(i,gaze=g,blink=b)) for g,b in frames]))
    template=(ROOT/'docs/eye_options_template.html').read_text(encoding='utf-8')
    (ROOT/'docs/eye_options.html').write_text(template.replace('__EYE_DATA__',json.dumps(data)),encoding='utf-8')
    sheet=Image.new('RGB',(1200,840),'#f3f1eb')
    d=ImageDraw.Draw(sheet)
    font_path=Path('C:/Windows/Fonts/segoeui.ttf')
    def font(size):
        return ImageFont.truetype(str(font_path),size) if font_path.exists() else ImageFont.load_default()
    d.text((40,24),'FORVIZ / EYE EXPLORATIONS',font=font(30),fill='#22252b')
    d.text((40,68),'Current eye + five alternatives | 128 x 64 monochrome | same image on both OLEDs',font=font(17),fill='#62666e')
    for i,(name,_) in enumerate(STYLES):
        x=40+(i%2)*580; y=120+(i//2)*228
        d.rounded_rectangle((x,y,x+550,y+206),18,fill='white',outline='#d7d5cf',width=2)
        d.text((x+20,y+13),f'{i+1:02}  {name}'+('  / CURRENT' if i==0 else ''),font=font(21),fill='#b51e2c' if i==0 else '#22252b')
        for j in range(2):
            sheet.paste(eye(i).convert('RGB').resize((244,122),Image.Resampling.NEAREST),(x+21+j*263,y+64))
    sheet.save(ROOT/'docs/eye_options.png')
    print('Created docs/eye_options.html and docs/eye_options.png (6 styles).')


if __name__ == '__main__':
    main()
