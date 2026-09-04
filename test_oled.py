"""
Interactive OLED Robot Eyes Test Script
Run this to preview and test robot eye animations:
    python3 test_oled.py [--dual]
"""
import sys
import time
import argparse
from oled_face import OLEDDisplayController, RobotEyesRenderer

def test_on_hardware(dual_mode=False):
    print("=" * 60)
    print("        ROBOT OLED EYES EXPRESSION DEMO")
    print("=" * 60)
    print(f"Mode: {'Dual Screen (2x OLEDs)' if dual_mode else 'Single Screen (1x OLED)'}")
    print("Running 15-second expression cycle...")
    print("=" * 60)

    face = OLEDDisplayController(dual_screen=dual_mode)
    face.start()

    try:
        # 1. Neutral with blinking
        print("[1/6] Neutral Eyes (Idle blinking)...")
        face.set_expression("NEUTRAL", gaze_x=0.0, gaze_y=0.0)
        time.sleep(3)

        # 2. Looking Left
        print("[2/6] Tracking Left...")
        face.set_expression("NEUTRAL", gaze_x=-0.9, gaze_y=0.0)
        time.sleep(2)

        # 3. Looking Right
        print("[3/6] Tracking Right...")
        face.set_expression("NEUTRAL", gaze_x=0.9, gaze_y=0.0)
        time.sleep(2)

        # 4. Looking Up
        print("[4/6] Looking Up...")
        face.set_expression("NEUTRAL", gaze_x=0.0, gaze_y=-0.8)
        time.sleep(2)

        # 5. Happy Locked Face (^ ^)
        print("[5/6] Happy Face (Target Locked!)...")
        face.set_expression("HAPPY", gaze_x=0.0, gaze_y=0.0)
        time.sleep(3)

        # 6. Heart Eyes
        print("[6/6] Heart Eyes (Face Recognized!)...")
        face.set_expression("HEART", gaze_x=0.0, gaze_y=0.0)
        time.sleep(3)

        print("[Done] Demo completed.")
    except KeyboardInterrupt:
        print("\nExiting...")
    finally:
        face.stop()

def generate_preview_gif():
    """Generates an animated GIF preview of the eyes for PC/documentation."""
    renderer = RobotEyesRenderer(128, 64)
    frames = []
    
    # 1. Neutral + Blink
    for t in range(20):
        blink = (t / 10.0) if t <= 10 else ((20 - t) / 10.0)
        frames.append(renderer.render_single_screen("NEUTRAL", 0.0, 0.0, blink_pct=blink))
    
    # 2. Gaze left to right
    for x in range(-10, 11, 2):
        frames.append(renderer.render_single_screen("NEUTRAL", gaze_x=x / 10.0, gaze_y=0.0))
    
    # 3. Happy
    for _ in range(15):
        frames.append(renderer.render_single_screen("HAPPY", 0.0, 0.0))
        
    # 4. Heart
    for _ in range(15):
        frames.append(renderer.render_single_screen("HEART", 0.0, 0.0))

    gif_path = "oled_eyes_preview.gif"
    frames[0].save(
        gif_path,
        save_all=True,
        append_images=frames[1:],
        duration=70,
        loop=0
    )
    print(f"[PREVIEW] Created animated eyes preview: '{gif_path}'")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dual", action="store_true", help="Use dual OLED mode")
    parser.add_argument("--preview-gif", action="store_true", help="Generate animated GIF preview")
    args = parser.parse_args()

    if args.preview_gif:
        generate_preview_gif()
    else:
        test_on_hardware(dual_mode=args.dual)
