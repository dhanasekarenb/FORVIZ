"""Capture, inference, timing and thermal regressions without Pi hardware."""
import contextlib
import io
import subprocess
import unittest
from unittest.mock import Mock, patch

import numpy as np
import pi_tracker as app


class PerformanceTests(unittest.TestCase):
    def detector(self, limit=320):
        native = Mock()
        with (patch.object(app.os.path, 'exists', return_value=True),
              patch.object(app.cv2.FaceDetectorYN, 'create', return_value=native)):
            return app.FaceDetectorYuNet(max_input_size=limit), native

    def test_reduced_inference_maps_box_and_landmarks_back(self):
        detector, native = self.detector()
        native.detect.return_value = (None, np.array([
            [10, 20, 30, 40, 12, 22, 14, 24, 16, 26, 18, 28, 20, 30, .9]], dtype=np.float32))
        faces, _ = detector.detect(np.zeros((480, 640, 3), dtype=np.uint8))
        self.assertEqual(native.detect.call_args.args[0].shape, (240, 320, 3))
        self.assertEqual(faces[0]['box'], (20, 40, 60, 80))
        self.assertEqual(faces[0]['landmarks'], [(24, 44), (28, 48), (32, 52), (36, 56), (40, 60)])
        self.assertAlmostEqual(faces[0]['confidence'], .9, places=6)

    def test_small_frames_are_not_upscaled_and_size_is_cached(self):
        detector, native = self.detector()
        native.detect.return_value = (None, None)
        frame = np.zeros((120, 160, 3), dtype=np.uint8)
        self.assertEqual(detector.detect(frame)[0], [])
        detector.detect(frame)
        self.assertIs(native.detect.call_args.args[0], frame)
        native.setInputSize.assert_called_once_with((160, 120))
        detector.detect(np.zeros((640, 480, 3), dtype=np.uint8))
        self.assertEqual(native.detect.call_args.args[0].shape, (320, 240, 3))

    def test_picamera_receives_frame_duration_and_fresh_capture_setting(self):
        native = Mock()
        with (patch.object(app, 'PICAM2_AVAILABLE', True),
              patch.object(app, 'Picamera2', return_value=native, create=True),
              patch.object(app.time, 'sleep'), contextlib.redirect_stdout(io.StringIO())):
            camera = app.PiCameraStream(width=320, height=240, fps=10)
            camera.release()
        native.create_preview_configuration.assert_called_once_with(
            main={'size': (320, 240), 'format': 'RGB888'},
            controls={'FrameDurationLimits': (100000, 100000)}, queue=False)
        native.stop.assert_called_once()
        native.close.assert_called_once()

    def test_limiter_sleeps_without_catch_up_bursts(self):
        now = [0.0]
        def sleep(delay):
            now[0] += delay
        sleeper = Mock(side_effect=sleep)
        limiter = app.FrameRateLimiter(10, clock=lambda: now[0], sleep=sleeper)
        limiter.wait()
        sleeper.assert_not_called()
        now[0] += .03
        limiter.wait()
        self.assertAlmostEqual(sleeper.call_args.args[0], .07)
        now[0] += .5  # A long camera/inference stall must not trigger a burst.
        limiter.wait()
        self.assertEqual(sleeper.call_count, 1)
        limiter.wait()
        self.assertAlmostEqual(sleeper.call_args.args[0], .1)

    def test_filter_behavior_is_resolution_independent(self):
        states = [app.FaceTrackingState(), app.FaceTrackingState()]
        for width, height, state in [(640, 480, states[0]), (320, 240, states[1])]:
            for i, fraction in enumerate((.50, .502, .55, .62)):
                state.update([{'box': (width*fraction, height*.5, width*.1, height*.1)}],
                             width, height, i/15)
        self.assertAlmostEqual(states[0].gaze_x, states[1].gaze_x)
        self.assertAlmostEqual(states[0].gaze_y, states[1].gaze_y)

    def monitor(self):
        with patch.object(app.shutil, 'which', return_value=None):
            monitor = app.ThermalMonitor()
        monitor.path = Mock()
        monitor.command = 'vcgencmd'
        return monitor

    def test_thermal_flags_separate_current_and_historical_and_rate_limit(self):
        monitor = self.monitor()
        monitor.path.read_text.return_value = '78500'
        with patch.object(app.subprocess, 'run', return_value=Mock(stdout='throttled=0x50000')) as run:
            message = monitor.report(0)
            self.assertIn('CPU 78.5 C', message)
            self.assertIn('HOT:', message)
            self.assertIn('now: no flags', message)
            self.assertIn('earlier this boot: undervoltage, throttled', message)
            self.assertIsNone(monitor.report(9.9))
            run.assert_called_once()
            run.return_value.stdout = 'throttled=0x5'
            self.assertIn('now: undervoltage, throttled', monitor.report(10))

    def test_monitor_handles_missing_sensor_and_command_timeout(self):
        monitor = self.monitor()
        monitor.path.read_text.side_effect = OSError('no sensor')
        with patch.object(app.subprocess, 'run', side_effect=subprocess.TimeoutExpired('vcgencmd', .25)):
            self.assertIn('unavailable', monitor.report(0))
        monitor.command = None
        self.assertIsNone(monitor.report(10))

    def test_performance_cli_defaults_and_invalid_values(self):
        args = app.parse_args([])
        self.assertEqual((args.camera_width, args.camera_height, args.camera_fps,
                          args.detect_size, args.detect_fps, args.cv_threads),
                         (320, 240, 15, 320, 15, 1))
        for option, value in [('--camera-width','0'), ('--camera-height','-1'),
                              ('--detect-size','1'), ('--camera-fps','nan'),
                              ('--detect-fps','0'), ('--cv-threads','0')]:
            with self.subTest(option=option), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                app.parse_args([option, value])

    def test_main_uses_limits_and_actual_frame_coordinates(self):
        camera, detector, tracker = Mock(), Mock(), Mock()
        camera.read.side_effect = [(True, np.zeros((480,640,3), dtype=np.uint8)), (False, None)]
        detector.detect.return_value = ([{'box': (300,220,40,40)}], 4)
        tracker.track_face.return_value = (90,90)
        with (patch.object(app, 'PiCameraStream', return_value=camera) as camera_type,
              patch.object(app, 'FaceDetectorYuNet', return_value=detector) as detector_type,
              patch.object(app, 'PanTiltTracker', wraps=app.PanTiltTracker, return_value=tracker),
              patch.object(app, 'FrameRateLimiter') as limiter_type,
              patch.object(app, 'ThermalMonitor') as thermal_type,
              patch.object(app.cv2, 'setNumThreads') as threads,
              patch.object(app, 'draw_hud') as hud,
              contextlib.redirect_stdout(io.StringIO())):
            thermal_type.return_value.report.return_value = None
            app.main(['--headless','--no-oled','--no-servo','--camera-fps','10'])
        camera_type.assert_called_once_with(width=320, height=240, fps=10)
        detector_type.assert_called_once_with(app.YUNET_MODEL_PATH, max_input_size=320)
        threads.assert_called_once_with(1)
        limiter_type.assert_called_once_with(10)
        self.assertEqual(limiter_type.return_value.wait.call_count, 2)
        self.assertEqual(tracker.track_face.call_args.args[:4], (320,240,640,480))
        hud.assert_not_called()
        camera.release.assert_called_once()
        tracker.close.assert_called_once()


if __name__ == '__main__':
    unittest.main()
