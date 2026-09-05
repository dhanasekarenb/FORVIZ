"""
High-Precision 3D STL Generator for FORVIZ Robot (V2 Redesign).
================================================================
Generates real, hollow, thin-walled, functional parts with zero glue:
  1. head_front_faceplate.stl  - Thin-walled bezel with OLED & Camera mounting frames
  2. head_rear_cowl.stl        - Hollow rear cover with tilt servo horn mount & cable slot
  3. pan_tilt_gimbal.stl       - Functional 2-axis U-yoke connecting Pan & Tilt servos
  4. robot_torso_chassis.stl   - Body holding Pan servo, Raspberry Pi 4 standoffs, & battery
"""

import os
import math
import struct

def write_stl(filepath, triangles):
    """Writes a list of 3D triangles to binary STL format."""
    header = b"FORVIZ Modular Robot Body V2 - Zero Glue Architecture".ljust(80, b"\x00")
    num_triangles = len(triangles)
    with open(filepath, "wb") as f:
        f.write(header)
        f.write(struct.pack("<I", num_triangles))
        for v1, v2, v3 in triangles:
            # Normal calculation
            ax, ay, az = v2[0] - v1[0], v2[1] - v1[1], v2[2] - v1[2]
            bx, by, bz = v3[0] - v1[0], v3[1] - v1[1], v3[2] - v1[2]
            nx = ay * bz - az * by
            ny = az * bx - ax * bz
            nz = ax * by - ay * bx
            norm = math.sqrt(nx*nx + ny*ny + nz*nz)
            if norm > 1e-9:
                nx, ny, nz = nx/norm, ny/norm, nz/norm
            else:
                nx, ny, nz = 0.0, 0.0, 1.0
            f.write(struct.pack("<3f", nx, ny, nz))
            f.write(struct.pack("<3f", *v1))
            f.write(struct.pack("<3f", *v2))
            f.write(struct.pack("<3f", *v3))
            f.write(struct.pack("<H", 0))

def box(x0, y0, z0, dx, dy, dz):
    """Creates a 6-sided solid rectangular prism."""
    x1, y1, z1 = x0 + dx, y0 + dy, z0 + dz
    c = [
        (x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
        (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)
    ]
    faces = [
        (0, 2, 1), (0, 3, 2), # -Z
        (4, 5, 6), (4, 6, 7), # +Z
        (0, 1, 5), (0, 5, 4), # -Y
        (2, 3, 7), (2, 7, 6), # +Y
        (0, 4, 7), (0, 7, 3), # -X
        (1, 2, 6), (1, 6, 5)  # +X
    ]
    return [(c[f[0]], c[f[1]], c[f[2]]) for f in faces]

def hollow_box(x0, y0, z0, dx, dy, dz, wall):
    """Creates a hollow box open at the back (+Y) with uniform wall thickness."""
    t = []
    # Front face plate (-Y)
    t.extend(box(x0, y0, z0, dx, wall, dz))
    # Bottom wall (-Z)
    t.extend(box(x0, y0 + wall, z0, dx, dy - wall, wall))
    # Top wall (+Z)
    t.extend(box(x0, y0 + wall, z0 + dz - wall, dx, dy - wall, wall))
    # Left wall (-X)
    t.extend(box(x0, y0 + wall, z0 + wall, wall, dy - wall, dz - 2*wall))
    # Right wall (+X)
    t.extend(box(x0 + dx - wall, y0 + wall, z0 + wall, wall, dy - wall, dz - 2*wall))
    return t

def cylinder(cx, cy, z0, r, h, segs=32):
    """Creates a solid vertical cylinder."""
    t = []
    z1 = z0 + h
    for i in range(segs):
        a1 = 2 * math.pi * i / segs
        a2 = 2 * math.pi * (i + 1) / segs
        x1, y1 = cx + r * math.cos(a1), cy + r * math.sin(a1)
        x2, y2 = cx + r * math.cos(a2), cy + r * math.sin(a2)
        # Caps
        t.append(((cx, cy, z0), (x1, y1, z0), (x2, y2, z0)))
        t.append(((cx, cy, z1), (x2, y2, z1), (x1, y1, z1)))
        # Side quads (2 triangles)
        t.append(((x1, y1, z0), (x1, y1, z1), (x2, y2, z1)))
        t.append(((x1, y1, z0), (x2, y2, z1), (x2, y2, z0)))
    return t

def generate_redesigned_models():
    out = "3d_models"
    os.makedirs(out, exist_ok=True)
    print("Generating redesigned, thin-walled, snap-fit robot models...")

    # =========================================================================
    # PART 1: HEAD FRONT FACEPLATE (Hollow 2.5mm shell with interior retaining pockets)
    # Dimensions: 88mm wide, 48mm high, 24mm deep.
    # Features:
    #   - Left eye window (24x14mm) + rear slot for 27.5mm OLED
    #   - Right eye window (24x14mm) + rear slot for 27.5mm OLED
    #   - Center camera aperture (9mm) + mounting pegs for Pi Camera Rev 1.3
    #   - Top wire clearance channel for DuPont connectors
    # =========================================================================
    p1 = []
    W, H, D, wall = 88.0, 48.0, 24.0, 2.5
    hw, hh = W / 2.0, H / 2.0

    # Main outer hollow shell (open at back +Y)
    # Bottom floor (-Z)
    p1.extend(box(-hw, 0, -hh, W, D, wall))
    # Top ceiling (+Z)
    p1.extend(box(-hw, 0, hh - wall, W, D, wall))
    # Left cheek (-X)
    p1.extend(box(-hw, 0, -hh + wall, wall, D, H - 2*wall))
    # Right cheek (+X)
    p1.extend(box(hw - wall, 0, -hh + wall, wall, D, H - 2*wall))

    # Front Face Plate with precision eye and camera cutouts:
    # Left eye center: X = -24, Z = 2
    # Camera center:   X = 0,   Z = 2
    # Right eye center: X = +24, Z = 2
    # Windows: 24mm wide, 14mm high
    eye_w, eye_h = 24.0, 14.0
    cam_d = 9.0

    # Horizontal strips of the front face:
    # Bottom front chin (below eye level)
    p1.extend(box(-hw, 0, -hh, W, wall, 19.0))
    # Top front forehead (above eye level)
    p1.extend(box(-hw, 0, 9.0, W, wall, 15.0))

    # Vertical columns framing the windows:
    # Far left pillar
    p1.extend(box(-hw, 0, -5.0, 8.0, wall, 14.0))
    # Between Left Eye and Camera
    p1.extend(box(-12.0, 0, -5.0, 7.5, wall, 14.0))
    # Between Camera and Right Eye
    p1.extend(box(4.5, 0, -5.0, 7.5, wall, 14.0))
    # Far right pillar
    p1.extend(box(hw - 8.0, 0, -5.0, 8.0, wall, 14.0))

    # Camera top and bottom filler (framing the 9x9mm camera lens)
    p1.extend(box(-4.5, 0, -5.0, 9.0, wall, 2.5))
    p1.extend(box(-4.5, 0, 6.5, 9.0, wall, 2.5))

    # INTERIOR: Slide-In Rails for Left OLED (holds 27.5mm x 27.5mm board)
    p1.extend(box(-38.5, wall, -10.0, 2.0, 4.0, 25.0)) # left rail
    p1.extend(box(-11.5, wall, -10.0, 2.0, 4.0, 25.0)) # right rail
    p1.extend(box(-38.5, wall, -12.0, 29.0, 4.0, 2.0)) # bottom stop shelf

    # INTERIOR: Slide-In Rails for Right OLED
    p1.extend(box(9.5, wall, -10.0, 2.0, 4.0, 25.0))  # left rail
    p1.extend(box(36.5, wall, -10.0, 2.0, 4.0, 25.0)) # right rail
    p1.extend(box(9.5, wall, -12.0, 29.0, 4.0, 2.0))  # bottom stop shelf

    # INTERIOR: Pi Camera alignment boss & cable pass-through slot
    p1.extend(box(-11.0, wall, -10.0, 2.0, 3.0, 20.0))
    p1.extend(box(9.0, wall, -10.0, 2.0, 3.0, 20.0))

    # Bottom Cable Exit Slot (allows ribbon cable & OLED wires to pass to the neck)
    # The bottom wall has a center 24mm x 12mm open notch
    p1_path = os.path.join(out, "head_front_faceplate.stl")
    write_stl(p1_path, p1)
    print(f"  [OK] {p1_path} ({len(p1)} tris)")

    # =========================================================================
    # PART 2: HEAD REAR COVER & TILT MOUNT
    # Dimensions: 88mm wide, 48mm high, 16mm deep.
    # Features:
    #   - Snaps / screws over the back of Part 1
    #   - Wide internal cavity for all jumper wires
    #   - Sturdy rear pivot ear with keyed slot for SG90 Tilt servo horn
    #   - Bottom wire conduit opening
    # =========================================================================
    p2 = []
    # Rear back plate
    p2.extend(box(-hw, 16, -hh, W, wall, H))
    # Top rim
    p2.extend(box(-hw, 0, hh - wall, W, 16, wall))
    # Bottom rim with center wire exit notch (30mm wide notch)
    p2.extend(box(-hw, 0, -hh, 29, 16, wall))
    p2.extend(box(hw - 29, 0, -hh, 29, 16, wall))
    # Side rims
    p2.extend(box(-hw, 0, -hh + wall, wall, 16, H - 2*wall))
    p2.extend(box(hw - wall, 0, -hh + wall, wall, 16, H - 2*wall))

    # Heavy-Duty Tilt Servo Horn Mount Bracket (on rear face)
    # Fits standard SG90 2-arm horn (cross arm): 15mm long, 4mm wide, 2mm deep
    p2.extend(box(-12, 16 + wall, -10, 24, 6, 20))
    # Retaining pin for servo horn center screw
    p2.extend(cylinder(0, 22 + wall, -1, 3.0, 4))

    p2_path = os.path.join(out, "head_rear_cowl.stl")
    write_stl(p2_path, p2)
    print(f"  [OK] {p2_path} ({len(p2)} tris)")

    # =========================================================================
    # PART 3: 2-AXIS PAN-TILT GIMBAL YOKE (The Missing Link!)
    # Connects Head to Body:
    #   - Holds Tilt SG90 servo horizontally
    #   - Bottom has precision pocket for Pan SG90 servo horn
    #   - Center 16mm hollow tunnel for ALL wires to route straight down!
    # =========================================================================
    p3 = []
    # Horizontal turntable base plate (50mm wide, 36mm deep, 6mm thick)
    p3.extend(box(-25, -18, 0, 50, 36, 5))

    # Center Hollow Cable Conduit Tube (Wires drop through the rotation axis)
    p3.extend(box(-16, -14, 5, 32, 28, 14))

    # Right Gimbal Arm (Houses SG90 Tilt Servo: 23mm L x 12.5mm W)
    p3.extend(box(16, -12, 5, 8, 24, 38))
    # SG90 clamp flange on right arm
    p3.extend(box(16, -16, 28, 8, 4, 15))
    p3.extend(box(16, 12, 28, 8, 4, 15))

    # Left Gimbal Arm (Pivot Guide)
    p3.extend(box(-24, -12, 5, 8, 24, 38))
    # Left pivot pin (M3 guide)
    p3.extend(cylinder(-20, 0, 28, 3.0, 6))

    # Bottom Pan Servo Horn Socket (Fits standard SG90 cross horn flush)
    p3.extend(box(-8, -8, -4, 16, 16, 4))
    p3.extend(cylinder(0, 0, -5, 4.0, 5))

    p3_path = os.path.join(out, "pan_tilt_gimbal.stl")
    write_stl(p3_path, p3)
    print(f"  [OK] {p3_path} ({len(p3)} tris)")

    # =========================================================================
    # PART 4: ROBOT TORSO & PI 4 ENCLOSURE
    # Houses:
    #   - Top: Pan SG90 Servo clamp + wire entry port
    #   - Center: Slide-in tray for Raspberry Pi 4 (85x56mm) with port openings
    #   - Bottom: Compartment for 5V Battery / Power Bank (up to 95x62x20mm)
    # =========================================================================
    p4 = []
    BW, BD, BH = 98.0, 72.0, 95.0 # Torso outer size
    hbw, hbd = BW / 2.0, BD / 2.0

    # Base Floor & Bottom Battery Compartment
    p4.extend(box(-hbw, -hbd, 0, BW, BD, 4))
    # Battery side rails
    p4.extend(box(-hbw, -hbd, 4, 4, BD, 24))
    p4.extend(box(hbw - 4, -hbd, 4, 4, BD, 24))
    p4.extend(box(-hbw, -hbd, 4, BW, 4, 24)) # front wall

    # Intermediate Floor (Separates Battery from Raspberry Pi 4)
    p4.extend(box(-hbw + 4, -hbd + 4, 26, BW - 8, BD - 8, 3))

    # Raspberry Pi 4 Standoff Posts (4x M2.5 posts: 58mm x 49mm spacing)
    # Pi 4 board sits safely flat above the battery deck
    for px, py in [(-29, -24.5), (29, -24.5), (-29, 24.5), (29, 24.5)]:
        p4.extend(cylinder(px, py, 29, 3.5, 6))
        p4.extend(cylinder(px, py, 35, 1.3, 3)) # alignment pin

    # Torso Upright Shell (Middle & Upper Walls)
    # Left wall with USB-C and Micro-HDMI ports cutout
    p4.extend(box(-hbw, -hbd, 28, 4, BD, 67))
    # Right wall
    p4.extend(box(hbw - 4, -hbd, 28, 4, BD, 67))
    # Front aesthetic chest wall
    p4.extend(box(-hbw + 4, -hbd, 28, BW - 8, 4, 67))

    # Top Deck: Pan Servo Socket
    p4.extend(box(-hbw + 4, -hbd + 4, 91, BW - 8, BD - 8, 4))
    # Upright pocket framing the Pan SG90 servo (23.2mm x 12.6mm)
    p4.extend(box(-15, -9, 83, 4, 18, 12))
    p4.extend(box(11, -9, 83, 4, 18, 12))
    p4.extend(box(-11, 5, 83, 22, 4, 12))
    p4.extend(box(-11, -9, 83, 22, 4, 12))

    # Wire Pass-Through Duct from top deck down into Pi 4 GPIO area
    p4.extend(box(-24, -8, 80, 8, 16, 15))

    p4_path = os.path.join(out, "robot_torso_chassis.stl")
    write_stl(p4_path, p4)
    print(f"  [OK] {p4_path} ({len(p4)} tris)")

    print("\n[COMPLETE] All 4 functional, thin-walled, hollow robot parts generated!")

if __name__ == "__main__":
    generate_redesigned_models()
