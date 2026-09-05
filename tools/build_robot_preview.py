"""Build the offline V3 mesh viewer and a depth-correct engineering PNG.

Run from any directory: python tools/build_robot_preview.py
Requires numpy and Pillow. The generated HTML has no external dependencies.
Printed triangles and nominal hardware reference envelopes come directly from
the exported mesh data. Reference envelopes are not printable components.
"""
import argparse
from datetime import date
import json
import math
from pathlib import Path
import re

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
PAPER = (245, 243, 236)
INK = (36, 58, 54)
MUTED = (115, 131, 122)
ORANGE = (188, 112, 66)


def font(size, bold=False):
    candidates = [
        Path('C:/Windows/Fonts') / ('segoeuib.ttf' if bold else 'segoeui.ttf'),
        Path('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf' if bold else
             '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'),
    ]
    for candidate in candidates:
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size)
    return ImageFont.load_default(size=size)


def load_meshes(path):
    data = json.loads(path.read_text(encoding='utf-8-sig'))
    if not data:
        raise ValueError('Assembly contains no meshes')
    for mesh in data:
        vertices = np.asarray(mesh['vertices'], dtype=float)
        faces = np.asarray(mesh['faces'], dtype=int)
        if (vertices.ndim != 2 or vertices.shape[1] != 3 or not np.isfinite(vertices).all()
                or faces.ndim != 2 or faces.shape[1] != 3
                or faces.min() < 0 or faces.max() >= len(vertices)):
            raise ValueError(f"Invalid mesh: {mesh['name']}")
        if len(mesh['explode']) != 3 or not np.isfinite(mesh['explode']).all():
            raise ValueError(f"Invalid explode vector: {mesh['name']}")
    return data


def readable_name(name):
    """Format part filenames, assembly-key instances, pins, and references."""
    name = re.sub(r'^\d+_', '', name)
    name = re.sub(r'^(reference|ref)_', '', name)
    if name.startswith('pcb_pin_'):
        return 'PCB pin · ' + name[8:].replace('_', ', ')
    if name.startswith('key_'):
        words = name[4:].split('_')
        side = ' · ' + words.pop() if words[-1] in ('left', 'right') else ''
        name = ' '.join(words) + ' key' + side
    else:
        name = name.replace('_', ' ')
    name = name.capitalize()
    for token, label in (('pcb', 'PCB'), ('oled', 'OLED'), ('sg90', 'SG90'),
                         ('csi', 'CSI'), ('pi4', 'Raspberry Pi 4')):
        name = re.sub(r'\b' + token + r'\b', label, name, flags=re.IGNORECASE)
    return name


def printed_legend(meshes):
    """Keep the PNG legend readable as repeated keys and pins are added."""
    ordinary, keys, pins = [], [], []
    for mesh in meshes:
        if mesh.get('group') == 'reference':
            continue
        if mesh['name'].startswith('key_'):
            keys.append(mesh)
        elif mesh['name'].startswith('pcb_pin_'):
            pins.append(mesh)
        else:
            ordinary.append((readable_name(mesh['name']), mesh['color']))
    if keys:
        ordinary.append((f'Retaining keys × {len(keys)}', keys[0]['color']))
    if pins:
        ordinary.append((f'PCB pins × {len(pins)}', pins[0]['color']))
    return ordinary


def render_meshes(meshes, width, height, explode=0.0, yaw=0.58, elevation=0.4):
    """Orthographic triangle renderer with per-pixel barycentric depth testing."""
    right = np.array([math.cos(yaw), math.sin(yaw), 0.0])
    forward = np.array([math.sin(yaw) * math.cos(elevation),
                        -math.cos(yaw) * math.cos(elevation), math.sin(elevation)])
    up = np.cross(forward, right)
    transform = np.stack([right, -up, forward], axis=1)
    prepared = []
    all_projected = []
    for mesh in meshes:
        vertices = np.asarray(mesh['vertices']) + np.asarray(mesh['explode']) * explode
        faces = np.asarray(mesh['faces'])
        projected = vertices @ transform
        color = np.array([int(mesh['color'][i:i + 2], 16) for i in (1, 3, 5)])
        prepared.append((vertices, projected, faces, color))
        all_projected.append(projected)
    all_projected = np.concatenate(all_projected)
    low, high = all_projected.min(axis=0), all_projected.max(axis=0)
    center = (low + high) / 2
    scale = min((width - 50) / (high[0] - low[0]), (height - 50) / (high[1] - low[1]))
    pixels = np.full((height, width, 3), PAPER, dtype=np.uint8)
    depth = np.full((height, width), -np.inf)
    light = np.array([-0.5, -0.8, 1.2])
    light /= np.linalg.norm(light)
    for vertices, projected, faces, color in prepared:
        projected = projected.copy()
        projected[:, :2] = (projected[:, :2] - center[:2]) * scale + [width / 2, height / 2]
        for face in faces:
            tri = projected[face]
            normal = np.cross(vertices[face[1]] - vertices[face[0]], vertices[face[2]] - vertices[face[0]])
            length = np.linalg.norm(normal)
            if length < 1e-10:
                continue
            normal /= length
            shade = 0.52 + 0.38 * max(0, np.dot(normal, light)) + 0.1 * max(0, normal[2])
            shade_color = np.clip(color * shade, 0, 255).astype(np.uint8)
            x0, y0 = np.maximum(np.floor(tri[:, :2].min(axis=0)).astype(int), 0)
            x1, y1 = np.minimum(np.ceil(tri[:, :2].max(axis=0)).astype(int), [width - 1, height - 1])
            if x1 < x0 or y1 < y0:
                continue
            a, b, c = tri
            denominator = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1])
            if abs(denominator) < 1e-9:
                continue
            y, x = np.mgrid[y0:y1 + 1, x0:x1 + 1]
            x, y = x + 0.5, y + 0.5
            wa = ((b[1] - c[1]) * (x - c[0]) + (c[0] - b[0]) * (y - c[1])) / denominator
            wb = ((c[1] - a[1]) * (x - c[0]) + (a[0] - c[0]) * (y - c[1])) / denominator
            wc = 1 - wa - wb
            z = wa * a[2] + wb * b[2] + wc * c[2]
            region_depth = depth[y0:y1 + 1, x0:x1 + 1]
            visible = (wa >= -1e-6) & (wb >= -1e-6) & (wc >= -1e-6) & (z > region_depth)
            region_depth[visible] = z[visible]
            pixels[y0:y1 + 1, x0:x1 + 1][visible] = shade_color
    return Image.fromarray(pixels)


def make_design_sheet(meshes, output):
    image = Image.new('RGB', (1800, 1380), PAPER)
    draw = ImageDraw.Draw(image)
    draw.text((74, 47), 'FORVIZ.', font=font(48, True), fill=INK)
    draw.text((76, 113), 'V3 / TOOL-FREE ROBOT ENCLOSURE', font=font(18), fill=MUTED)
    draw.rounded_rectangle((1225, 55, 1725, 132), radius=12, outline=(217, 184, 155), width=2)
    draw.text((1249, 66), 'V3 ENGINEERING PROTOTYPE', font=font(18, True), fill=ORANGE)
    draw.text((1249, 96), 'Physical fit not yet tested', font=font(18), fill=ORANGE)
    draw.line((75, 164, 1725, 164), fill=(218, 222, 211), width=2)

    draw.text((78, 194), '01 / ASSEMBLED', font=font(17, True), fill=MUTED)
    draw.text((78, 225), 'Designed to come apart.', font=font(32), fill=INK)
    # Supersampled orthographic views of precisely the same mesh data as the HTML.
    assembled = render_meshes(meshes, 2100, 1720).resize((1050, 860), Image.Resampling.LANCZOS)
    image.paste(assembled, (40, 310))
    draw.line((1126, 197, 1126, 1195), fill=(218, 222, 211), width=2)
    draw.text((1180, 195), '02 / EXPLODED STUDY', font=font(17, True), fill=MUTED)
    exploded = render_meshes(meshes, 1160, 1240, explode=1).resize((580, 620), Image.Resampling.LANCZOS)
    image.paste(exploded, (1150, 238))

    draw.text((1192, 891), 'PRINTED COMPONENTS', font=font(15, True), fill=MUTED)
    legend = printed_legend(meshes)
    row_height = min(22, 276 / max(len(legend), 1))
    for index, (name, hex_color) in enumerate(legend):
        y = 930 + index * row_height
        color = tuple(int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
        draw.rounded_rectangle((1194, y + 6, 1205, y + 17), radius=2, fill=color)
        draw.text((1221, y), f'{index + 1:02d}  {name}', font=font(16), fill=INK)
    reference_count = sum(mesh.get('group') == 'reference' for mesh in meshes)
    draw.text((1194, 1232), f'{reference_count} nominal hardware reference envelopes', font=font(15), fill=MUTED)
    vertices = np.concatenate([np.asarray(mesh['vertices']) for mesh in meshes])
    dimensions = np.ptp(vertices, axis=0)
    draw.text((86, 1194), 'ASSEMBLED ENVELOPE', font=font(14, True), fill=MUTED)
    text = f'{dimensions[0]:.1f} W  ×  {dimensions[1]:.1f} D  ×  {dimensions[2]:.1f} H mm'
    draw.text((86, 1220), text, font=font(26), fill=INK)
    draw.line((75, 1292, 1725, 1292), fill=(218, 222, 211), width=2)
    draw.text((76, 1315), 'ACTUAL MESH GEOMETRY  /  ELECTRONICS ARE NOMINAL REFERENCE ENVELOPES, NOT PRINTED', font=font(14), fill=MUTED)
    draw.text((1184, 1315), 'Exploded offsets are illustrative.', font=font(15), fill=MUTED)
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, default=ROOT / '3d_models/v3/assembly_meshes.json')
    parser.add_argument('--html', type=Path, default=ROOT / 'docs/robot_preview.html')
    parser.add_argument('--png', type=Path, default=ROOT / 'docs/robot_v3.png')
    parser.add_argument('--skip-png', action='store_true', help='Only refresh the interactive viewer')
    args = parser.parse_args()
    meshes = load_meshes(args.input)
    template = (ROOT / 'docs/robot_preview_template.html').read_text(encoding='utf-8')
    # Escape HTML-sensitive characters in names even though this is local build data.
    data = json.dumps(meshes, separators=(',', ':')).replace('<', '\\u003c')
    html = template.replace('__MESH_DATA__', data).replace('__GENERATED_DATE__', date.today().isoformat())
    html = html.replace('__TRIANGLE_COUNT__', f"{sum(len(m['faces']) for m in meshes):,}")
    args.html.parent.mkdir(parents=True, exist_ok=True)
    args.html.write_text(html, encoding='utf-8')
    print(f'Offline viewer: {args.html}')
    if not args.skip_png:
        make_design_sheet(meshes, args.png)
        print(f'Engineering sheet: {args.png}')


if __name__ == '__main__':
    main()
