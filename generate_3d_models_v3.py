"""FORVIZ V3 / FIELD — serviceable, screwless robot CAD.

All dimensions are millimetres. X is right, Y is rear, Z is up. The source
uses real Manifold boolean solids, exports independent printable STL parts,
an assembled GLB, OpenSCAD source and an auditable dimensions/mesh report.
See docs/MECHANICAL_V3.md before printing: stock servo/horn dimensions vary.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass, replace
import hashlib
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
if (ROOT / ".cad-deps").is_dir():
    sys.path.insert(0, str(ROOT / ".cad-deps"))
import manifold3d as m
import numpy as np
import trimesh


@dataclass(frozen=True)
class Dimensions:
    clearance: float = 0.35  # per mating side, NOT total diametral clearance
    wall: float = 2.4
    base_w: float = 120.0
    base_d: float = 106.0
    deck_z: float = 56.0
    head_w: float = 110.0
    head_d: float = 46.0
    head_h: float = 58.0
    pivot_z: float = 117.0
    oled_w: float = 27.5
    oled_h: float = 27.5
    oled_glass_w: float = 26.7
    oled_glass_h: float = 19.3
    oled_glass_depth: float = 2.3
    pcb_t: float = 1.6
    camera_w: float = 25.0
    camera_h: float = 24.0
    camera_aperture_d: float = 14.0
    camera_lens_offset_x: float = 0.0
    camera_lens_offset_z: float = 0.0
    oled_window_offset_z: float = 0.0
    servo_l: float = 23.2
    servo_w: float = 12.6
    servo_depth: float = 23.0  # below mounting-ear support plane
    servo_ear_l: float = 32.5
    servo_ear_t: float = 2.4
    servo_axis_offset: float = 5.7  # shaft offset from case longitudinal centre
    horn_l: float = 32.0   # supplied double arm horn; measure your particular horn
    horn_w: float = 6.0
    horn_t: float = 2.0
    horn_hub_d: float = 8.0
    horn_top_above_deck: float = 6.0
    latch_t: float = 1.2
    latch_deflection: float = 0.45
    pan_limit: float = 50.0
    tilt_limit: float = 25.0


# A small CSG wrapper keeps the OpenSCAD export identical to the evaluated mesh.
class Solid:
    def __init__(self, shape, scad):
        self.shape, self.scad = shape, scad

    def __add__(self, other):
        return Solid(self.shape + other.shape, f"union(){{{self.scad}{other.scad}}}")

    def __sub__(self, other):
        return Solid(self.shape - other.shape, f"difference(){{{self.scad}{other.scad}}}")

    def __xor__(self, other):
        return Solid(self.shape ^ other.shape, f"intersection(){{{self.scad}{other.scad}}}")

    def move(self, xyz):
        v = [float(n) for n in xyz]
        return Solid(self.shape.translate(v), f"translate({v}){{{self.scad}}}")

    def rotate(self, xyz):
        v = [float(n) for n in xyz]
        return Solid(self.shape.rotate(v), f"rotate({v}){{{self.scad}}}")

    def hull(self):
        return Solid(self.shape.hull(), f"hull(){{{self.scad}}}")


def box(x, y, z, w, d, h):
    assert min(w, d, h) > 0
    return Solid(m.Manifold.cube((w, d, h)), f"cube([{w},{d},{h}]);").move((x, y, z))


def cylinder(x, y, z, r, h, r2=None, n=48):
    top = r if r2 is None else r2
    return Solid(m.Manifold.cylinder(h, r, top, n),
                 f"cylinder(h={h},r1={r},r2={top},$fn={n});").move((x, y, z))


def union(items):
    items = list(items)
    if not items:
        return Solid(m.Manifold(), "")
    result = items[0]
    for item in items[1:]:
        result = result + item
    return result


def rounded(x, y, z, w, d, h, r=3):
    r = min(r, w / 2 - 0.01, d / 2 - 0.01)
    return union(cylinder(cx, cy, z, r, h, n=24)
                 for cx in (x + r, x + w - r)
                 for cy in (y + r, y + d - r)).hull()


def prism(points, height):
    return Solid(m.CrossSection([points]).extrude(height),
                 f"linear_extrude(height={height}) polygon({points});")


def along_x(x, y, z, r, length, r2=None):
    return cylinder(0, 0, 0, r, length, r2).rotate((0, 90, 0)).move((x, y, z))


def along_y(x, y, z, r, length):
    return cylinder(0, 0, 0, r, length).rotate((-90, 0, 0)).move((x, y, z))


def rail_y(x, y, z, length, width=5, height=3):
    # Trapezoidal section, slides along Y. Wider upper face resists lift.
    shape = prism([[-width / 2 + 1, 0], [width / 2 - 1, 0],
                   [width / 2, height], [-width / 2, height]], length)
    return shape.rotate((90, 0, 0)).move((x, y + length, z))


def horn_cut(d, z, height):
    return rounded(-d.horn_l / 2 - d.clearance, -d.horn_w / 2 - d.clearance,
                   z, d.horn_l + 2*d.clearance, d.horn_w + 2*d.clearance,
                   height, 1.5) + cylinder(0, 0, z, d.horn_hub_d/2+d.clearance, height)


@dataclass
class Part:
    name: str
    solid: Solid
    color: str
    explode: tuple
    print_rotation: tuple = (0, 0, 0)
    quantity: int = 1
    note: str = ""
    group: str = "fixed"


def spring_key(d, width=8.0, length=24.0):
    """Two 1.2mm planar beams; bidirectional ramps permit deliberate pull release.

    The rigid handle bears against the receiver. The key's shank takes shear;
    its small detents only prevent migration. Print flat, never scaled in slicer.
    """
    t = d.latch_t
    key = rounded(-7, -3, 0, 14, 5, 2.4, 1.5)
    key += box(-width/2, 0, 0, t, length-1.5, 2.4)
    key += box(width/2-t, 0, 0, t, length-1.5, 2.4)
    for sign in (-1, 1):
        x = sign*width/2
        pts = [[x-sign*(t+0.05), length-6], [x, length-6],
               [x+sign*d.latch_deflection, length-3.4],
               [x, length-1.0], [x-sign*(t+0.05), length-1.0]]
        if sign < 0:
            pts.reverse()
        key += prism(pts, 2.4)
        key += cylinder(sign*(width/2-t/2), 1, 0, t/2+0.3, 2.4, n=20)
    return key


def make_parts(d):
    c, w, H = d.clearance, d.wall, d.deck_z
    parts = []
    add = parts.append
    ivory, sage, dark, orange = "#e7e4da", "#78938d", "#263c43", "#e4a052"

    # 01 — rounded base, real hollow interior, two independent connector openings.
    base = rounded(-60, -53, 0, 120, 106, H, 14)
    base -= rounded(-60+w, -53+w, 3, 120-2*w, 106-2*w, H+1, 11.6)
    base -= rounded(-50, 46, 3, 100, 12, 33, 2)  # rear drawer entrance
    base -= box(-56.5, 39, 49.2, 113, 20, 9)  # rear entry for top deck
    base -= box(55, -32, 8, 12, 65, 27)  # USB / Ethernet insertion envelope
    base -= box(-45, -58, 8, 76, 12, 17)  # USB-C / HDMI / audio insertion envelope
    for x in (-42, -30, -18, -6, 6, 18, 30, 42):
        base -= rounded(x-2, -32, -1, 4, 66, 5, 1.8)
    for px in (-39,19):
        for py in (-24.5,24.5):
            base -= cylinder(px,py,-1,2.8,5,n=32)
    for side in (-1, 1):
        # Lower rails carry the drawer; upper rails carry the sliding deck.
        base += box(side*50.5-1.5, -43, 3, 3, 86, 4)
        base += box(-48 if side<0 else 45,-38,2.9,3,78,1.1)
        base += box(side*52.5-5.2, -40, 49.6, 10.4, 80, 2.8)
        base += rail_y(side*51, -39, 52, 78, 4.8, 2.5)
        # Tie rails to side wall without closing the connector openings.
        for y in (-39, 37):
            base += box(-58 if side<0 else 49, y, 3, 9, 6, 7)
            base += box(-58 if side<0 else 51, y, 49.6, 7, 6, 2.8)
        # Rear drawer-key receiver and deck-key receiver.
        base += box(-60 if side<0 else 49, 33, 6, 11, 12, 8)
        base -= box(-61 if side<0 else 40, 35.2, 8.2, 21, 8.6, 3.1)
        base += box(-60 if side<0 else 56.35, -36, 48.4, 3.65, 12, 7.6)
        base -= box(-61 if side<0 else 40, -33.8, 51.0, 21, 8.6, 3.1)
    # Side cooling slots stay outside the electrical connector cutouts.
    for y in (-30, -18, -6, 6, 18, 30):
        base -= box(-62, y-2, 20, 7, 4, 19)
    add(Part("01_base_shell", base, sage, (0, 0, -25), note="Floor down; supports only under upper rail roofs."))

    # 02 — PCB drawer: actual Pi mounting-hole pattern and removable snap pins.
    tray = rounded(-48.6, -42, 4, 97.2, 89, 2.4, 4)
    tray -= rounded(-34, -22, 3, 66, 44, 5, 5)
    tray += rounded(-49, 47, 3.5, 98, 4.2, 31.5, 2)
    tray -= rounded(-16, 46, 12, 32, 7, 12, 3)  # accessible pull and ventilation
    for side in (-1, 1):
        tray += box(-48.6 if side<0 else 41, 33, 6, 7.6, 12, 8)
        tray -= box(-61 if side<0 else 40, 35.2, 8.2, 21, 8.6, 3.1)
    # Pi4 holes are NOT centred along the 85mm dimension: 3.5 and61.5mm from left.
    for px in (-39,19):
        for py in (-24.5,24.5):
            tray += cylinder(px,py,6.2,3.6,2.8)
            tray -= cylinder(px,py,3,1.3,9,n=32)
    add(Part("02_electronics_drawer", tray, dark, (0, 65, -10),
             note="Floor down. Drop Pi onto four seats; retain through its mounting holes with four printed pins."))

    # 03 — removable top deck with servo ear seats and real body/wire apertures.
    deck = rounded(-56, -43, H-3.2, 112, 86, 3.2, 7)
    for side in (-1, 1):
        deck -= rail_y(side*51, -44, 52-c, 89, 4.8+2*c, 2.5+2*c)
        deck += box(-46.95 if side<0 else 40, -36, 49.5, 6.95, 12, 5.8)
        deck -= box(-61 if side<0 else 37, -33.8, 51.0, 24, 8.6, 3.1)
    # Case's long axis is X, output shaft deliberately offset from case centre.
    sx = d.servo_axis_offset
    deck -= rounded(sx-d.servo_l/2-c, -d.servo_w/2-c, H-5,
                    d.servo_l+2*c, d.servo_w+2*c, 10, 0.8)
    # Ear seats are recessed into the deck. Body can be installed from above.
    deck -= box(sx-d.servo_ear_l/2-c, -d.servo_w/2-c, H-2.4,
                d.servo_ear_l+2*c, d.servo_w+2*c, 5)
    # Bearing pedestal is separate from servo load path. Shaft/horn stays at centre.
    pedestal = cylinder(0, 0, H, 25, 4.1) - cylinder(0, 0, H-1, 17.35, 6.1)
    # Gaps give the removable servo gate access to the mounting ears.
    pedestal -= box(-27, -8, H-1, 54, 16, 7)
    deck += pedestal
    for x in (-32, 32):
        deck += box(x-4, -31, H-0.2, 8, 64, 5.5)
        deck += rail_y(x, -30, H+5, 62, 6, 2.6)
    # Keeper-key blocks accept keys from the rear. These carry no servo torque.
    for x in (-28, 28):
        deck += box(x-6, 33.35, H, 12, 9.65, 10.4)
        deck -= box(x-4.3, 22, H+6.3, 8.6, 24, 3.1)
    deck -= rounded(-15, 33, H-5, 30, 7, 11, 2)  # open rear cable route, away from shaft
    for x in (-44, 42):
        for y in (-22, -10, 2, 14):
            deck -= rounded(x-2, y-3, H-5, 4, 6, 10, 1.5)
    add(Part("03_sliding_top_deck", deck, ivory, (0, -55, 12),
             note="Underside down; localized supports beneath bearing bridges and dovetail overhangs."))

    # Pan servo ear gate slides over the recessed ears. Slot permits shaft/boss.
    gate = rounded(sx-20, -7.5, H+0.1, 40, 15, 1.2, 1.0)
    gate -= rounded(sx-d.servo_l/2-0.3, -d.servo_w/2-0.3, H-1,
                    d.servo_l+0.6, d.servo_w+0.6, 5, 1)
    # Gate is trapped axially by the pedestal and yoke when assembled.
    add(Part("04_pan_servo_gate", gate, orange, (0, -35, 27),
             note="Flat. Fit ear thickness first; trapped below the pan assembly."))

    # 05 — journal, flange, bridge, left pivot; detachable right tower joins at base.
    flange_bottom = H+4.4
    yoke = cylinder(0, 0, H+1.65, 17.0, 2.8)
    yoke += cylinder(0, 0, flange_bottom, 24, 3.2)
    yoke += cylinder(0, 0, H+7.5, 16.8, 3.5)
    yoke += rounded(-64, -18, H+11, 128, 36, 4, 6)
    # Removable stock horn slides into an underside pocket; never print splines.
    horn_top = H+d.horn_top_above_deck
    yoke -= horn_cut(d, H-2, horn_top+c-(H-2))
    yoke -= cylinder(0, 0, H-2, 6.1+c, 4.5)  # clear stationary gearbox boss
    # Left arm; X-axis extrusion of the Y/Z profile.
    profile = [[-18,H+14],[18,H+14],[18,d.pivot_z+2],
               [13,d.pivot_z+9],[-13,d.pivot_z+9],[-18,d.pivot_z+2]]
    left = prism(profile, 4).rotate((90,0,90)).move((-64,0,0))
    yoke += left
    yoke += along_x(-60.05, 0, d.pivot_z, 4, 6.5)
    yoke += along_x(-54.0, 0, d.pivot_z, 4, 0.8, 3.25)
    # Twin X-directed dovetails let the entire right tower retract from the head.
    for y in (-12, 12):
        yoke += rail_y(y, -64, H+14.8, 38, 6, 3.2).rotate((0,0,90))
    yoke += box(27, -18, H+14.8, 3, 36, 4.8)  # tower insertion hard stop
    yoke += box(48, 17.8, H+13, 12, 7, 9)
    yoke -= box(49.7, -20, H+17, 8.6, 47, 3.1)  # transverse tower locking key
    add(Part("05_pan_yoke", yoke, dark, (0, 0, 55),
             print_rotation=(0,90,0), group="pan",
             note="Left outer cheek on bed; support journal and crossbar as needed, keep bearing/pocket supports clean."))

    # 06 — front-inserted U keeper, with journal/flange running clearances.
    keeper = rounded(-37, -32, H+7.9, 74, 65, 2.5, 6)
    keeper -= cylinder(0, 0, H+7, 17.2+c, 5)
    keeper -= box(-17.2-c, 0, H+7, 34.4+2*c, 36, 5)
    for x in (-32,32):
        keeper += box(x-4.5,-31,H+5.65,9,50.5,2.45)
    for x in (-32, 32):
        keeper -= rail_y(x, -34, H+5-c, 70, 6+2*c, 2.6+2*c)
    for x in (-28, 28):
        keeper += box(x-6, 20, H+7.6, 12, 3, 2.8)
        keeper -= box(x-4.3, 18, H+6.3, 8.6, 22, 3.1)
    add(Part("06_pan_bearing_keeper", keeper, orange, (0, -60, 33),
             note="Flat; no support in running bore. Slide from FRONT after seating yoke; keys enter from rear."))

    # 07 — right tower is the complete detachable tilt drive carriage.
    tower = rounded(30.4, -18, H+15.2, 34, 36, 7, 3)
    for y in (-12, 12):
        tower -= rail_y(y, -68, H+14.8-c, 43, 6+2*c, 3.2+2*c).rotate((0,0,90))
    tower -= box(29.9,17.45,H+14.5,30.45,9,8)
    tower -= box(49.7, -20, H+17, 8.6, 47, 3.1)
    profile = [[-18,H+20],[18,H+20],[22,d.pivot_z+10],
               [17,d.pivot_z+14],[-13,d.pivot_z+14],[-18,d.pivot_z+9]]
    tower += prism(profile, 4).rotate((90,0,90)).move((60,0,0))
    # Through opening in arm admits shaft boss, while face bears on servo ears.
    tower -= along_x(59,0,d.pivot_z,6.0,8)
    # External cradle; shaft points toward -X, servo body long direction +Y.
    scy = d.servo_axis_offset
    cradle = rounded(scy-d.servo_ear_l/2-3, d.pivot_z-d.servo_w/2-3,
                     0, d.servo_ear_l+6, d.servo_w+6, d.servo_depth+7, 3)
    cradle = cradle.rotate((90,0,90)).move((64,0,0))
    cradle -= box(63, scy-d.servo_l/2-c, d.pivot_z-d.servo_w/2-c,
                  d.servo_depth+10, d.servo_l+2*c, d.servo_w+2*c)
    # Slots for factory mounting ears, and a rear wire exit.
    cradle -= box(63.9, scy-d.servo_ear_l/2-c, d.pivot_z-d.servo_w/2-c,
                  d.servo_depth+9, d.servo_ear_l+2*c, d.servo_w+2*c)
    cradle -= box(79, scy-5, d.pivot_z-12, 20, 10, 10)
    # Open outboard end for insertion; cap later captures rear of servo body.
    tower += cradle
    tower -= box(87.0, scy-d.servo_ear_l/2-1.5, d.pivot_z-d.servo_w/2-1.7,
                 3.1, d.servo_ear_l+3, d.servo_w+12)
    for side in (-1,1):
        edge=scy+side*(d.servo_ear_l/2+1.15)
        tower -= box(86.9,edge-0.7,d.pivot_z+0.7,3.3,1.4,2.6)
    add(Part("07_removable_tilt_tower", tower, sage, (65,0,45),
             print_rotation=(0,90,0), group="pan",
             note="Outer cheek down; selective supports in cradle. Install servo before sliding tower inward."))

    # Slide a broad gate across the back of tilt servo; it only bears on case edges.
    tilt_gate = rounded(87.35, scy-d.servo_ear_l/2-1.15, d.pivot_z-d.servo_w/2-1.35,
                        2.4, d.servo_ear_l+2.3, d.servo_w+2.7, 0.6)
    tilt_gate -= box(87, scy-5, d.pivot_z-3.5, 5, 10, 7)
    tilt_gate += box(87.35, scy-4, d.pivot_z+d.servo_w/2+1, 2.4, 8, 5)
    for side in (-1,1):
        edge=scy+side*(d.servo_ear_l/2+1.15)
        slit=edge-side*1.55
        tilt_gate -= box(87,slit-0.3,d.pivot_z-4.5,4,0.6,14)
        pts=[[edge-side*1.25,d.pivot_z],[edge,d.pivot_z],
             [edge+side*0.55,d.pivot_z+2],[edge,d.pivot_z+4],
             [edge-side*1.25,d.pivot_z+4]]
        if side<0:pts.reverse()
        tilt_gate += prism(pts,2.4).rotate((90,0,90)).move((87.35,0,0))
    add(Part("08_tilt_servo_gate", tilt_gate, orange, (88,0,45),
             print_rotation=(0,90,0), group="pan", note="Flat on broad face. Remove gate before removing servo."))

    # 09 — face shell. Rounded outline extruded front-to-back in Y.
    P = d.pivot_z
    outer = rounded(-55, P-29, 0, 110, 58, 39, 11).rotate((90,0,0)).move((0,16,0))
    # Inner shape starts behind a 2.4mm front face; rear remains open.
    inner = rounded(-55+w, P-29+w, 0, 110-2*w,58-2*w,40,8.6).rotate((90,0,0)).move((0,19.4,0))
    head = outer - inner
    # Three actual apertures normal to front face: the camera isn't a Z-axis hole.
    for x in (-32, 32):
        eye = rounded(x-12.4, P-7.4+d.oled_window_offset_z, 0, 24.8,14.8,8,3).rotate((90,0,0)).move((0,-18,0))
        head -= eye
    head -= along_y(d.camera_lens_offset_x,-27,P+d.camera_lens_offset_z,d.camera_aperture_d/2,12)
    # Dedicated board pockets, along Y. Boards drop from rear; over-rails retain edges.
    # Bare board fronts rest at y=-17.2; components face the bezel.
    for cx,bw,bh in [(-32,d.oled_w,d.oled_h),(32,d.oled_w,d.oled_h),(0,d.camera_w,d.camera_h)]:
        for sx in (-1,1):
            x = cx + sx*(bw/2+c)
            railx = x-1.8 if sx<0 else x
            head += box(railx,-21.0,P-bh/2-1.8,1.8,8.4,bh+3.6)
        # Edge shelves avoid pressure on chips. Back comb supplies retention.
        head += box(cx-bw/2-1.8,-21.0,P-bh/2-1.8,bw+3.6,8.4,1.8)
        for side in (-1,1):
            for zz in (P-bh/2,P+bh/2-2):
                head += box(cx+side*(bw/2-1.0)-0.6,-21.0,zz,1.2,3.5,2)
    # Head side journals: left is a plain bearing; right is a captive horn pocket.
    head += along_x(-59.65,0,P,11,7.05)
    head -= along_x(-61,0,P,4+c,14)
    head += along_x(52.6,0,P,18.2,7.05)
    # Map the Z-directed horn pocket onto X, long arm along Y.
    tilt_hole = horn_cut(d,0,4).rotate((90,0,90)).move((56.9,0,P))
    head -= tilt_hole
    head -= along_x(57,0,P,d.horn_hub_d/2+c,5)
    # Sliding rear cover rails run downwards along Z on both side walls.
    for x in (-48,48):
        # T runners retain the cover against peeling and slide open along Z.
        # Connect inner cover runners to shell through short end bridges.
        head += box(x-0.8,9.0,P-24,1.6,5.5,48)
        head += box(x-1.8,14.35,P-24,3.6,3.15,48)
        head += box(-54 if x<0 else 46.2,9.0,P-24,7.8,2.45,48)
        head += box(-54 if x<0 else 46.2,12.7,P-24,7.8,3.0,3)
        head -= box(x-3.85,11.45,P+20.8,7.7,12,15)  # open rail run-in at crown
    head -= box(-13,6,P-32,26,15,7)  # real ribbon opening in underside
    # Cover cross-key receiver at crown, outside electronics envelope.
    head += box(-6,9,P+22,12,9,5)
    head -= box(-4.3,7,P+23,8.6,14,3.1)
    add(Part("09_head_face_shell", head, ivory, (0,-45,85),
             print_rotation=(90,0,0), group="head",
             note="Face on bed. Support side journal bosses and rail overhangs only; protect the eye windows."))

    # 10 — rear cowl slides down onto cheek ledges; a pull key prevents upward removal.
    rear = rounded(-55,P-29,0,110,58,6.65,11).rotate((90,0,0)).move((0,23,0))
    rear -= rounded(-52.6,P-26.6,0,105.2,53.2,7,8.6).rotate((90,0,0)).move((0,20.6,0))
    for x in (-48,48):
        rear += box(x-3.5,11.8,P-20.5,7,9.2,41)
        rear -= box(x-1.8-c,14.0,P-35,3.6+2*c,3.9,75)
        rear -= box(x-0.8-c,11.1,P-35,1.6+2*c,3.0,75)
        rear -= box(x-4.15,11.1,P-35,8.3,6.8,14.2)  # lower rim passes rail end stop
    rear -= box(-13,9,P-32,26,18,7)
    for x in (-34,-20,20,34):
        rear -= box(x-2,18,P-16,4,9,32)
    rear -= box(-4.3,7,P+23,8.6,20,3.1)
    rear -= box(-6.35,8.6,P+21.65,12.7,9.8,5.7)
    rear -= along_x(51.5,0,P,18.2+c,11)
    rear -= box(51.5,-18.55,P-32,11,37.1,32)
    for x in (-43,43):
        rear -= box(x-1.35,15.9,P-32,2.7,4.65,16.35)
    add(Part("10_sliding_rear_cowl", rear, sage, (0,58,100),
             print_rotation=(-90,0,0), group="head",
             note="Rear face down; support inside rail roofs, leave ventilation/cable openings clear."))

    # 11 — removable PCB comb: edge bars overlap PCB backs, held by cowl pressure stops.
    comb = box(-45.9,-12.25,P-18,91.8,2.0,2.0)
    for cx,bw,bh in [(-32,d.oled_w,d.oled_h),(0,d.camera_w,d.camera_h),(32,d.oled_w,d.oled_h)]:
        for side in (-1,1):
            comb += box(cx+side*(bw/2-0.5)-0.65,-15.55,P-bh/2+0.35,1.3,4.15,bh+1.65)
            comb += box(cx+side*(bw/2-0.5)-0.65,-12.25,P-18,1.3,2.0,18-bh/2+2)
            comb += box(cx+side*(bw/2-0.5)-0.65,-17.85,P+bh/2+0.35,1.3,6.45,1.3)
    # Long spacers terminate against rear cowl interior; one part captures all three boards.
    for x in (-43,43):
        comb += box(x-1,-12.25,P-18,2,32.5,2)
    add(Part("11_display_retaining_comb", comb, orange, (0,22,83),
             print_rotation=(90,0,0), group="head",
             note="Broad comb plane down. Edge contacts only; verify PCB component clearance before fitting."))

    # 12 — universal flat locking key, with deliberately separate, replaceable flexures.
    add(Part("12_pull_release_key", spring_key(d), orange, (75,40,0),
             quantity=8, note="Print flat, 100% infill, seam away from beam roots. Fit coupon first.",group="hardware"))

    # 13 — removable board pins engage the official mounting holes, without screws.
    pcb_pin = cylinder(0,0,0,2.5,1.6,n=32)+cylinder(0,0,1.5,1.15,7.9,n=32)
    pcb_pin += cylinder(0,0,7.7,1.15,0.9,1.45,n=32)
    pcb_pin += cylinder(0,0,8.6,1.45,0.8,1.05,n=32)
    pcb_pin -= box(-0.4,-3,2.4,0.8,6,8)
    add(Part("13_pcb_snap_pin",pcb_pin,orange,(75,15,0),print_rotation=(90,0,0),quantity=4,
             note="Print on side with brim; clean support from shaft. Test pin and seat coupon before board installation.",group="hardware"))

    # Detent pockets let the pull-key beams relax in their locked position.
    # Both ramp directions are intentional: withdraw by pulling the broad handle.
    relief=box(-4.6,18.6,-0.15,9.2,4.0,2.7)
    for label,position,rotation,group in lock_positions(d):
        tool=relief.rotate(rotation).move(position)
        for part in parts:
            if part.group==group and part.group not in ("hardware","coupon"):
                part.solid=part.solid-tool

    return parts


def lock_positions(d):
    return [("drawer_left",(-62.35,39.5,8.55),(0,0,-90),"fixed"),
            ("drawer_right",(62.35,39.5,8.55),(0,0,90),"fixed"),
            ("deck_left",(-62.35,-29.5,51.35),(0,0,-90),"fixed"),
            ("deck_right",(62.35,-29.5,51.35),(0,0,90),"fixed"),
            ("keeper_left",(-28,45.35,d.deck_z+6.65),(0,0,180),"fixed"),
            ("keeper_right",(28,45.35,d.deck_z+6.65),(0,0,180),"fixed"),
            ("tower",(54,27.15,d.deck_z+17.35),(0,0,180),"pan"),
            ("cowl",(0,25.35,d.pivot_z+23.35),(0,0,180),"head")]


def placed_hardware(parts,d):
    byname={p.name:p for p in parts}
    if "12_pull_release_key" not in byname:return []
    result=[]
    for label,position,rotation,group in lock_positions(d):
        solid=byname["12_pull_release_key"].solid.rotate(rotation).move(position)
        result.append(Part("key_"+label,solid,"#e4a052",(0,20,20),group=group))
    for px in (-39,19):
        for py in (-24.5,24.5):
            solid=byname["13_pcb_snap_pin"].solid.rotate((180,0,0)).move((px,py,12.2))
            result.append(Part(f"pcb_pin_{px}_{py}",solid,"#e4a052",(0,55,0),group="fixed"))
    return result


def reference_parts(d):
    """Nominal bought-component envelopes; illustration/clearance checks, never STLs.

    These are not manufacturer STEP models. Connector/header variants and horn
    axial stacks still need comparison with the user's physical components.
    """
    H,P=d.deck_z,d.pivot_z
    refs=[]
    def ref(name,solid,color,group="reference"):
        refs.append(Part(name,solid,color,(0,0,0),group=group))
    pcb=box(-42.5,-28,9,85,56,d.pcb_t)
    for x in (-39,19):
        for y in (-24.5,24.5):pcb-=cylinder(x,y,8,1.35,5,n=32)
    ref("reference_Pi4_board",pcb,"#33594a")
    ports=union(box(31,y,10.6,14,13.5,15.5) for y in (-26.5,-9.5,7.5))
    ref("reference_USB_Ethernet",ports,"#98a4a7")
    ref("reference_Pi_CPU",box(-8,-8,10.6,15,15,3),"#26383b")
    ref("reference_Pi_GPIO",box(-35,21,10.6,50,5.2,10),"#26383b")
    body=box(d.servo_axis_offset-d.servo_l/2,-d.servo_w/2,H-2.4-d.servo_depth,
             d.servo_l,d.servo_w,d.servo_depth+2.4)
    body+=box(d.servo_axis_offset-d.servo_ear_l/2,-d.servo_w/2,H-2.4,d.servo_ear_l,d.servo_w,2.4)
    body+=cylinder(0,0,H,5.5,2)+cylinder(0,0,H+1.9,2.4,2.6)
    ref("reference_pan_SG90",body,"#38566e")
    arm=rounded(-d.horn_l/2,-d.horn_w/2,H+d.horn_top_above_deck-d.horn_t,
                d.horn_l,d.horn_w,d.horn_t,1.5)
    arm+=cylinder(0,0,H+2.2,d.horn_hub_d/2,2.3)
    arm-=cylinder(0,0,H+1.9,2.25,4.5)
    ref("reference_pan_stock_horn",arm,"#cbd2cc")
    scy=d.servo_axis_offset
    servo=box(64,scy-d.servo_l/2,P-d.servo_w/2,d.servo_depth,d.servo_l,d.servo_w)
    servo+=box(64,scy-d.servo_ear_l/2,P-d.servo_w/2,d.servo_ear_t,d.servo_ear_l,d.servo_w)
    servo+=along_x(61.8,0,P,5.5,2.2)+along_x(59.5,0,P,2.4,2.4)
    ref("reference_tilt_SG90",servo,"#38566e")
    tilt_arm=rounded(-d.horn_l/2,-d.horn_w/2,0,d.horn_l,d.horn_w,d.horn_t,1.5)
    tilt_arm+=cylinder(0,0,d.horn_t-0.05,d.horn_hub_d/2,1.8)
    tilt_arm-=cylinder(0,0,-0.1,2.25,5)
    tilt_arm=tilt_arm.rotate((90,0,90)).move((57.25,0,P))
    ref("reference_tilt_stock_horn",tilt_arm,"#cbd2cc")
    for cx,bw,bh,name in [(-32,d.oled_w,d.oled_h,"left_OLED"),(32,d.oled_w,d.oled_h,"right_OLED"),(0,d.camera_w,d.camera_h,"camera")]:
        ref("reference_"+name+"_PCB",box(cx-bw/2,-17.5,P-bh/2,bw,d.pcb_t,bh),"#33594a")
        if cx:
            glass=rounded(cx-d.oled_glass_w/2,P-d.oled_glass_h/2+d.oled_window_offset_z,
                          0,d.oled_glass_w,d.oled_glass_h,d.oled_glass_depth,1).rotate((90,0,0)).move((0,-17.5,0))
            ref("reference_"+name+"_glass",glass,"#162d35")
            eye=rounded(cx-5.4,P-4.25+d.oled_window_offset_z,0,10.8,8.5,0.04,1.8).rotate((90,0,0)).move((0,-17.5-d.oled_glass_depth-0.05,0))
            ref("reference_"+name+"_eye",eye,"#c7f5df")
            pupil=rounded(cx-2.25,P-2.35+d.oled_window_offset_z,0,4.5,4.7,0.04,0.8).rotate((90,0,0)).move((0,-17.5-d.oled_glass_depth-0.11,0))
            ref("reference_"+name+"_pupil",pupil,"#162d35")
            ref("reference_"+name+"_header",box(cx-5.2,-15.9,P+bh/2-2,10.4,7,5),"#26383b")
    ref("reference_camera_lens",along_y(d.camera_lens_offset_x,-26.5,P+d.camera_lens_offset_z,4.25,9),"#172d33")
    for refpart in refs:
        name=refpart.name
        if "Pi" in name or "USB" in name:refpart.explode=(0,65,-10)
        elif "pan_SG90" in name:refpart.explode=(0,-55,12)
        elif "pan_stock" in name:refpart.explode=(0,0,45)
        elif "tilt_SG90" in name:refpart.explode=(65,0,45)
        elif "tilt_stock" in name:refpart.explode=(15,-25,85)
        else:refpart.explode=(0,0,85)
    return refs


def coupons(d):
    """Small real mating features, not only a ruler with nominal numbers."""
    female = box(-34,-22,0,68,44,2.4)
    for i,gap in enumerate((0.2,0.35,0.5)):
        x=-23+i*23
        block=box(x-7,-17,2.3,14,22,7)
        block-=box(x-4-gap,-18,4.4,8+2*gap,24,2.4+2*gap)
        # 1/2/3 small dimples identify increasing clearances without tiny text.
        for mark in range(i+1):
            block-=cylinder(x-3+mark*3,-12,8.3,0.7,2,n=16)
        female+=block
    male=spring_key(d)
    # Bearing/horn pocket coupon receives the supplied horn and a separate gauge puck.
    horn=rounded(-23,-23,0,46,46,5,5)-horn_cut(d,1.8,5)
    horn-=cylinder(0,0,-1,d.horn_hub_d/2+d.clearance,8)
    journal=cylinder(0,0,0,19,4)-cylinder(0,0,-1,17+d.clearance,6)
    puck=cylinder(0,0,0,17,4)+cylinder(0,0,4,8,3)
    sg90=rounded(-20,-12,0,40,24,3,3)
    sg90-=rounded(-d.servo_l/2-d.clearance,-d.servo_w/2-d.clearance,-1,
                   d.servo_l+2*d.clearance,d.servo_w+2*d.clearance,5,0.8)
    pcb_seat=rounded(-10,-8,0,20,16,5,2)-cylinder(0,0,-1,1.3,8,n=32)
    pcb_gauge=rounded(-8,-6,0,16,12,1.6,1)-cylinder(0,0,-1,1.35,4,n=32)
    return [Part("fit_01_key_receivers",female,"#78938d",(0,0,0),group="coupon",note="1/2/3 dimples = 0.20/0.35/0.50 mm per side."),
            Part("fit_02_key",male,"#e4a052",(0,0,0),group="coupon"),
            Part("fit_03_stock_horn_pocket",horn,"#78938d",(0,0,0),group="coupon"),
            Part("fit_04_journal_ring",journal,"#78938d",(0,0,0),group="coupon"),
            Part("fit_05_journal_plug",puck,"#e4a052",(0,0,0),group="coupon"),
            Part("fit_06_servo_body_gauge",sg90,"#78938d",(0,0,0),group="coupon"),
            Part("fit_07_pcb_pin_seat",pcb_seat,"#78938d",(0,0,0),group="coupon",note="Stack fit08 above this seat for6.6mm capture stack."),
            Part("fit_08_dummy_pcb",pcb_gauge,"#e4a052",(0,0,0),group="coupon")]


def mesh_of(solid):
    raw=solid.shape.simplify(0.0001).to_mesh()
    return trimesh.Trimesh(vertices=np.asarray(raw.vert_properties)[:,:3],
                           faces=np.asarray(raw.tri_verts),process=True)


def hex_color(value):
    return [int(value[i:i+2],16) for i in (1,3,5)]+[255]


def inspect_part(part):
    mesh=mesh_of(part.solid)
    components=mesh.split(only_watertight=False)
    info={"name":part.name,"triangles":len(mesh.faces),"watertight":bool(mesh.is_watertight),
          "winding_consistent":bool(mesh.is_winding_consistent),"positive_volume":bool(mesh.volume>0),
          "connected_components":len(components),"volume_mm3":round(float(mesh.volume),2),
          "bounds_mm":np.round(mesh.bounds,3).tolist(),"quantity":part.quantity,
          "print_rotation_degrees":part.print_rotation,"print_note":part.note,"group":part.group}
    return mesh,info


def check_motion(parts,d):
    byname={p.name:p for p in parts}
    if "01_base_shell" not in byname:
        return {"states_checked":0,"failures":[]}
    get=lambda name: byname[name].solid.shape
    join=lambda names: union(byname[n].solid for n in names).shape
    fixed=join([p.name for p in parts if p.group=="fixed"])
    pan=join([p.name for p in parts if p.group=="pan"])
    head=join([p.name for p in parts if p.group=="head"])
    failures=[];count=0
    def overlap(a,b,label):
        nonlocal count
        count+=1
        result=a^b
        vol=result.volume()
        if vol>0.01:
            failures.append({"check":label,"overlap_mm3":round(vol,3),
                             "bounds":np.round(mesh_of(Solid(result,"")).bounds,2).tolist()})
    for pa in (-d.pan_limit,-d.pan_limit/2,0,d.pan_limit/2,d.pan_limit):
        moving_pan=pan.rotate((0,0,pa))
        overlap(moving_pan,fixed,f"pan {pa}")
        for ti in (-d.tilt_limit,-d.tilt_limit/2,0,d.tilt_limit/2,d.tilt_limit):
            moving_head=head.translate((0,0,-d.pivot_z)).rotate((ti,0,0)).translate((0,0,d.pivot_z)).rotate((0,0,pa))
            overlap(moving_head,fixed,f"head/fixed pan={pa} tilt={ti}")
            overlap(moving_head,moving_pan,f"head/yoke pan={pa} tilt={ti}")
    # Check actual approach directions, not just assembled endpoints.
    paths=[("02_electronics_drawer",["01_base_shell"],(0,1,0),[1,5,15,40,90,120]),
           ("03_sliding_top_deck",["01_base_shell"],(0,1,0),[1,5,15,40,90,120]),
           ("06_pan_bearing_keeper",["03_sliding_top_deck","05_pan_yoke"],(0,-1,0),[1,5,15,35,65,100]),
           ("07_removable_tilt_tower",["05_pan_yoke","09_head_face_shell"],(1,0,0),[1,3,10,25,45,70]),
           ("04_pan_servo_gate",["03_sliding_top_deck"],(0,0,1),[0.5,1,3,6,12,20]),
           ("10_sliding_rear_cowl",["09_head_face_shell","11_display_retaining_comb"],(0,0,1),[0.5,1,3,6,12,20,35,55,80]),
           ("11_display_retaining_comb",["09_head_face_shell"],(0,1,0),[1,3,10,25,45,70])]
    for name,against,direction,distances in paths:
        static=join(against)
        for distance in distances:
            overlap(get(name).translate(tuple(distance*a for a in direction)),static,f"insert {name} distance={distance}")
    return {"states_checked":count,"failures":failures,
            "scope":"Discrete rigid printed-part poses and insertion samples; excludes flexible wires and real-component variation."}


def export(parts,d,out):
    out.mkdir(parents=True,exist_ok=True)
    stldir=out/"stl";stldir.mkdir(exist_ok=True)
    scene=trimesh.Scene()
    reports=[];viewer=[];scad=["// Generated by generate_3d_models_v3.py. All units mm.\n// Edit Dimensions or use --config and regenerate to change fits.\npart = \"assembly\"; // or a module name listed below\nexploded = 0; // 0 assembled, 1 exploded\nshow_references = true; // bought hardware, never printable\n"]
    failures=[]
    for part in parts:
        mesh,info=inspect_part(part)
        if not (info["watertight"] and info["winding_consistent"] and info["positive_volume"] and info["connected_components"]==1):
            failures.append(info)
            print("  COMPONENTS:", [np.round(item.bounds,2).tolist() for item in mesh.split(only_watertight=False)])
        printable=mesh.copy()
        angles=np.radians(part.print_rotation)
        printable.apply_transform(trimesh.transformations.euler_matrix(*angles))
        printable.apply_translation([-float(printable.bounds[0,0]),-float(printable.bounds[0,1]),-float(printable.bounds[0,2])])
        printable.export(stldir/f"{part.name}.stl")
        info["stl_sha256"]=hashlib.sha256((stldir/f"{part.name}.stl").read_bytes()).hexdigest()
        info["print_size_mm"]=np.round(printable.extents,2).tolist()
        info["estimated_solid_mass_g"]=round(float(mesh.volume)*0.00124,1)
        reports.append(info)
        module="p_"+part.name
        scad.append(f"module {module}(){{{part.solid.scad}}}\n")
        scad.append(f"if(part==\"{part.name}\") {module}();\n")
        if part.group not in ("coupon","hardware"):
            mesh.visual.face_colors=hex_color(part.color)
            scene.add_geometry(mesh,node_name=part.name,geom_name=part.name)
            viewer.append({"name":part.name,"color":part.color,"explode":part.explode,
                           "vertices":np.round(mesh.vertices,3).tolist(),"faces":mesh.faces.tolist(),"group":part.group})
            scad.append(f"if(part==\"assembly\") color(\"{part.color}\") translate(exploded*{list(part.explode)}) {module}();\n")
        print(f"{part.name}: {len(mesh.faces)} triangles, {info['connected_components']} solid(s), watertight={info['watertight']}")
    instances=placed_hardware(parts,d)
    references=reference_parts(d) if instances else []
    for part in instances+references:
        mesh=mesh_of(part.solid);mesh.visual.face_colors=hex_color(part.color)
        scene.add_geometry(mesh,node_name=part.name,geom_name=part.name)
        viewer.append({"name":part.name,"color":part.color,"explode":part.explode,
                       "vertices":np.round(mesh.vertices,3).tolist(),"faces":mesh.faces.tolist(),"group":part.group})
        condition='part=="assembly"'+(' && show_references' if part.group=="reference" else '')
        scad.append(f'if({condition}) color("{part.color}") translate(exploded*{list(part.explode)}) {{{part.solid.scad}}}\n')
    if instances:scene.export(out/"FORVIZ_V3_assembly.glb")
    (out/"FORVIZ_V3.scad").write_text("\n".join(scad),encoding="utf-8")
    (out/"assembly_meshes.json").write_text(json.dumps(viewer,separators=(",",":")),encoding="utf-8")
    collisions=[]
    assembled=[p for p in parts if p.group not in ("coupon","hardware")]+instances
    for i,a in enumerate(assembled):
        for b in assembled[i+1:]:
            overlap=a.solid.shape ^ b.solid.shape
            volume=overlap.volume()
            if volume>0.01:
                bounds=[np.round(mesh_of(Solid(piece,"")).bounds,2).tolist() for piece in overlap.decompose()]
                collisions.append({"parts":[a.name,b.name],"overlap_mm3":round(volume,3),"bounds":bounds})
    print("ASSEMBLY OVERLAPS:",json.dumps(collisions))
    motion=check_motion(parts+instances,d)
    print("MOTION/PATH CHECKS:",motion["states_checked"],"failures:",json.dumps(motion["failures"]))
    hardware_failures=[]
    for ref in references:
        for part in assembled:
            overlap=ref.solid.shape ^ part.solid.shape
            if overlap.volume()>0.01:
                hardware_failures.append({"parts":[ref.name,part.name],"overlap_mm3":round(overlap.volume(),3),
                                          "bounds":np.round(mesh_of(Solid(overlap,"")).bounds,2).tolist()})
    print("NOMINAL HARDWARE OVERLAPS:",json.dumps(hardware_failures))
    report={"design":"FORVIZ V3 FIELD","units":"mm","material":"PLA","nozzle_mm":0.4,
            "generator_sha256":hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "status":"Engineering prototype; physical fit and motion validation required",
            "dimensions":asdict(d),"parts":reports,"mesh_failures":failures,"assembly_overlaps":collisions,"motion_checks":motion,
            "nominal_hardware_overlaps":hardware_failures,
            "assumed_snap_beam_strain":round(1.5*d.latch_t*d.latch_deflection/20**2,5)}
    (out/"validation.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    if failures or collisions or motion["failures"] or hardware_failures:
        print("CAD VALIDATION FAILED; inspect validation.json before using these exports.")
        return False
    return True


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path,default=ROOT/"3d_models"/"v3")
    parser.add_argument("--clearance",type=float,default=None,help="Per-side general clearance; key slots and snap pins have separate fixed fits")
    parser.add_argument("--config",type=Path,help="JSON overrides for the component and optical fit fields")
    parser.add_argument("--coupons-only",action="store_true")
    args=parser.parse_args()
    d=Dimensions()
    allowed={"clearance","oled_w","oled_h","oled_glass_w","oled_glass_h","oled_glass_depth",
             "camera_w","camera_h","camera_aperture_d","camera_lens_offset_x","camera_lens_offset_z",
             "oled_window_offset_z","horn_l","horn_w","horn_t","horn_hub_d","horn_top_above_deck"}
    if args.config:
        try:
            values=json.loads(args.config.read_text(encoding="utf-8-sig"))
            if not isinstance(values,dict) or set(values)-allowed:
                raise ValueError("Unsupported config field. See cad/v3_fit.json and docs/MECHANICAL_V3.md")
            if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in values.values()):
                raise ValueError("All fit values must be finite numbers in millimetres")
            if any(v<=0 for k,v in values.items() if "offset" not in k):
                raise ValueError("All sizes and clearances must be positive")
            d=replace(d,**values)
        except (OSError,ValueError) as exc:
            parser.error(str(exc))
    if args.clearance is not None:d=replace(d,clearance=args.clearance)
    if not 0.15<=d.clearance<=0.65:
        parser.error("clearance must be 0.15..0.65 mm per side")
    parts=coupons(d) if args.coupons_only else make_parts(d)+coupons(d)
    if not export(parts,d,args.output):
        raise SystemExit(1)


if __name__=="__main__":
    main()
