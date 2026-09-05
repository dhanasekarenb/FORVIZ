# FORVIZ runtime and calibration

The robot uses YuNet face detection, two bounded positional servos, and one or two SSD1306 OLEDs. The main program imports the shared controllers in `servos.py` and `oled_face.py`; transfer those files together.

For printing, stock-horn capture, wiring clearances, and removable joints, use the [V3 mechanical guide](MECHANICAL_V3.md). The [print files](../3d_models/v3/stl) and [offline 3D preview](robot_preview.html) describe the enclosure. V3 is an engineering prototype intended for PLA and a 0.4 mm nozzle; physical fit and loaded operation remain untested.

## Setup and dependencies

From the project directory on the Raspberry Pi:

```bash
bash setup_pi.sh
```

The script installs Raspberry Pi camera/GPIO packages, enables I2C, attempts to start `pigpiod`, and downloads `face_detection_yunet_2023mar.onnx` if needed. Some optional operations tolerate failure, so read the command output rather than relying solely on the final message.

The Python requirements include OpenCV 4.8 or newer, NumPy, Pillow, `luma.oled`, `gpiozero`, and `pigpio`. Picamera2 is supplied by Raspberry Pi OS. Check the OpenCV version in the interpreter that will run the robot:

```bash
python3 -c "import cv2; print(cv2.__version__)"
```

If distribution packages do not satisfy [requirements.txt](../requirements.txt), install those requirements in an environment that can still access the system Picamera2 package:

```bash
sudo apt install -y python3-venv
python3 -m venv --system-site-packages .venv
. .venv/bin/activate
python3 -m pip install -r requirements.txt
```

Activate that environment again in each new terminal before running the robot. Do not install both OpenCV's desktop and headless distributions into the same environment; `--headless` is a runtime option and does not require replacing OpenCV.

For the second OLED wired to GPIO 23/24:

```bash
bash enable_dual_oled.sh
python3 test_oled.py --scan
```

The script configures software I2C bus 3. Reboot if the new bus does not appear. The [README wiring tables](../README.md#wiring) list signal pins, OLED power, and the external servo supply. The external supply and Pi share ground; servo power is separate from the Pi's positive supply output.

## First physical calibration

The commanded angles are controller estimates, not measured shaft positions. SG90 variants, stock horns, printed fits, and ribbon routing must be checked on the actual build. The enclosure uses captive stock horns and printed retainers; follow the mechanical guide without adding horn screws or altering the servo internals.

1. Run the software sequence without GPIO or camera access:

   ```bash
   python3 test_servos.py --dry-run
   ```

   This takes approximately 12 seconds and exercises the manual demo in simulation. It does not establish physical clearance.

2. With unloaded servos wired to the external supply, command neutral:

   ```bash
   python3 test_servos.py --center-only
   ```

   Both outputs hold at 90° until Ctrl+C. Stop, disconnect servo power, and fit the stock horns in the neutral orientation described in the mechanical guide. Preserve the shaft position during assembly. Support any attached head before stopping or disconnecting power, because PWM release removes holding torque.

3. Start the camera and real servos manually, initially using a small motion envelope:

   ```bash
   python3 pi_tracker.py --no-oled --headless \
     --pan-min 80 --pan-max 100 --tilt-min 80 --tilt-max 100 \
     --servo-speed 12 --scan-speed 6
   ```

   Startup commands the configured center. With no face visible, the head begins scanning. Watch cable slack, clearance, horn retention, motion direction, and load throughout this first run. Stop with Ctrl+C before correcting anything. The tracker should reduce the face's offset; if it moves away from the face or binds, correct the assembly/wiring before expanding travel.

4. Expand the limits gradually after checking the complete intended movement. Default bounds are pan 40–140° and tilt 65–115°. Keep narrower values if your assembled robot needs them. These defaults have not been physically verified on your print.

5. Test the OLEDs, then run the complete robot:

   ```bash
   python3 test_oled.py --dual
   python3 pi_tracker.py
   ```

The optional `python3 test_servos.py` command runs a physical 12-second sine-motion demonstration covering pan 55–125° and tilt 70–110°. Use it only after that motion range has been checked. It reports command completion, not a sensor-confirmed test result.

## Runtime options

```bash
python3 pi_tracker.py --help
```

| Option | Default | Effect |
| --- | --- | --- |
| `--no-servo` | Off | Simulates commanded pan/tilt angles; sends no physical servo output |
| `--no-oled` | Off | Disables physical OLED output |
| `--headless` | Automatic on systems without a detected GUI/display | Disables the camera preview and prints telemetry |
| `--preview` | Off | Requests the OpenCV desktop preview |
| `--single-oled` | Off | Uses one detected OLED with both eyes on it |
| `--dual-oled` | Off | Requests two OLEDs, falling back to available displays |
| `--pan-pin`, `--tilt-pin` | `12`, `19` | BCM GPIO signal pins; must be distinct |
| `--pan-min`, `--pan-max` | `40`, `140` | Pan limits in commanded degrees |
| `--tilt-min`, `--tilt-max` | `65`, `115` | Tilt limits in commanded degrees |
| `--pan-center`, `--tilt-center` | `90`, `90` | Startup center; scan also returns tilt to its center |
| `--servo-speed` | `36` | Maximum tracking/tilt-return speed in degrees per second |
| `--scan-speed` | `18` | Pan scan speed in degrees per second, capped by servo speed |
| `--face-loss-sec` | `1.5` | Time to hold position after the last face detection before scanning |
| `--idle-detach-after` | Disabled | Optional idle timeout in seconds that releases PWM and holding torque |
| `--model` | YuNet ONNX file beside `pi_tracker.py` | Overrides the detector model path |

`--headless` and `--preview` are mutually exclusive, as are `--single-oled` and `--dual-oled`. Centers must lie inside their configured ranges. Speeds must be positive. An explicitly supplied relative model path is resolved from the current working directory; the default model location is independent of that directory.

### Simulation still uses the camera

```bash
python3 pi_tracker.py --no-servo --no-oled --preview
```

This processes a real camera stream and calculates simulated angles for the overlay. It does not output servo PWM or OLED frames. To check software without opening a camera, use the regression suite or `test_servos.py --dry-run` instead.

`--no-oled` by itself leaves physical servo movement enabled. Read the startup backend message: `DUMMY`/simulation means no physical servo output, even if `--no-servo` was not supplied because no usable hardware backend was found.

## Tracking and eyes

`PiCameraStream` uses Picamera2 when available, with an OpenCV camera fallback. Picamera2's `RGB888` array uses BGR byte order for OpenCV, so the runtime passes it through directly; see the [Picamera2 manual](https://datasheets.raspberrypi.com/camera/picamera2-manual.pdf). YuNet chooses the largest detected face each frame; it does not identify a person or preserve a person's identity when multiple faces cross.

| State | Transition and behavior |
| --- | --- |
| `SCANNING` | Initial state with no detection, or after the face-loss timeout. Pan reverses at its configured limits and tilt moves smoothly toward the calibrated center. |
| `TRACKING` | The smoothed face center is outside the centering deadband. Each axis moves only when its own error exceeds the deadband. |
| `LOCKED` | Both normalized offsets are within ±0.08 of half the frame dimension. The eyes turn happy after one continuous second centered. |
| `HOLDING` | A previously visible face disappears for less than the configured timeout. The robot holds its last angles and displays neutral eyes. |

Face-position smoothing and servo movement use monotonic elapsed time. Each servo update accounts for at most 100 ms, limiting movement after an inference stall. A missed detection resets the happy-expression timer. A face reacquired before scanning resumes can continue from the previous smoothed position.

The eye controller probes bus 1 at the primary address and supported secondary addresses/buses. A display found only on a secondary bus becomes the primary screen. If one display fails during animation, the remaining display continues with both eyes on it. Failures are logged, and the animation thread owns display cleanup.

Manual display demos:

```bash
python3 test_oled.py --single
python3 test_oled.py --dual
```

The demo cycles through gaze directions, happy eyes, and heart eyes. Hearts are a demonstration expression, not a face-recognition result. SSD1306 output is monochrome.

## Holding torque and shutdown

Stationary servos keep PWM enabled by default. This lets the motor hold the head against gravity. The optional `--idle-detach-after` setting releases PWM after a stationary period; the head may then sag or fall. PWM release does not cut electrical supply power, eliminate all current, or guarantee safe temperatures.

Press Ctrl+C in any runtime mode, or Q/Escape in the desktop preview, to stop. Shutdown releases PWM at the current position, stops OLED animation, and releases the camera. It does not command an abrupt return to center. Support the head when releasing torque. Disconnect power before adjusting wiring or mechanical retention.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Model missing | Run `bash setup_pi.sh`; verify the ONNX file beside `pi_tracker.py`, or provide `--model`. |
| YuNet/OpenCV load error | Check the active interpreter, OpenCV version, model file, and requirements. Do not substitute a Git LFS pointer text file for the actual ONNX model. |
| Servo backend is simulation unexpectedly | Check GPIO packages and `systemctl status pigpiod`. On the supported Pi 4 setup, `sudo systemctl start pigpiod` starts the daemon when it is installed. |
| Servo hums, binds, or the Pi resets | Stop the run. Check physical clearance, load, external servo power, and shared ground before trying again. Detaching PWM is not a substitute for correcting binding. |
| Camera cannot open | Check the CSI ribbon with power disconnected, camera availability, and whether another process is using it. |
| Second OLED missing | Check bus-3 wiring/overlay and `python3 test_oled.py --scan`; two `0x3C` displays must not share the same bus. |
| No preview | Use `--preview` on a graphical desktop; use `--headless` over a terminal-only connection. |

## PC demo and automated checks

The PC webcam demonstration uses the shared YuNet detector and displays tracking telemetry without servo control:

```bash
python test_vision.py
```

On Windows, `run_pc_test.bat` runs the same script using `python` from PATH and changes to the project directory first. Q/Escape quits, C toggles the overlay, S saves a snapshot, and M switches modes when optional YOLO support is installed. The optional object detector needs Ultralytics and its model weights; the main robot does not require it.

Run hardware-free regression checks from the project directory:

```bash
python3 -m unittest discover -s tests -v
```

The tests cover motion across frame rates, stalled-frame limits, scan transitions, centering/deadband behavior, lost-face timing, OLED discovery/disconnection, rendering, and cleanup after partial initialization. Hardware demos are excluded from pytest collection. These checks do not activate a camera or establish servo calibration, print fit, load capacity, temperature, or physical collision clearance.
