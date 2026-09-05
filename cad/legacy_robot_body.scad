// ====================================================================
// FORVIZ AI Robot Body - Parametric OpenSCAD Model
// Open in OpenSCAD (https://openscad.org) -> Press F5 (Preview) or F6 (Render)
// ====================================================================

$fn = 48; // Smooth circular curves

// -------------------------------------------------------------
// Component Caliper Measurements (with 0.3mm 3D printing clearance)
// -------------------------------------------------------------
sg90_length = 23.0;
sg90_width  = 12.5;
sg90_height = 29.0;
sg90_ear_l  = 32.5;

oled_pcb_w  = 27.5;
oled_pcb_h  = 27.5;
oled_view_w = 24.5;
oled_view_h = 14.5;

cam_pcb_w   = 25.0;
cam_pcb_h   = 24.0;
cam_lens_d  = 8.5;

// =============================================================
// MODULE 1: Robot Head Face Shell
// Holds 2x OLED Displays + Center Camera + Back Mount for Tilt
// =============================================================
module robot_head() {
    difference() {
        // Outer rounded head box
        translate([0, 0, 26])
            cube([92, 42, 52], center=true);

        // Hollow interior
        translate([0, 2, 26])
            cube([84, 38, 44], center=true);

        // Left Eye Cutout (OLED window)
        translate([-24, -20, 28])
            cube([oled_view_w, 10, oled_view_h], center=true);

        // Right Eye Cutout (OLED window)
        translate([24, -20, 28])
            cube([oled_view_w, 10, oled_view_h], center=true);

        // Center Camera Lens Cutout
        translate([0, -20, 28])
            cylinder(d=cam_lens_d + 1.0, h=15, center=true);

        // Cable pass-through slot at bottom
        translate([0, 5, 0])
            cube([40, 20, 10], center=true);
    }

    // Rear Tilt Servo Mount Arm
    translate([0, 21, 26])
        difference() {
            cube([20, 6, 22], center=true);
            // M2 / M2.5 screw hole for servo horn
            rotate([90, 0, 0])
                cylinder(d=2.5, h=10, center=true);
        }
}

// =============================================================
// MODULE 2: Neck Tilt Gimbal Bracket
// Mounts onto Pan Servo Horn and cradles the Tilt Servo
// =============================================================
module neck_tilt_bracket() {
    difference() {
        union() {
            // Bottom circular horn disk
            cylinder(d=28, h=4);

            // Upright servo cradle block
            translate([0, 0, 18])
                cube([30, 22, 32], center=true);
        }

        // Pocket for Tilt SG90 servo
        translate([0, 0, 22])
            cube([sg90_length, sg90_width, sg90_height], center=true);

        // Screw holes for pan servo horn on bottom
        translate([0, 0, -1])
            cylinder(d=2.2, h=8);
    }
}

// =============================================================
// MODULE 3: Robot Base Torso Stand
// Stable weighted tabletop base that locks the Pan Servo
// =============================================================
module robot_base_stand() {
    difference() {
        union() {
            // Main wide circular desktop base
            cylinder(d1=85, d2=75, h=16);

            // Tapered neck collar
            translate([0, 0, 16])
                cylinder(d1=75, d2=42, h=18);
        }

        // Top socket for Pan SG90 servo
        translate([0, 0, 22])
            cube([sg90_length, sg90_width, sg90_height], center=true);

        // Wire pass-through tunnel
        translate([0, 0, 8])
            rotate([0, 45, 0])
                cylinder(d=10, h=40, center=true);
    }
}

// -------------------------------------------------------------
// Preview Assembly View
// (Uncomment individual modules below to render & export STL)
// -------------------------------------------------------------
// 1. To view assembly:
translate([0, 0, 0]) robot_base_stand();
translate([0, 0, 45]) neck_tilt_bracket();
translate([0, -15, 82]) robot_head();

// 2. To export single parts for 3D printing:
// robot_head();
// neck_tilt_bracket();
// robot_base_stand();
