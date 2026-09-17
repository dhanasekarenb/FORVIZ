"""Hardware-free regression tests: python -m unittest discover -s tests -v."""
import contextlib
import io
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

import numpy as np
import oled_face
import pi_tracker
import servos


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class ServoTests(unittest.TestCase):
    def tracker(self, **kwargs):
        clock = FakeClock()
        with contextlib.redirect_stdout(io.StringIO()):
            tracker = servos.PanTiltTracker(hardware=False, clock=clock, **kwargs)
        self.addCleanup(tracker.close)
        return tracker, clock

    def test_tracking_rate_independent_of_fps(self):
        positions = []
        for fps in (10, 30, 60):
            tracker, clock = self.tracker()
            for _ in range(fps):
                clock.advance(1 / fps)
                tracker.track_face(400, 280)
            positions.append((tracker.current_pan, tracker.current_tilt))
        for pan, tilt in positions:
            self.assertAlmostEqual(pan, 71.25)
            self.assertAlmostEqual(tilt, 100.0)

    def test_scan_rate_independent_of_fps(self):
        for fps in (10, 30, 60):
            tracker, clock = self.tracker()
            for _ in range(fps):
                clock.advance(1 / fps)
                tracker.step_scan()
            self.assertAlmostEqual(tracker.current_pan, 108.0)

    def test_stalled_frame_cannot_jump(self):
        tracker, clock = self.tracker()
        clock.advance(9)
        tracker.track_face(640, 480)
        self.assertAlmostEqual(tracker.current_pan, 86.4)
        self.assertAlmostEqual(tracker.current_tilt, 93.6)

    def test_small_error_outside_deadband_can_move(self):
        tracker, clock = self.tracker()
        clock.advance(1 / 60)
        tracker.track_face(320 + 320 * 0.081, 240)
        self.assertLess(tracker.current_pan, 90)
        self.assertEqual(tracker.current_tilt, 90)

    def test_inverted_tilt_and_pan_direction(self):
        tracker, clock = self.tracker(invert_pan=True, invert_tilt=True)
        clock.advance(0.1)
        # Target to the right (400 > 320) and down (350 > 240)
        tracker.track_face(400, 350)
        # Normally pan would decrease (-dx), but with invert_pan it increases
        self.assertGreater(tracker.current_pan, 90)
        # Normally tilt would increase (+dy), but with invert_tilt it decreases
        self.assertLess(tracker.current_tilt, 90)

    def test_deadband_is_independent_per_axis(self):
        tracker, clock = self.tracker()
        clock.advance(0.1)
        tracker.track_face(320 + 320 * 0.07, 350)
        self.assertEqual(tracker.current_pan, 90)
        self.assertGreater(tracker.current_tilt, 90)

    def test_scan_eases_tilt_and_respects_custom_center(self):
        tracker, clock = self.tracker(tilt_range=(100, 130), tilt_center=112, pan_center=85)
        tracker.set_direct(100, 130)
        clock.advance(0.05)
        tracker.step_scan()
        self.assertAlmostEqual(tracker.current_tilt, 128.2)
        for _ in range(100):
            clock.advance(0.05)
            tracker.step_scan()
            self.assertTrue(100 <= tracker.current_tilt <= 130)
            self.assertTrue(40 <= tracker.current_pan <= 140)
        self.assertEqual(tracker.current_tilt, 112)
        tracker.center()
        self.assertEqual((tracker.current_pan, tracker.current_tilt), (85, 112))

    def test_boundary_reverses_scan(self):
        tracker, clock = self.tracker()
        tracker.set_direct(140, 90)
        clock.advance(0.1)
        tracker.step_scan()
        self.assertEqual(tracker.scan_direction, -1)
        clock.advance(0.1)
        tracker.step_scan()
        self.assertLess(tracker.current_pan, 140)

    def test_pwm_holds_by_default_and_detach_is_opt_in(self):
        tracker, clock = self.tracker()
        clock.advance(10)
        tracker.hold()
        self.assertFalse(tracker.is_sleeping)
        tracker, clock = self.tracker(idle_timeout_sec=0.6)
        clock.advance(0.61)
        tracker.hold()
        self.assertTrue(tracker.is_sleeping)
        clock.advance(0.02)
        tracker.track_face(500, 240)
        self.assertFalse(tracker.is_sleeping)

    def test_bounds_and_invalid_input(self):
        tracker, _ = self.tracker()
        self.assertEqual(tracker.set_direct(-99, 999), (40, 115))
        for coords in ((float('nan'), 240, 640, 480), (10, 10, 0, 480)):
            with self.assertRaises(ValueError):
                tracker.track_face(*coords)
        with self.assertRaises(ValueError):
            self.tracker(tilt_range=(95, 115), tilt_center=90)


def face_at(x=320, y=240, width=80, height=80):
    return {'box': (x - width / 2, y - height / 2, width, height)}


class StateTests(unittest.TestCase):
    def test_lost_face_holds_then_scans(self):
        state = pi_tracker.FaceTrackingState()
        state.update([face_at()], 640, 480, 0)
        state.update([], 640, 480, 1.49)
        self.assertEqual(state.state_name, 'HOLDING')
        state.update([], 640, 480, 1.5)
        self.assertEqual(state.state_name, 'SCANNING')
        self.assertIsNone(state.smooth_cx)

    def test_starts_scanning_without_initial_hold(self):
        state = pi_tracker.FaceTrackingState()
        state.update([], 640, 480, 0)
        self.assertEqual(state.state_name, 'SCANNING')

    def test_zero_loss_hold_does_not_disable_face_smoothing(self):
        state = pi_tracker.FaceTrackingState(face_loss_sec=0)
        state.update([face_at(x=300)], 640, 480, 0)
        state.update([face_at(x=400)], 640, 480, 1 / 30)
        self.assertGreater(state.smooth_cx, 300)
        self.assertLess(state.smooth_cx, 400)
        state.update([], 640, 480, 0.1)
        self.assertEqual(state.state_name, 'SCANNING')

    def test_face_lock_timing_resets_after_detection_gap(self):
        state = pi_tracker.FaceTrackingState()
        state.update([face_at()], 640, 480, 0)
        state.update([face_at()], 640, 480, 1)
        self.assertEqual(state.mood, 'HAPPY')
        self.assertTrue(state.just_settled)
        state.update([face_at()], 640, 480, 1.1)
        self.assertFalse(state.just_settled)
        state.update([], 640, 480, 1.1)
        state.update([face_at()], 640, 480, 1.2)
        self.assertEqual(state.mood, 'NEUTRAL')
        state.update([face_at()], 640, 480, 2.21)
        self.assertEqual(state.mood, 'HAPPY')
        self.assertTrue(state.just_settled)

    def test_lock_and_servo_deadbands_match(self):
        state = pi_tracker.FaceTrackingState()
        state.update([face_at(x=349)], 640, 480, 0)
        self.assertEqual(state.state_name, 'TRACKING')
        state = pi_tracker.FaceTrackingState()
        state.update([face_at(x=344)], 640, 480, 0)
        self.assertEqual(state.state_name, 'LOCKED')

    def test_largest_face_and_reacquisition(self):
        state = pi_tracker.FaceTrackingState()
        small, large = face_at(x=100, width=20), face_at(x=500)
        self.assertIs(state.update([small, large], 640, 480, 0), large)
        state.update([], 640, 480, 2)
        state.update([face_at(x=200)], 640, 480, 2.1)
        self.assertEqual(state.smooth_cx, 200)
        # Test inverted gaze
        # A face above centre has negative Y, matching an upward pupil offset.
        state.update([face_at(x=500, y=100)], 640, 480, 2.2)
        self.assertGreater(state.gaze_x, 0)
        self.assertLess(state.gaze_y, 0)
        # Inverted gaze flips it
        state.update([face_at(x=500, y=100)], 640, 480, 2.3, invert_gaze_x=True, invert_gaze_y=True)
        self.assertLess(state.gaze_x, 0)
        self.assertGreater(state.gaze_y, 0)

    def test_vertical_pupils_follow_face_at_both_tilt_limits(self):
        frames = []
        for face_y, limit in ((80, 115), (400, 65)):
            with self.subTest(face_y=face_y):
                clock = FakeClock()
                with contextlib.redirect_stdout(io.StringIO()):
                    tracker = servos.PanTiltTracker(hardware=False, clock=clock,
                                                   invert_tilt=True)
                self.addCleanup(tracker.close)
                tracker.set_direct(90, limit)
                state = pi_tracker.FaceTrackingState()
                state.update([face_at(y=face_y)], 640, 480, 0)
                clock.advance(0.1)
                pan, tilt = tracker.track_face(state.smooth_cx, state.smooth_cy)
                self.assertEqual((pan, tilt), (90, limit))
                self.assertEqual(state.gaze_x, 0)
                frames.append(np.asarray(oled_face.RobotEyesRenderer().render_single_eye(
                    state.mood, state.gaze_x, state.gaze_y)))
        # The dark pupil occupies more of the upper half when looking up,
        # and more of the lower half when looking down, even with tilt clamped.
        up, down = frames
        self.assertLess(up[:32].sum(), down[:32].sum())
        self.assertGreater(up[32:].sum(), down[32:].sum())


class DisplayTests(unittest.TestCase):
    def controller(self, available, **kwargs):
        devices = {key: Mock() for key in available}

        def connect(port, address):
            if (port, address) not in devices:
                raise OSError('absent')
            return devices[(port, address)]

        with (patch.object(oled_face, 'LUMA_AVAILABLE', True),
              patch.object(oled_face, 'i2c', side_effect=connect, create=True),
              patch.object(oled_face, 'ssd1306', side_effect=lambda serial, rotate=0: serial, create=True),
              contextlib.redirect_stdout(io.StringIO())):
            controller = oled_face.OLEDDisplayController(**kwargs)
        self.addCleanup(controller.stop)
        return controller, devices

    def test_only_secondary_display_becomes_primary(self):
        controller, devices = self.controller([(3, 0x3C)])
        self.assertIs(controller.dev1, devices[(3, 0x3C)])
        self.assertFalse(controller.dual_screen)
        controller._display_frame(0)
        devices[(3, 0x3C)].display.assert_called_once()

    def test_explicit_single_mode_uses_only_one_device(self):
        controller, devices = self.controller([(1, 0x3C), (3, 0x3C)], dual_screen=False)
        self.assertFalse(controller.dual_screen)
        self.assertIsNone(controller.dev2)

    def test_display_failure_preserves_other_screen(self):
        controller, devices = self.controller([(1, 0x3C), (3, 0x3C)])
        devices[(1, 0x3C)].display.side_effect = OSError('disconnected')
        with contextlib.redirect_stdout(io.StringIO()):
            controller._display_frame(0)
        self.assertIs(controller.dev1, devices[(3, 0x3C)])
        self.assertFalse(controller.dual_screen)
        controller._display_frame(0)
        self.assertEqual(devices[(3, 0x3C)].display.call_count, 2)

    def test_worker_shutdown_and_duplicate_start(self):
        controller, devices = self.controller([(1, 0x3C)])
        controller.start()
        original_thread = controller.thread
        controller.start()
        self.assertIs(controller.thread, original_thread)
        controller.stop()
        self.assertFalse(controller.thread.is_alive())
        self.assertFalse(controller.running)
        devices[(1, 0x3C)].cleanup.assert_called_once()

    def test_single_eye_mode_renders_one_big_eye(self):
        controller, devices = self.controller([(1, 0x3C)], single_eye=True)
        controller._display_frame(0)
        devices[(1, 0x3C)].display.assert_called_once()
        frame = devices[(1, 0x3C)].display.call_args[0][0]
        self.assertEqual(frame.size, (128, 64))

    def test_eye_rendering_variants(self):
        renderer = oled_face.RobotEyesRenderer()
        for mood in ('NEUTRAL', 'HAPPY', 'HEART', 'NIGHTMARE', 'NARUTO', 'UCHIHA'):
            for blink in (0, 0.5, 1):
                for image in (renderer.render_single_screen(mood, -1, 1, blink),
                              renderer.render_single_eye(mood, 0, 0, blink),
                              *renderer.render_dual_screen(mood, 1, -1, blink)):
                    self.assertEqual(image.size, (128, 64))
                    self.assertEqual(image.mode, '1')
                    self.assertIsNotNone(image.getbbox())

    def test_full_screen_eye_coverage_and_animation(self):
        renderer = oled_face.RobotEyesRenderer()
        neutral = renderer.render_single_eye()
        left, top, right, bottom = neutral.getbbox()
        self.assertGreaterEqual(right - left, 120)
        self.assertGreaterEqual(bottom - top, 58)
        self.assertEqual(neutral.tobytes(), renderer.render_dual_screen()[0].tobytes())
        self.assertNotEqual(renderer.render_single_eye(gaze_x=-1).tobytes(),
                            renderer.render_single_eye(gaze_x=1).tobytes())
        blink = renderer.render_single_eye(blink_pct=1).getbbox()
        self.assertLessEqual(blink[3] - blink[1], 3)
        for mood in ('NEUTRAL', 'HAPPY', 'HEART', 'NIGHTMARE', 'NARUTO', 'UCHIHA'):
            for frame in (renderer.render_single_eye(mood), *renderer.render_dual_screen(mood)):
                left, top, right, bottom = frame.getbbox()
                self.assertGreater(left, 0)
                self.assertGreater(top, 0)
                self.assertLess(right, frame.width)
                self.assertLess(bottom, frame.height)

    def test_nightmare_eye_is_distinct_and_tracks_gaze(self):
        renderer = oled_face.RobotEyesRenderer()
        neutral = renderer.render_single_eye('NEUTRAL')
        nightmare = renderer.render_single_eye('NIGHTMARE')
        left = renderer.render_single_eye('NIGHTMARE', gaze_x=-1)
        right = renderer.render_single_eye('NIGHTMARE', gaze_x=1)
        self.assertNotEqual(neutral.tobytes(), nightmare.tobytes())
        self.assertNotEqual(left.tobytes(), right.tobytes())

    def test_naruto_eye_is_distinct_and_tracks_gaze(self):
        renderer = oled_face.RobotEyesRenderer()
        neutral = renderer.render_single_eye('NEUTRAL')
        naruto = renderer.render_single_eye('NARUTO')
        left = renderer.render_single_eye('NARUTO', gaze_x=-1)
        right = renderer.render_single_eye('NARUTO', gaze_x=1)
        self.assertNotEqual(neutral.tobytes(), naruto.tobytes())
        self.assertNotEqual(left.tobytes(), right.tobytes())

    def test_uchiha_eye_is_distinct_and_tracks_gaze(self):
        renderer = oled_face.RobotEyesRenderer()
        neutral = renderer.render_single_eye('NEUTRAL')
        uchiha = renderer.render_single_eye('UCHIHA')
        left = renderer.render_single_eye('UCHIHA', gaze_x=-1)
        right = renderer.render_single_eye('UCHIHA', gaze_x=1)
        self.assertNotEqual(neutral.tobytes(), uchiha.tobytes())
        self.assertNotEqual(left.tobytes(), right.tobytes())
        for point in ((3, 32), (64, 3), (124, 32), (64, 60)):
            self.assertEqual(uchiha.getpixel(point), 1)

    def test_uchiha_activation_opens_and_builds_the_pattern(self):
        renderer = oled_face.RobotEyesRenderer()
        closed = renderer.render_single_eye('UCHIHA', effect_progress=0.0)
        forming = renderer.render_single_eye('UCHIHA', effect_progress=0.5)
        complete = renderer.render_single_eye('UCHIHA', effect_progress=1.0)
        closed_box = closed.getbbox()
        self.assertLessEqual(closed_box[3] - closed_box[1], 3)
        self.assertNotEqual(closed.tobytes(), forming.tobytes())
        self.assertNotEqual(forming.tobytes(), complete.tobytes())
        self.assertEqual(complete.tobytes(),
                         renderer.render_single_eye('UCHIHA').tobytes())

    def test_uchiha_activation_restarts_only_when_mode_is_entered(self):
        controller, _ = self.controller([], hardware=False)
        with patch.object(oled_face.time, 'monotonic',
                          side_effect=(10.0, 11.0, 12.0, 13.0)):
            controller.set_expression('UCHIHA')
            started = controller._expression_started_at
            controller.set_expression('UCHIHA', gaze_x=0.5)
            self.assertEqual(controller._expression_started_at, started)
            controller.set_expression('UCHIHA', restart_effect=True)
            self.assertEqual(controller._expression_started_at, 11.0)
            controller.set_expression('NEUTRAL')
            self.assertEqual(controller._expression_started_at, 12.0)
            controller.set_expression('UCHIHA')
            self.assertEqual(controller._expression_started_at, 13.0)


class IntegrationTests(unittest.TestCase):
    def test_model_path_and_shared_controllers(self):
        self.assertTrue(Path(pi_tracker.YUNET_MODEL_PATH).is_absolute())
        self.assertIs(pi_tracker.PanTiltTracker, servos.PanTiltTracker)
        self.assertIs(pi_tracker.OLEDDisplayController, oled_face.OLEDDisplayController)

    def test_invalid_cli_rejected_before_hardware(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            pi_tracker.parse_args(['--pan-min', '100', '--pan-center', '90'])

    def test_picamera_rgb888_array_already_bgr(self):
        camera = pi_tracker.PiCameraStream.__new__(pi_tracker.PiCameraStream)
        camera.use_picam2 = True
        camera.picam2 = Mock()
        frame = np.array([[[5, 10, 250]]], dtype=np.uint8)
        camera.picam2.capture_array.return_value = frame
        ok, returned = camera.read()
        self.assertTrue(ok)
        self.assertIs(returned, frame)

    def test_partial_startup_cleans_camera_and_servo(self):
        camera, servo = Mock(), Mock()
        with (patch.object(pi_tracker, 'FaceDetectorYuNet'),
              patch.object(pi_tracker, 'PiCameraStream', return_value=camera),
              patch.object(pi_tracker, 'PanTiltTracker', wraps=servos.PanTiltTracker) as tracker_type,
              patch.object(pi_tracker, 'OLEDDisplayController', side_effect=RuntimeError('OLED failed')),
              contextlib.redirect_stdout(io.StringIO())):
            tracker_type.return_value = servo
            with self.assertRaisesRegex(RuntimeError, 'OLED failed'):
                pi_tracker.main(['--headless'])
        camera.release.assert_called_once()
        servo.close.assert_called_once()
        servo.center.assert_not_called()


    def test_oled_rotation_cli_args(self):
        self.assertEqual(pi_tracker.parse_args([]).oled_rotate, 180)

        args = pi_tracker.parse_args(['--oled-rotate', '180'])
        self.assertEqual(args.oled_rotate, 180)
        self.assertIsNone(args.oled1_rotate)
        self.assertIsNone(args.oled2_rotate)

        args = pi_tracker.parse_args(['--oled1-rotate', '90', '--oled2-rotate', '270'])
        self.assertEqual(args.oled1_rotate, 90)
        self.assertEqual(args.oled2_rotate, 270)

    def test_oled_rotation_mapping_and_device_init(self):
        self.assertEqual(oled_face.parse_rotation(0), 0)
        self.assertEqual(oled_face.parse_rotation(90), 1)
        self.assertEqual(oled_face.parse_rotation(180), 2)
        self.assertEqual(oled_face.parse_rotation(270), 3)
        self.assertEqual(oled_face.parse_rotation(2), 2)

        created_rotations = []
        def mock_ssd1306(serial, rotate=0):
            created_rotations.append(rotate)
            return serial

        with (patch.object(oled_face, 'LUMA_AVAILABLE', True),
              patch.object(oled_face, 'i2c', side_effect=lambda port, address: Mock(), create=True),
              patch.object(oled_face, 'ssd1306', side_effect=mock_ssd1306, create=True),
              contextlib.redirect_stdout(io.StringIO())):
            ctrl = oled_face.OLEDDisplayController(port_1=1, addr_1=0x3C, port_2=3, addr_2=0x3C,
                                                   rotate_1=180, rotate_2=90)
            ctrl.stop()
        self.assertEqual(created_rotations, [2, 1])



if __name__ == '__main__':
    unittest.main()
