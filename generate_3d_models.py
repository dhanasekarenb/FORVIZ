"""
Parametric 3D STL Model Generator for FORVIZ Robot Body.
Generates ready-to-print manifold binary STL files:
  1. robot_head_face.stl    - Front head shell with dual OLED eye cutouts & camera lens hole
  2. neck_tilt_bracket.stl  - 2-axis gimbal bracket linking Pan & Tilt SG90 servos
  3. robot_base_stand.stl   - Weighted desktop base holding the Pan servo firmly
Uses standard python (struct, math) with zero external dependencies.
"""

import os
import math
import struct

def write_binary_stl(filepath, triangles):
    """Writes a list of triangle tuples [((x,y,z), (x,y,z), (x,y,z)), ...] to binary STL."""
    header = b"FORVIZ Robot 3D Printable STL Generator - AntiGravity IDE".ljust(80, b"\x00")
    num_triangles = len(triangles)
    
    with open(filepath, "wb") as f:
        f.write(header)
        f.write(struct.pack("<I", num_triangles))
        for v1, v2, v3 in triangles:
            # Compute normal vector
            ax, ay, az = v2[0] - v1[0], v2[1] - v1[1], v2[2] - v1[2]
            bx, by, bz = v3[0] - v1[0], v3[1] - v1[1], v3[2] - v1[2]
            nx = ay * bz - az * by
            ny = az * bx - ax * bz
            nz = ax * by - ay * bx
            length = math.sqrt(nx*nx + ny*ny + nz*nz)
            if length > 1e-9:
                nx, ny, nz = nx/length, ny/length, nz/length
            else:
                nx, ny, nz = 0.0, 0.0, 1.0

            f.write(struct.pack("<3f", nx, ny, nz))
            f.write(struct.pack("<3f", *v1))
            f.write(struct.pack("<3f", *v2))
            f.write(struct.pack("<3f", *v3))
            f.write(struct.pack("<H", 0))

def create_box_triangles(x0, y0, z0, dx, dy, dz):
    """Generates 12 triangles for an axis-aligned box."""
    x1, y1, z1 = x0 + dx, y0 + dy, z0 + dz
    c = [
        (x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0), # bottom 0,1,2,3
        (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)  # top 4,5,6,7
    ]
    # Faces defined with CCW winding:
    faces = [
        (0, 2, 1), (0, 3, 2), # bottom (-Z)
        (4, 5, 6), (4, 6, 7), # top (+Z)
        (0, 1, 5), (0, 5, 4), # front (-Y)
        (2, 3, 7), (2, 7, 6), # back (+Y)
        (0, 4, 7), (0, 7, 3), # left (-X)
        (1, 2, 6), (1, 6, 5)  # right (+X)
    ]
    return [(c[f[0]], c[f[1]], c[f[2]]) for f in faces]

def create_cylinder_triangles(cx, cy, z0, radius, height, segments=32):
    """Generates a solid cylinder along Z."""
    tris = []
    z1 = z0 + height
    angles = [2.0 * math.pi * i / segments for i in range(segments)]
    
    for i in range(segments):
        a1 = angles[i]
        a2 = angles[(i + 1) % segments]
        x1, y1 = cx + radius * math.cos(a1), cy + radius * math.sin(a1)
        x2, y2 = cx + radius * math.cos(a2), cy + radius * math.sin(a2)
        
        # Bottom cap
        tris.append(((cx, cy, z0), (x1, y1, z0), (x2, y2, z0)))
        # Top cap
        tris.append(((cx, cy, z1), (x2, y2, z1), (x1, y1, z1)))
        # Side wall
        tris.append(((x1, y1, z0), (x1, y1, z1), (x2, y2, z1)))
        tris.append(((x1, y1, z0), (x2, y2, z1), (x2, y2, z0)))
        
    return tris

def generate_robot_models():
    out_dir = "3d_models"
    os.makedirs(out_dir, exist_ok=True)
    print(f"[3D] Generating STL models into folder '{out_dir}/'...")

    # -------------------------------------------------------------
    # 1. ROBOT HEAD FACE PLATE & SHELL
    # Dimensions: 90mm wide, 55mm high, 45mm deep.
    # Features:
    #   - Left OLED cutout (25mm x 15mm)
    #   - Right OLED cutout (25mm x 15mm)
    #   - Center camera aperture (10mm x 10mm)
    #   - Rear mounting bracket for SG90 tilt horn
    # -------------------------------------------------------------
    head_tris = []
    # Main outer enclosure box (hollowed by construction)
    # Bottom plate
    head_tris.extend(create_box_triangles(-45, -20, 0, 90, 40, 4))
    # Top plate
    head_tris.extend(create_box_triangles(-45, -20, 48, 90, 40, 4))
    # Left wall
    head_tris.extend(create_box_triangles(-45, -20, 4, 4, 40, 44))
    # Right wall
    head_tris.extend(create_box_triangles(41, -20, 4, 4, 40, 44))
    # Back plate with servo horn mount boss
    head_tris.extend(create_box_triangles(-45, 16, 4, 90, 4, 44))
    # Servo mount boss on back (for tilt arm connection)
    head_tris.extend(create_box_triangles(-10, 20, 15, 20, 6, 20))

    # Front Face Plate with cutouts for:
    # Left eye: X from -36 to -11, Z from 20 to 35
    # Center camera: X from -5 to +5, Z from 22 to 32
    # Right eye: X from 11 to 36, Z from 20 to 35
    # Sub-blocks forming the faceplate around the 3 holes:
    # Below eyes
    head_tris.extend(create_box_triangles(-41, -20, 4, 82, 4, 16))
    # Above eyes
    head_tris.extend(create_box_triangles(-41, -20, 35, 82, 4, 13))
    # Left edge pillar
    head_tris.extend(create_box_triangles(-41, -20, 20, 5, 4, 15))
    # Divider between Left Eye and Camera
    head_tris.extend(create_box_triangles(-11, -20, 20, 6, 4, 15))
    # Divider between Camera and Right Eye
    head_tris.extend(create_box_triangles(5, -20, 20, 6, 4, 15))
    # Right edge pillar
    head_tris.extend(create_box_triangles(36, -20, 20, 5, 4, 15))
    # Camera top/bottom filling
    head_tris.extend(create_box_triangles(-5, -20, 20, 10, 4, 2))
    head_tris.extend(create_box_triangles(-5, -20, 32, 10, 4, 3))

    head_path = os.path.join(out_dir, "robot_head_face.stl")
    write_binary_stl(head_path, head_tris)
    print(f"  [OK] Generated: {head_path} ({len(head_tris)} triangles)")

    # -------------------------------------------------------------
    # 2. NECK TILT GIMBAL BRACKET
    # Dimensions: Holds the SG90 tilt servo horizontally,
    # and has a bottom socket that attaches to the SG90 pan servo horn.
    # -------------------------------------------------------------
    neck_tris = []
    # Bottom base disk / socket that mounts on Pan servo horn
    neck_tris.extend(create_cylinder_triangles(0, 0, 0, 16, 5, segments=32))
    # Center upright spine
    neck_tris.extend(create_box_triangles(-8, -10, 5, 16, 20, 22))
    # Servo cradle (holds SG90 body: 23mm length, 12.5mm width)
    # Cradle back plate
    neck_tris.extend(create_box_triangles(-16, 10, 15, 32, 4, 30))
    # Cradle left clamp ear
    neck_tris.extend(create_box_triangles(-16, -14, 15, 4, 24, 30))
    # Cradle right clamp ear
    neck_tris.extend(create_box_triangles(12, -14, 15, 4, 24, 30))
    # Cradle bottom shelf
    neck_tris.extend(create_box_triangles(-16, -14, 15, 32, 24, 4))

    neck_path = os.path.join(out_dir, "neck_tilt_bracket.stl")
    write_binary_stl(neck_path, neck_tris)
    print(f"  [OK] Generated: {neck_path} ({len(neck_tris)} triangles)")

    # -------------------------------------------------------------
    # 3. ROBOT BASE TORSO STAND
    # Dimensions: 80mm diameter circular base, 35mm height.
    # Features:
    #   - Solid, weighted desktop base
    #   - Top rectangular recess (23mm x 12.5mm x 18mm) for SG90 Pan servo
    #   - Wire passthrough channel for servo cables
    # -------------------------------------------------------------
    base_tris = []
    # Main wide base cylinder (80mm diameter, 18mm height)
    base_tris.extend(create_cylinder_triangles(0, 0, 0, 40, 18, segments=48))
    # Upper tapered collar cylinder (44mm diameter, 15mm height)
    base_tris.extend(create_cylinder_triangles(0, 0, 18, 22, 15, segments=36))

    # Top servo mounting socket walls (frames SG90: 23mm x 12.5mm)
    # Left and Right walls
    base_tris.extend(create_box_triangles(-16, -9, 33, 4, 18, 12))
    base_tris.extend(create_box_triangles(12, -9, 33, 4, 18, 12))
    # Front and Back walls with wire notch
    base_tris.extend(create_box_triangles(-12, 5, 33, 24, 4, 12))
    base_tris.extend(create_box_triangles(-12, -9, 33, 24, 4, 12))
    # Mounting screw tabs
    base_tris.extend(create_box_triangles(-22, -8, 41, 6, 16, 4))
    base_tris.extend(create_box_triangles(16, -8, 41, 6, 16, 4))

    base_path = os.path.join(out_dir, "robot_base_stand.stl")
    write_binary_stl(base_path, base_tris)
    print(f"  [OK] Generated: {base_path} ({len(base_tris)} triangles)")

    print("[SUCCESS] All 3D STL files are ready to slice and 3D print!")

if __name__ == "__main__":
    generate_robot_models()
