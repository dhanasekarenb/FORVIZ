# FORVIZ V3 FIELD — print and assembly guide

V3 is a removable PLA enclosure for the Raspberry Pi 4, two SG90 positional servos, two 0.96-inch SSD1306 OLED boards, and Pi Camera Rev 1.3, powered externally. The robot assembles with printed slides, gates, keys, and split pins: **no added screws, horn screws, glue, or heat-set inserts**. Leave the factory-assembled servos intact.

This is an engineering prototype with checked digital geometry. Print the fit gauges first; physical fit, loaded motion, and repeated removal still require validation on your printer and components.

## Files and dimensions

Open the [interactive assembly and exploded preview](robot_preview.html), [render](robot_v3.png), or [assembled GLB](../3d_models/v3/FORVIZ_V3_assembly.glb). Print from the [V3 STL folder](../3d_models/v3/stl). The [Python CAD source](../generate_3d_models_v3.py), [fit profile](../cad/v3_fit.json), [generated OpenSCAD](../3d_models/v3/FORVIZ_V3.scad), and [validation report](../3d_models/v3/validation.json) accompany the model. Wiring, centering commands, and first motion tests are in the [runtime guide](RUNTIME.md).

| Feature | Nominal dimension / setting |
| --- | --- |
| Complete neutral assembly, including keys | 159.3 W × 106 D × 146 H mm |
| Base shell | 120 × 106 × 56 mm |
| Head shell and cowl | 110 × 46 × 58 mm |
| Tilt axis above base underside | 117 mm |
| Shell wall | 2.4 mm |
| General mating clearance | 0.35 mm per side |
| Designed motion around neutral | Pan ±50°; tilt ±25° |
| Printing target | PLA; 0.4 mm nozzle |

Front means the camera/eye side: negative Y in the CAD. Rear is positive Y, right is positive X, and up is positive Z. The wider right side houses the removable tilt-servo tower. The external power arrangement has no internal battery compartment.

The V3 folder is the current print set. Earlier generators, `robot_body.scad`, and STL files outside `3d_models/v3` are legacy designs; their parts and assembly instructions do not belong to V3.

## What to print

There are **13 production designs, 23 production pieces, and eight fit-gauge designs**. The full export contains **21 unique STL files**. Gauges are separate from the 23 pieces used in the robot.

| STL prefix | Production part | Quantity |
| --- | --- | ---: |
| 01 | Base shell | 1 |
| 02 | Electronics drawer | 1 |
| 03 | Sliding top deck | 1 |
| 04 | Pan servo gate | 1 |
| 05 | Pan yoke with left pivot | 1 |
| 06 | Pan bearing keeper | 1 |
| 07 | Removable tilt tower | 1 |
| 08 | Tilt servo gate | 1 |
| 09 | Head face shell | 1 |
| 10 | Sliding rear cowl | 1 |
| 11 | Display retaining comb | 1 |
| 12 | Pull-release key | 8 |
| 13 | PCB snap pin | 4 |

The eight keys retain the drawer, deck, and pan keeper with two keys each, plus one key for the tilt tower and one for the cowl. All are the same printable design.

Start with 0.20 mm layers, four perimeters, and approximately 20–30% infill for large parts, then inspect the slicer preview. Print keys, pins, and their gauges solid. Use your filament's calibrated PLA temperature profile. PLA is comparatively brittle and heat-sensitive; keep cooling openings clear and avoid warm storage locations. See [Prusa's PLA material guidance](https://help.prusa3d.com/article/pla_2062).

STLs are already rotated for printing and placed on Z=0. Base, drawer, and deck print underside down; the yoke and tower print on a cheek; the head prints face down; the cowl prints rear face down. Keys lie flat, and split pins lie on their side. Preserve these orientations when evaluating the gauges.

Use localized supports where required under rail roofs, journal bosses, and servo-cradle overhangs. Keep support scars and seams away from sliding faces, horn pockets, bearing surfaces, and flexure roots. Remove supports fully before fitting electronics. Per-part rotations, sizes, and support notes are recorded in [validation.json](../3d_models/v3/validation.json).

The CAD's solid-volume PLA estimates are approximately 90.4 g for the complete printed head assembly and 354.5 g for all production pieces. These assume solid plastic throughout; use the slicer's result for actual filament and print-time estimates.

## Fit gauges before the robot

| Gauge | What to check |
| --- | --- |
| `fit_01_key_receivers` + `fit_02_key` | One/two/three dimples identify 0.20/0.35/0.50 mm clearance per side. Check sliding fit and gentle beam deflection. |
| `fit_03_stock_horn_pocket` | Check both actual double-arm horns, including hub and arm shape. |
| `fit_04_journal_ring` + `fit_05_journal_plug` | Check smooth rotation and removal without forcing or excessive rocking. |
| `fit_06_servo_body_gauge` | Check both servo cases; this shallow gauge does not verify the full ear or axial stack. |
| `fit_07_pcb_pin_seat` + `fit_08_dummy_pcb` | Stack the dummy PCB above the seat for a 6.6 mm capture thickness; test a production pin before fitting the Pi. |

The straight key-gauge channels lack the installed receivers' detent pockets. They test clearance and beam flex, **not final click or release effort**. Validate one actual keyed joint before printing all eight keys. Installed key channels are 8.6 × 3.1 mm: 0.30 mm clearance per side across the 8 mm shank and 0.35 mm per side across its 2.4 mm thickness. The middle gauge is 8.7 × 3.1 mm, so it is slightly wider.

A fitted key should enter with light finger pressure, settle into its detent, and withdraw by pulling its broad handle. Its beams should relax when seated. Remove a joint by its intended release direction rather than bending the enclosure. Replace a cracked or permanently bent key. Rounded roots, favorable layer orientation, and relaxed assembled flexures follow [Protolabs' snap-fit guidance](https://www.hubs.com/knowledge-base/how-design-snap-fit-joints-3d-printing/); the actual print determines usable force and service life.

## Component fit and regeneration

The nominal fit profile assumes 27.5 × 27.5 mm OLED PCBs, 26.7 × 19.3 × 2.3 mm OLED glass, a 25 × 24 mm camera PCB, and 1.6 mm PCB thickness. The larger glass envelope differs from the visible display window. Front lands contact PCB corners; the comb retains the backs and top corners while leaving central OLED headers clear.

Dry-fit both OLEDs and the camera before closing the head. Boards must rest flat on their intended lands, with no pressure on glass, chips, lens, or connectors. Confirm the active displays and camera lens align with their apertures. Board dimensions alone do not establish the optical offsets. Raspberry Pi publishes the Camera Module 1's approximate 25 × 24 × 9 mm overall envelope in its [camera specifications](https://www.raspberrypi.com/documentation/accessories/camera.html).

Pi supports use its four mounting holes, spaced 58 × 49 mm; the hole pattern is offset along the 85 mm board dimension. Use the orientation in the preview, with USB/Ethernet toward the right opening. See the [official Pi 4 mechanical drawing](https://datasheets.raspberrypi.com/rpi4/raspberry-pi-4-mechanical-drawing.pdf).

The model assumes two supplied **double-arm stock horns, 32 × 6 × 2 mm with an 8 mm hub**. The case envelope uses 23.2 × 12.6 mm, 32.5 mm ear length, and a 5.7 mm shaft offset. These are design assumptions to compare with your parts, not universal SG90 dimensions. [Tower Pro's SG90 specification](https://towerpro.com.tw/product/sg90-7/) identifies the manufacturer's servo; other suppliers and supplied horns can differ.

The pan journal and keeper carry axial/radial restraint around the stock horn. The left pivot, head cheeks, and locked right tower restrain the tilt horn. Both retain the original spline engagement without a horn screw. Confirm each horn remains engaged throughout the available axial play; a dimensionally clear pocket does not establish spline grip or load capacity.

Edit [cad/v3_fit.json](../cad/v3_fit.json) for supported OLED board/glass sizes, camera board/aperture sizes, optical offsets, horn sizes, horn height, and general clearance. Offsets are in millimetres; positive camera X moves right and positive optical Z moves up. `--clearance` overrides the profile's general clearance, within 0.15–0.65 mm per side. **Fixed key channels and pin holes are unaffected.** Structural dimensions and servo-body assumptions require editing the Python source and rechecking geometry.

From the project directory, install the separate [CAD dependencies](../requirements-cad.txt) and regenerate:

```bash
python -m pip install -r requirements-cad.txt
python generate_3d_models_v3.py --config cad/v3_fit.json --coupons-only --output 3d_models/v3_fit_trial
python generate_3d_models_v3.py --config cad/v3_fit.json
```

For a separate clearance trial, retain the component profile and choose a new output folder:

```bash
python generate_3d_models_v3.py --config cad/v3_fit.json --clearance 0.40 --output 3d_models/v3_trial
```

Use `python3` if that is your interpreter command. CAD dependencies are unnecessary to run the robot. Keep each generated fit set together, do not scale parts in the slicer, and inspect its validation report before printing. Regeneration updates STL/GLB/SCAD and mesh data; rebuild any separately generated preview after changing dimensions.

## Assembly order

1. Complete the gauge checks and remove all supports. Identify the front/rear directions in the preview. Keep power disconnected while fitting parts.
2. Center both unloaded servos with `python3 test_servos.py --center-only`, following the [runtime calibration instructions](RUNTIME.md#first-physical-calibration). Stop the command and disconnect power. Preserve the shaft positions while assembling; do not force the gear train around by hand.
3. Drop the Pi onto the drawer's four seats in the preview's orientation. Press four pins through the Pi mounting holes until their split ends retain below the drawer. Preconnect internal leads as needed, then slide the drawer into the base **from the rear** and insert its two side keys. Leave external power disconnected.
4. Thread loose head leads through the deck's rear cable opening. Slide the **bare deck from the rear** into the base and install its two side keys. The pan servo must be absent during this slide because its body would encounter the rear wall.
5. Lower the pan servo into the deck opening, with its offset output shaft centered on the bearing. Seat the mounting ears, then lower the thin pan gate over the case and ears. Fit one centered stock horn into the yoke's underside pocket and lower the yoke onto the servo spline and journal.
6. Slide the U-shaped bearing keeper **from the front**, below the yoke bridge, until seated. Insert its two keys **from the rear**. Confirm the keeper retains the flange while the journal can rotate without binding.
7. With the right tower detached, insert its centered tilt servo from the outboard end toward the inner cheek. Slide the tilt servo gate down into its tracks until the side detents engage. Fit the second stock horn into the empty head shell's right cheek pocket.
8. Support the empty head and place its left bearing over the yoke's fixed left pivot. Slide the complete right tower inward **from the right** on its dovetails, aligning the servo spline with the head's horn. Seat the tower against its stop and insert its rear key. Re-index the stock horn if neutral alignment is wrong; do not force engagement by twisting the head.
9. Fit the OLED and camera boards into their pockets **from the rear**, with displays/lens facing forward. Connect the leads with power disconnected. Insert the comb from the rear so its fingers retain board backs and its small caps sit above board top corners. Keep headers and camera connectors clear.
10. Route a relaxed cable loop through the head underside and behind the pan bearing. Keep the ribbon away from shaft pockets, sliding tracks, and closing edges. Slide the rear cowl **downward from above** onto its guides and insert its key from the rear.
11. Inspect the complete cable route and all retainers, then perform the narrow-range powered checks in the runtime guide. Expand toward pan ±50° and tilt ±25° only after the assembled robot moves freely with its actual wiring and load.

Use the external-power wiring described in [README](../README.md#wiring) and the runtime guide. Cable slack must accommodate both axes without tension at the CSI connectors. The CAD does not model a moving ribbon or wire bundle.

For service, disconnect power and support the head before releasing a structural key. Pull keys by their handles; slide the cowl up, tower right, keeper forward, and drawer rearward. Release Pi pins by squeezing their split ends **from below the withdrawn drawer** and lifting the heads; do not pry against the PCB. Remove the pan assembly and servo before sliding the top deck out. Reverse the assembly order for deeper disassembly.

## What has been verified

The shipped [validation report](../3d_models/v3/validation.json) records 21 watertight, consistently wound, positive-volume STL designs, each containing one connected solid. It reports zero printed-part overlaps in the assembled pose, including all eight keys and four pins; 100 sampled motion/insertion checks pass; and the nominal purchased-component envelopes have zero overlap with the assembled printed parts.

Those component envelopes are simplified reference geometry, not manufacturer CAD. The checks sample rigid poses rather than every point along continuous motion, and do not establish compatibility with every servo/OLED variant, cable motion, spline retention strength, thermal behavior, fatigue, or loaded physical operation. Fit gauges and the first slow assembled run remain part of completing this prototype.
