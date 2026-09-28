"""FORVIZ - Autonomous Face Tracking Robot with Groq Voice Assistant.

Features:
  - Real-time YuNet AI face detection & pan/tilt servo tracking (15 FPS).
  - Dual/Single SSD1306 OLED animated eyes with gaze tracking and expressions.
  - Voice Assistant powered by Groq API (Whisper STT + Llama 3.3 LLM + TTS).
  - Defaults to --mirror-eye mode for standard same-bus dual OLED setups.
  - Works with standard headsets/headphones plugged into Raspberry Pi.

Run:
  python3 forviz.py
"""
import argparse
import audioop
import base64
import io
import json
import math
import os
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import wave

import cv2
from servos import PanTiltTracker
from oled_face import DEFAULT_OLED_ROTATION, OLEDDisplayController, RobotEyesRenderer

YUNET_MODEL_PATH = str(Path(__file__).resolve().with_name('face_detection_yunet_2023mar.onnx'))

try:
    from picamera2 import Picamera2
    PICAM2_AVAILABLE = True
except ImportError:
    PICAM2_AVAILABLE = False

# Audio libraries (optional imports with graceful fallbacks)
try:
    import pyaudio
    PYAUDIO_AVAILABLE = True
except ImportError:
    PYAUDIO_AVAILABLE = False

try:
    import sounddevice as sd
    import numpy as np
    SOUNDDEVICE_AVAILABLE = True
except ImportError:
    SOUNDDEVICE_AVAILABLE = False

try:
    import pygame
    PYGAME_AVAILABLE = True
except ImportError:
    PYGAME_AVAILABLE = False

try:
    from gtts import gTTS
    GTTS_AVAILABLE = True
except ImportError:
    GTTS_AVAILABLE = False

try:
    from groq import Groq
    GROQ_SDK_AVAILABLE = True
except ImportError:
    GROQ_SDK_AVAILABLE = False


# ---------------------------------------------------------------------------
# 1. CAMERA STREAM (Picamera2 / OpenCV fallback)
# ---------------------------------------------------------------------------
class PiCameraStream:
    """Handles camera capture using Picamera2 or OpenCV fallback."""
    def __init__(self, width=320, height=240, fps=15, hflip=True, vflip=False):
        self.width = width
        self.height = height
        self.fps = fps
        self.hflip = hflip
        self.vflip = vflip
        self.use_picam2 = PICAM2_AVAILABLE
        self.picam2 = None
        self.cap = None

        if self.use_picam2:
            try:
                print("[CAM] Initializing Raspberry Pi Camera via Picamera2...")
                self.picam2 = Picamera2()
                frame_us = round(1_000_000 / fps)
                config = self.picam2.create_preview_configuration(
                    main={"size": (width, height), "format": "RGB888"},
                    controls={"FrameDurationLimits": (frame_us, frame_us)},
                    queue=False,
                )
                self.picam2.configure(config)
                self.picam2.start()
                time.sleep(1.0)
                print("[CAM] Picamera2 started successfully.")
            except Exception as e:
                print(f"[CAM WARNING] Picamera2 failed ({e}). Falling back to cv2.VideoCapture...")
                if self.picam2 is not None:
                    self.picam2.close()
                    self.picam2 = None
                self.use_picam2 = False

        if not self.use_picam2:
            print("[CAM] Opening camera via OpenCV VideoCapture(0)...")
            self.cap = cv2.VideoCapture(0)
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
            self.cap.set(cv2.CAP_PROP_FPS, fps)
            self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            if not self.cap.isOpened():
                self.cap.release()
                raise RuntimeError("Failed to open camera! Check CSI ribbon cable or run 'rpicam-hello'.")

    def read(self):
        if self.use_picam2:
            frame = self.picam2.capture_array()
            ret = True
        else:
            ret, frame = self.cap.read()
        if ret and frame is not None:
            hflip = getattr(self, 'hflip', False)
            vflip = getattr(self, 'vflip', False)
            if hflip and vflip:
                frame = cv2.flip(frame, -1)
            elif hflip:
                frame = cv2.flip(frame, 1)
            elif vflip:
                frame = cv2.flip(frame, 0)
        return ret, frame

    def release(self):
        if self.use_picam2 and self.picam2 is not None:
            try:
                self.picam2.stop()
            finally:
                self.picam2.close()
        elif self.cap is not None:
            self.cap.release()


# ---------------------------------------------------------------------------
# 2. YUNET FACE DETECTOR (ONNX CPU INFERENCE)
# ---------------------------------------------------------------------------
class FaceDetectorYuNet:
    """Ultra-lightweight (232KB) Face Detector for Raspberry Pi 4 CPU."""
    def __init__(self, model_path=YUNET_MODEL_PATH, conf_threshold=0.6, nms_threshold=0.3,
                 max_input_size=320):
        if max_input_size < 64:
            raise ValueError('Detection input size must be at least 64 pixels')
        self.max_input_size = max_input_size
        self._input_size = None
        if not os.path.exists(model_path):
            raise FileNotFoundError(f"Model file '{model_path}' not found! Run setup_pi.sh to download it.")

        self.detector = cv2.FaceDetectorYN.create(
            model=str(model_path),
            config="",
            input_size=(320, 320),
            score_threshold=conf_threshold,
            nms_threshold=nms_threshold,
            top_k=2000,
            backend_id=cv2.dnn.DNN_BACKEND_OPENCV,
            target_id=cv2.dnn.DNN_TARGET_CPU
        )

    def detect(self, frame):
        h, w = frame.shape[:2]
        t0 = time.perf_counter()
        scale = min(1.0, self.max_input_size / max(w, h))
        dw, dh = max(1, round(w * scale)), max(1, round(h * scale))
        small = frame if (dw, dh) == (w, h) else cv2.resize(frame, (dw, dh), interpolation=cv2.INTER_AREA)
        if self._input_size != (dw, dh):
            self.detector.setInputSize((dw, dh))
            self._input_size = (dw, dh)
        _, faces = self.detector.detect(small)
        latency_ms = (time.perf_counter() - t0) * 1000

        results = []
        if faces is not None:
            for face in faces:
                sx, sy = w / dw, h / dh
                x, y, bw, bh = [int(round(float(v) * s)) for v, s in zip(face[0:4], (sx, sy, sx, sy))]
                conf = float(face[14])
                landmarks = [(int(round(float(face[i]) * sx)), int(round(float(face[i+1]) * sy)))
                             for i in range(4, 14, 2)]
                results.append({
                    "box": (x, y, bw, bh),
                    "confidence": conf,
                    "landmarks": landmarks
                })
        return results, latency_ms


# ---------------------------------------------------------------------------
# 3. RATE LIMITER & THERMAL MONITOR
# ---------------------------------------------------------------------------
class FrameRateLimiter:
    """Sleep between loop starts; never burst to catch up after slow inference."""
    def __init__(self, fps, clock=time.monotonic, sleep=time.sleep):
        if not math.isfinite(fps) or fps <= 0:
            raise ValueError('Frame rate must be finite and positive')
        self.period, self.clock, self.sleep = 1.0 / fps, clock, sleep
        self.next_start = clock()

    def wait(self):
        delay = self.next_start - self.clock()
        if delay > 0:
            self.sleep(delay)
        self.next_start = self.clock() + self.period


class ThermalMonitor:
    """Read Pi temperature and firmware flags at most once every ten seconds."""
    def __init__(self):
        self.path = Path('/sys/class/thermal/thermal_zone0/temp')
        self.command = shutil.which('vcgencmd') if sys.platform.startswith('linux') else None
        self.next_read = 0.0

    def report(self, now):
        if now < self.next_read:
            return None
        self.next_read = now + 10.0
        info = []
        try:
            temp = float(self.path.read_text().strip()) / 1000.0
            if math.isfinite(temp):
                info.append(f'CPU {temp:.1f} C')
                if temp >= 75:
                    info.append('HOT: check airflow/cooling; lower --camera-fps and --detect-fps')
        except (OSError, ValueError):
            pass
        if self.command:
            try:
                result = subprocess.run([self.command, 'get_throttled'], capture_output=True,
                                        text=True, timeout=0.25, check=True)
                flags = int(result.stdout.strip().split('=', 1)[1], 16)
                labels = ('undervoltage', 'frequency capped', 'throttled', 'soft temperature limit')
                active = [label for bit, label in enumerate(labels) if flags & (1 << bit)]
                past = [label for bit, label in enumerate(labels) if flags & (1 << (bit + 16))]
                info.append('now: ' + (', '.join(active) or 'no flags'))
                if past:
                    info.append('earlier this boot: ' + ', '.join(past))
            except (OSError, subprocess.SubprocessError, ValueError, IndexError):
                info.append('firmware flags unavailable')
        return '[THERMAL] ' + ' | '.join(info) if info else None


# ---------------------------------------------------------------------------
# 4. TRACKING STATE MACHINE
# ---------------------------------------------------------------------------
class FaceTrackingState:
    """Pure tracking state with jitter filtering and deadband locking."""
    def __init__(self, face_loss_sec=1.5, deadband=0.08):
        if not math.isfinite(face_loss_sec) or face_loss_sec < 0:
            raise ValueError('Face-loss hold must be finite and nonnegative')
        if not math.isfinite(deadband) or not 0 <= deadband < 1:
            raise ValueError('Deadband must be between 0 and 1')
        self.face_loss_sec, self.deadband = face_loss_sec, deadband
        self.last_seen = self.last_update = self.lock_start_time = None
        self.smooth_cx = self.smooth_cy = None
        self.state_name, self.mood = 'SCANNING', 'NEUTRAL'
        self.gaze_x = self.gaze_y = 0.0
        self.just_settled = False
        self._settled = False

    def update(self, faces, width, height, now, invert_gaze_x=False, invert_gaze_y=False):
        dt = 1.0 / 30.0 if self.last_update is None else max(0.0, now - self.last_update)
        self.last_update = now
        self.mood = 'NEUTRAL'
        self.just_settled = False
        if not faces:
            self.lock_start_time = None
            self._settled = False
            if self.last_seen is not None and now - self.last_seen < self.face_loss_sec:
                self.state_name = 'HOLDING'
            else:
                self.state_name = 'SCANNING'
                self.smooth_cx = self.smooth_cy = None
                self.gaze_x, self.gaze_y = math.sin(now * 2.5) * 0.7, 0.0
            return None

        primary_face = max(faces, key=lambda face: face['box'][2] * face['box'][3])
        x, y, box_w, box_h = primary_face['box']
        raw_x, raw_y = x + box_w / 2.0, y + box_h / 2.0
        if self.smooth_cx is None or self.last_seen is None:
            self.smooth_cx, self.smooth_cy = raw_x, raw_y
        else:
            dist = math.hypot((raw_x - self.smooth_cx) * 640 / width,
                              (raw_y - self.smooth_cy) * 480 / height)
            if dist > 3.0:
                factor = min(1.0, dist / 80.0)
                tc = 0.09 * (1.0 - 0.55 * factor)
                alpha = 1.0 - math.exp(-min(dt, 0.1) / tc)
                self.smooth_cx += alpha * (raw_x - self.smooth_cx)
                self.smooth_cy += alpha * (raw_y - self.smooth_cy)
        self.last_seen = now
        gx = (self.smooth_cx - width / 2.0) / (width / 2.0)
        gy = (self.smooth_cy - height / 2.0) / (height / 2.0)
        self.gaze_x = -gx if invert_gaze_x else gx
        self.gaze_y = -gy if invert_gaze_y else gy
        if abs(self.gaze_x) <= self.deadband and abs(self.gaze_y) <= self.deadband:
            self.state_name = 'LOCKED'
            if self.lock_start_time is None:
                self.lock_start_time = now
            if now - self.lock_start_time >= 1.0:
                self.mood = 'HAPPY'
                if not self._settled:
                    self.just_settled = True
                self._settled = True
        else:
            self.state_name = 'TRACKING'
            self.lock_start_time = None
            self._settled = False
        return primary_face


# ---------------------------------------------------------------------------
# 5. VOICE ASSISTANT ENGINE (GROQ API + WHISPER + LLM + TTS)
# ---------------------------------------------------------------------------
class GroqVoiceAssistant:
    """Asynchronous Voice Assistant using Groq Cloud API for STT and LLM reasoning.

    Runs in a background thread so face tracking, pan/tilt servos, and OLED
    animations run at full 15 FPS without any jitter or stalling.
    """
    SYSTEM_PROMPT = (
        "You are FORVIZ, a charming, intelligent, friendly companion desktop robot "
        "with an expressive pan-tilt head, camera vision, and animated OLED eyes. "
        "You are speaking to your creator through headphones. "
        "CRITICAL RULES: Keep answers very brief, natural, witty, and conversational (1 to 2 sentences max), "
        "as your output is converted directly to voice audio. Never use markdown, bullet points, asterisks, "
        "or URLs. If the user mentions emotions like smile, naruto, sharingan, or nightmare, enthusiastically acknowledge it."
    )

    def __init__(self, api_key=None, groq_model="llama-3.3-70b-versatile",
                 whisper_model="whisper-large-v3-turbo", voice_callback=None):
        self.api_key = api_key or os.environ.get("GROQ_API_KEY")
        if not self.api_key:
            self.api_key = self._find_key_in_dotenv()

        self.groq_model = groq_model
        self.whisper_model = whisper_model
        self.voice_callback = voice_callback  # Callback to set OLED expression & robot state
        self.running = False
        self.thread = None
        self._stop_event = threading.Event()
        self.conversation_history = [
            {"role": "system", "content": self.SYSTEM_PROMPT}
        ]
        self.client = None
        if self.api_key and GROQ_SDK_AVAILABLE:
            try:
                self.client = Groq(api_key=self.api_key)
            except Exception as e:
                print(f"[VOICE WARNING] Groq SDK init failed: {e}")

        # Pygame mixer initialization for audio playback
        self.pygame_audio = False
        if PYGAME_AVAILABLE:
            try:
                pygame.mixer.init(frequency=24000)
                self.pygame_audio = True
            except Exception:
                pass

        if not self.api_key:
            print("[VOICE NOTE] GROQ_API_KEY not set. Set GROQ_API_KEY in environment or .env file to enable voice.")

    @staticmethod
    def _find_key_in_dotenv():
        """Search current directory and user home for .env file with GROQ_API_KEY."""
        search_paths = [Path.cwd() / ".env", Path.home() / ".env"]
        for path in search_paths:
            if path.is_file():
                try:
                    for line in path.read_text(encoding="utf-8").splitlines():
                        line = line.strip()
                        if line.startswith("GROQ_API_KEY="):
                            val = line.split("=", 1)[1].strip().strip('"\'')
                            if val:
                                return val
                except Exception:
                    pass
        return None

    def start(self):
        if self.thread is not None and self.thread.is_alive():
            return
        self._stop_event.clear()
        self.running = True
        self.thread = threading.Thread(target=self._voice_loop, daemon=True, name="forviz-voice")
        self.thread.start()
        print("[VOICE] Background voice assistant thread started.")

    def stop(self):
        self._stop_event.set()
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=1.5)
        self.running = False
        print("[VOICE] Voice assistant stopped.")

    def _voice_loop(self):
        """Continuously listen from headphone microphone, query Groq API, and speak reply."""
        while not self._stop_event.is_set():
            if not self.api_key:
                # Idle wait if no key is supplied
                self._stop_event.wait(5.0)
                continue

            try:
                # 1. Listen for voice activity
                audio_wav_data = self._record_phrase(silence_duration=1.2, max_record_sec=12.0)
                if not audio_wav_data or self._stop_event.is_set():
                    time.sleep(0.1)
                    continue

                if self.voice_callback:
                    self.voice_callback("THINKING", "Processing speech...")

                # 2. Transcribe using Groq Whisper API
                transcription = self._transcribe_audio(audio_wav_data)
                if not transcription or len(transcription.strip()) < 2:
                    if self.voice_callback:
                        self.voice_callback("IDLE", None)
                    continue

                print(f"\n[USER]: {transcription}")

                # Check for direct offline Easter eggs/voice commands
                text_lower = transcription.lower()
                custom_mood = None
                if any(k in text_lower for k in ("sharingan", "uchiha")):
                    custom_mood = "UCHIHA"
                elif any(k in text_lower for k in ("sage mode", "naruto")):
                    custom_mood = "NARUTO"
                elif any(k in text_lower for k in ("nightmare", "monster")):
                    custom_mood = "NIGHTMARE"
                elif any(k in text_lower for k in ("smile", "happy")):
                    custom_mood = "HAPPY"

                if self.voice_callback and custom_mood:
                    self.voice_callback("MOOD_OVERRIDE", custom_mood)

                # 3. Query Groq LLM (Llama 3.3)
                reply = self._query_groq_llm(transcription)
                if not reply or self._stop_event.is_set():
                    if self.voice_callback:
                        self.voice_callback("IDLE", None)
                    continue

                print(f"[FORVIZ]: {reply}\n")

                # 4. Speak response through headphones
                if self.voice_callback:
                    self.voice_callback("SPEAKING", reply)

                self._speak_text(reply)

                if self.voice_callback:
                    self.voice_callback("IDLE", None)

            except Exception as e:
                print(f"[VOICE ERROR] Voice loop exception: {e}")
                time.sleep(1.0)

    def _record_phrase(self, silence_duration=1.2, max_record_sec=12.0):
        """Record audio until silence is detected using PyAudio, sounddevice, or arecord."""
        sample_rate = 16000
        channels = 1
        chunk_size = 1024
        energy_threshold = 700  # Voice activity threshold

        # Method 1: PyAudio
        if PYAUDIO_AVAILABLE:
            try:
                p = pyaudio.PyAudio()
                # Find default input device
                stream = p.open(format=pyaudio.paInt16, channels=channels,
                                rate=sample_rate, input=True,
                                frames_per_buffer=chunk_size)
                frames = []
                has_voice = False
                silence_chunks = 0
                max_silence_chunks = int(silence_duration * sample_rate / chunk_size)
                max_chunks = int(max_record_sec * sample_rate / chunk_size)

                for _ in range(max_chunks):
                    if self._stop_event.is_set():
                        break
                    data = stream.read(chunk_size, exception_on_overflow=False)
                    # Calculate volume (RMS)
                    rms = audioop.rms(data, 2)
                    if rms > energy_threshold:
                        if not has_voice:
                            has_voice = True
                            if self.voice_callback:
                                self.voice_callback("LISTENING", "Listening...")
                        frames.append(data)
                        silence_chunks = 0
                    elif has_voice:
                        frames.append(data)
                        silence_chunks += 1
                        if silence_chunks >= max_silence_chunks:
                            break
                    else:
                        time.sleep(0.01)

                stream.stop_stream()
                stream.close()
                p.terminate()

                if has_voice and frames:
                    wav_io = io.BytesIO()
                    with wave.open(wav_io, 'wb') as wf:
                        wf.setnchannels(channels)
                        wf.setsampwidth(2)
                        wf.setframerate(sample_rate)
                        wf.writeframes(b''.join(frames))
                    return wav_io.getvalue()
                return None
            except Exception as e:
                pass

        # Method 2: ALSA arecord on Raspberry Pi Linux
        if sys.platform.startswith('linux') and shutil.which('arecord'):
            try:
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                    tmp_name = tmp.name
                cmd = ["arecord", "-D", "default", "-f", "S16_LE", "-r", str(sample_rate),
                       "-c", "1", "-d", "4", "-q", tmp_name]
                subprocess.run(cmd, timeout=5, check=True)
                wav_data = Path(tmp_name).read_bytes()
                try:
                    os.remove(tmp_name)
                except OSError:
                    pass
                return wav_data
            except Exception:
                pass

        # Fallback if no audio hardware detected: sleep and return None
        self._stop_event.wait(1.0)
        return None

    def _transcribe_audio(self, wav_bytes):
        """Send audio to Groq Whisper API."""
        if not self.api_key:
            return None

        # SDK method
        if self.client is not None:
            try:
                transcription = self.client.audio.transcriptions.create(
                    file=("speech.wav", wav_bytes),
                    model=self.whisper_model,
                    response_format="json",
                    language="en",
                    temperature=0.0
                )
                return transcription.text
            except Exception as e:
                print(f"[VOICE] Groq SDK Whisper error: {e}")

        # Direct HTTP POST fallback using standard library
        try:
            boundary = f"----WebKitFormBoundary{os.urandom(16).hex()}"
            body = bytearray()
            # Model field
            body.extend(f"--{boundary}\r\n".encode("utf-8"))
            body.extend(b'Content-Disposition: form-data; name="model"\r\n\r\n')
            body.extend(f"{self.whisper_model}\r\n".encode("utf-8"))
            # File field
            body.extend(f"--{boundary}\r\n".encode("utf-8"))
            body.extend(b'Content-Disposition: form-data; name="file"; filename="audio.wav"\r\n')
            body.extend(b'Content-Type: audio/wav\r\n\r\n')
            body.extend(wav_bytes)
            body.extend(b"\r\n")
            body.extend(f"--{boundary}--\r\n".encode("utf-8"))

            req = urllib.request.Request(
                "https://api.groq.com/openai/v1/audio/transcriptions",
                data=bytes(body),
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": f"multipart/form-data; boundary={boundary}"
                }
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                return result.get("text", "")
        except Exception as e:
            print(f"[VOICE] Direct Groq Whisper API error: {e}")
            return None

    def _query_groq_llm(self, user_text):
        """Send user message to Groq Chat Completion (Llama 3.3)."""
        self.conversation_history.append({"role": "user", "content": user_text})
        # Keep last 8 messages
        if len(self.conversation_history) > 9:
            self.conversation_history = [self.conversation_history[0]] + self.conversation_history[-8:]

        # SDK method
        if self.client is not None:
            try:
                response = self.client.chat.completions.create(
                    model=self.groq_model,
                    messages=self.conversation_history,
                    temperature=0.7,
                    max_tokens=120
                )
                reply = response.choices[0].message.content.strip()
                self.conversation_history.append({"role": "assistant", "content": reply})
                return reply
            except Exception as e:
                print(f"[VOICE] Groq SDK LLM error: {e}")

        # Direct HTTP POST fallback
        try:
            payload = json.dumps({
                "model": self.groq_model,
                "messages": self.conversation_history,
                "temperature": 0.7,
                "max_tokens": 120
            }).encode("utf-8")

            req = urllib.request.Request(
                "https://api.groq.com/openai/v1/chat/completions",
                data=payload,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                }
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                reply = data["choices"][0]["message"]["content"].strip()
                self.conversation_history.append({"role": "assistant", "content": reply})
                return reply
        except Exception as e:
            print(f"[VOICE] Direct Groq LLM API error: {e}")
            return "I heard you, but my connection to Groq briefly stuttered."

    def _speak_text(self, text):
        """Render text to audio and play back through connected headphones."""
        if not text:
            return

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
            tmp_audio_path = tmp.name

        tts_success = False

        # 1. Try edge-tts if CLI or python is installed
        if shutil.which("edge-tts"):
            try:
                cmd = ["edge-tts", "--voice", "en-US-ChristopherNeural", "--text", text, "--write-media", tmp_audio_path]
                res = subprocess.run(cmd, capture_output=True, timeout=8)
                if res.returncode == 0 and os.path.exists(tmp_audio_path) and os.path.getsize(tmp_audio_path) > 100:
                    tts_success = True
            except Exception:
                pass

        # 2. Try gTTS
        if not tts_success and GTTS_AVAILABLE:
            try:
                tts = gTTS(text=text, lang='en', slow=False)
                tts.save(tmp_audio_path)
                tts_success = True
            except Exception:
                pass

        # 3. Play generated audio through headphones
        if tts_success:
            self._play_audio_file(tmp_audio_path)
        else:
            # Fallback to local espeak if present on Pi
            if shutil.which("espeak"):
                try:
                    subprocess.run(["espeak", "-v", "en-us", "-s", "165", text], timeout=6)
                except Exception:
                    pass

        try:
            if os.path.exists(tmp_audio_path):
                os.remove(tmp_audio_path)
        except OSError:
            pass

    def _play_audio_file(self, file_path):
        """Play sound file through the default sound device (headphones)."""
        # Try pygame mixer
        if self.pygame_audio:
            try:
                pygame.mixer.music.load(file_path)
                pygame.mixer.music.play()
                while pygame.mixer.music.get_busy() and not self._stop_event.is_set():
                    time.sleep(0.05)
                if hasattr(pygame.mixer.music, 'unload'):
                    pygame.mixer.music.unload()
                return
            except Exception:
                pass
                pass

        # Try system players on Linux (mpv, mpg123, ffplay, aplay)
        for player in ["mpg123", "mpv", "ffplay"]:
            if shutil.which(player):
                try:
                    extra = ["-nodisp", "-autoexit"] if player == "ffplay" else (["--no-video"] if player == "mpv" else ["-q"])
                    subprocess.run([player] + extra + [file_path], timeout=15)
                    return
                except Exception:
                    pass

    def ask_text(self, text):
        """Query Groq LLM from text and speak answer via headphones."""
        if not text or not text.strip():
            return None
        text = text.strip()
        print(f"\n[USER (Text)]: {text}")
        if self.voice_callback:
            self.voice_callback("THINKING", "Processing text...")

        text_lower = text.lower()
        if any(k in text_lower for k in ("sharingan", "uchiha")):
            if self.voice_callback:
                self.voice_callback("MOOD_OVERRIDE", "UCHIHA")
        elif any(k in text_lower for k in ("sage mode", "naruto")):
            if self.voice_callback:
                self.voice_callback("MOOD_OVERRIDE", "NARUTO")
        elif any(k in text_lower for k in ("nightmare", "monster")):
            if self.voice_callback:
                self.voice_callback("MOOD_OVERRIDE", "NIGHTMARE")
        elif any(k in text_lower for k in ("smile", "happy")):
            if self.voice_callback:
                self.voice_callback("MOOD_OVERRIDE", "HAPPY")

        reply = self._query_groq_llm(text)
        print(f"[FORVIZ]: {reply}\n")
        if self.voice_callback:
            self.voice_callback("SPEAKING", reply)
        self._speak_text(reply)
        if self.voice_callback:
            self.voice_callback("IDLE", None)
        return reply


# ---------------------------------------------------------------------------
# 6. HEADS-UP DISPLAY (HUD)
# ---------------------------------------------------------------------------
def draw_hud(frame, primary_face, pan_deg, tilt_deg, state_name, fps, latency_ms, voice_status=None):
    h, w = frame.shape[:2]
    cx, cy = w // 2, h // 2

    cv2.drawMarker(frame, (cx, cy), (80, 80, 80), cv2.MARKER_CROSS, 20, 1)

    if primary_face:
        x, y, bw, bh = primary_face["box"]
        tcx, tcy = x + bw // 2, y + bh // 2
        color = (0, 255, 0) if state_name == "LOCKED" else (127, 0, 255)
        cv2.rectangle(frame, (x, y), (x + bw, y + bh), color, 2)
        cv2.circle(frame, (tcx, tcy), 4, (0, 0, 255), -1)
        cv2.arrowedLine(frame, (cx, cy), (tcx, tcy), (0, 255, 255), 2, tipLength=0.2)

    cv2.rectangle(frame, (0, 0), (w, 40), (20, 20, 20), -1)
    status_top = f"FORVIZ | FPS: {fps:4.1f} | Latency: {latency_ms:4.1f}ms"
    cv2.putText(frame, status_top, (10, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.52, (0, 255, 0), 1)

    cv2.rectangle(frame, (0, h - 45), (w, h), (20, 20, 20), -1)
    voice_tag = f" | {voice_status}" if voice_status else ""
    status_str = f"State: {state_name:8s} | Pan: {pan_deg:5.1f} | Tilt: {tilt_deg:5.1f}{voice_tag}"
    cv2.putText(frame, status_str, (10, h - 16), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (0, 220, 255), 1)

    return frame


def default_headless():
    gui_lines = [line for line in cv2.getBuildInformation().splitlines() if line.strip().startswith('GUI:')]
    no_gui = any('NONE' in line for line in gui_lines)
    return no_gui or (sys.platform.startswith('linux') and not
                      (os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY')))


# ---------------------------------------------------------------------------
# 7. COMMAND LINE ARGUMENTS (Defaults to --mirror-eye)
# ---------------------------------------------------------------------------
def parse_args(argv=None):
    parser = argparse.ArgumentParser(description='FORVIZ - Face Tracking Robot with Groq Voice Assistant')
    parser.add_argument('--no-servo', action='store_true', help='Simulate servo angles without GPIO output')
    parser.add_argument('--no-oled', action='store_true', help='Disable physical OLED hardware')

    # OLED Configuration: Default is now MIRROR_EYE (big centered eye on both screens)
    oled = parser.add_mutually_exclusive_group()
    oled.add_argument('--mirror-eye', '--single-eye', dest='mirror_eye', action='store_true', default=True,
                      help='Render ONE big centered eye (DEFAULT: ideal for dual OLEDs on shared I2C bus)')
    oled.add_argument('--dual-oled', dest='dual_oled', action='store_true', default=False,
                      help='Request independent left/right screens (Bus 1 & Bus 3)')
    oled.add_argument('--single-oled', dest='single_oled', action='store_true', default=False,
                      help='Use one OLED, rendering both eyes side-by-side')

    parser.add_argument('--oled-rotate', type=int, default=DEFAULT_OLED_ROTATION,
                        choices=[0, 90, 180, 270],
                        help='Rotate all OLED displays (default: 180 for the installed panels)')
    parser.add_argument('--oled1-rotate', type=int, default=None, choices=[0, 90, 180, 270])
    parser.add_argument('--oled2-rotate', type=int, default=None, choices=[0, 90, 180, 270])

    expressions = parser.add_mutually_exclusive_group()
    expressions.add_argument('--nightmare', action='store_true', help='Keep OLEDs in nightmare eye expression')
    expressions.add_argument('--naruto', action='store_true', help='Keep OLEDs in Naruto Sage-style expression')
    expressions.add_argument('--uchiha', action='store_true', help='Keep OLEDs in Uchiha three-tomoe expression')

    display = parser.add_mutually_exclusive_group()
    display.add_argument('--headless', action='store_true', help='Disable OpenCV preview')
    display.add_argument('--preview', action='store_true', help='Request OpenCV preview on a desktop')

    # Voice Assistant Arguments
    parser.add_argument('--no-voice', action='store_true', help='Disable Groq Voice Assistant')
    parser.add_argument('--voice-text', action='store_true', help='Enable interactive terminal text chat alongside voice')
    parser.add_argument('--groq-key', type=str, default=None, help='Groq API key (or set GROQ_API_KEY env/dotenv)')
    parser.add_argument('--groq-model', type=str, default="llama-3.3-70b-versatile",
                        help='Groq LLM model (default: llama-3.3-70b-versatile)')
    parser.add_argument('--whisper-model', type=str, default="whisper-large-v3-turbo",
                        help='Groq Whisper model (default: whisper-large-v3-turbo)')

    # Vision & Camera Parameters
    parser.add_argument('--model', default=YUNET_MODEL_PATH, help='YuNet ONNX model path')
    parser.add_argument('--camera-width', type=int, default=320, help='Requested camera width (default: 320)')
    parser.add_argument('--camera-height', type=int, default=240, help='Requested camera height (default: 240)')
    parser.add_argument('--camera-fps', type=float, default=15, help='Requested camera frame rate (default: 15)')
    parser.add_argument('--detect-fps', type=float, default=15, help='Maximum detection/servo loop rate (default: 15)')
    parser.add_argument('--detect-size', type=int, default=320, help='Maximum inference image dimension (default: 320)')
    parser.add_argument('--cv-threads', type=int, default=1, help='OpenCV worker threads (default: 1)')
    parser.add_argument('--no-hflip', dest='hflip', action='store_false', default=True)
    parser.add_argument('--hflip', dest='hflip', action='store_true', default=True)
    parser.add_argument('--vflip', action='store_true', default=False)

    # Servo Pins & Range Limits
    parser.add_argument('--pan-pin', type=int, default=12)
    parser.add_argument('--tilt-pin', type=int, default=19)
    parser.add_argument('--pan-min', type=float, default=10)
    parser.add_argument('--pan-max', type=float, default=170)
    parser.add_argument('--tilt-min', type=float, default=45)
    parser.add_argument('--tilt-max', type=float, default=155)
    parser.add_argument('--invert-tilt', action='store_true', help='Invert vertical tilt servo')
    parser.add_argument('--invert-pan', action='store_true', help='Invert horizontal pan servo')
    parser.add_argument('--invert-gaze-y', action='store_true', help='Invert eye pupil vertical gaze')
    parser.add_argument('--invert-gaze-x', action='store_true', help='Invert eye pupil horizontal gaze')
    parser.add_argument('--invert-y', action='store_true', help='Invert both vertical tilt servo and eye gaze')
    parser.add_argument('--pan-center', type=float, default=90)
    parser.add_argument('--tilt-center', type=float, default=90)
    parser.add_argument('--servo-speed', type=float, default=144, help='Maximum servo speed (deg/s)')
    parser.add_argument('--gain-pan', type=float, default=144.0, help='Pan tracking sensitivity')
    parser.add_argument('--gain-tilt', type=float, default=75.0, help='Tilt tracking sensitivity')
    parser.add_argument('--reverse-pan', action='store_true', help='Reverse pan servo direction')
    parser.add_argument('--reverse-tilt', action='store_true', help='Reverse tilt servo direction')
    parser.add_argument('--scan-speed', type=float, default=18, help='Pan scan speed (deg/s)')
    parser.add_argument('--face-loss-sec', type=float, default=1.5, help='Hold position before resuming scan')
    parser.add_argument('--idle-detach-after', type=float, default=None,
                        help='Idle PWM timeout in seconds; releases head holding torque')

    args = parser.parse_args(argv)

    # Resolve mutual exclusivity override for mirror-eye
    if args.dual_oled or args.single_oled:
        args.mirror_eye = False

    return args


# ---------------------------------------------------------------------------
# 8. MAIN EXECUTION
# ---------------------------------------------------------------------------
def main(argv=None):
    args = parse_args(argv)
    headless = args.headless or (not args.preview and default_headless())

    print("=" * 65)
    print("      FORVIZ - Face Tracking Robot & Groq Voice Assistant")
    print("=" * 65)
    print(f"[DISPLAY] Default mode active: Mirror-Eye (Dual screens in sync)")
    print(f"[SERVOS] Limits: pan {args.pan_min:g}..{args.pan_max:g}, tilt {args.tilt_min:g}..{args.tilt_max:g} deg")
    if headless:
        print("[INFO] Headless telemetry active. Use Ctrl+C to stop.")

    camera = tracker = face_display = voice_bot = None
    voice_state = {"status": None, "mood_override": None}

    def on_voice_event(event_type, data):
        """Callback from background voice thread to sync robot expressions."""
        if event_type == "LISTENING":
            voice_state["status"] = "Listening..."
        elif event_type == "THINKING":
            voice_state["status"] = "Thinking..."
        elif event_type == "SPEAKING":
            voice_state["status"] = "Speaking..."
            voice_state["mood_override"] = "HAPPY"
        elif event_type == "MOOD_OVERRIDE":
            voice_state["mood_override"] = data
        elif event_type == "IDLE":
            voice_state["status"] = None
            voice_state["mood_override"] = None

    try:
        cv2.setNumThreads(args.cv_threads)
        detector = FaceDetectorYuNet(args.model, max_input_size=args.detect_size)
        camera = PiCameraStream(width=args.camera_width, height=args.camera_height,
                                fps=args.camera_fps, hflip=args.hflip, vflip=args.vflip)

        invert_tilt = False if args.reverse_tilt else True
        invert_pan = False if args.reverse_pan else True
        invert_gaze_y = args.invert_gaze_y or args.invert_y
        invert_gaze_x = args.invert_gaze_x

        tracker = PanTiltTracker(
            pan_pin=args.pan_pin, tilt_pin=args.tilt_pin,
            pan_range=(args.pan_min, args.pan_max), tilt_range=(args.tilt_min, args.tilt_max),
            pan_center=args.pan_center, tilt_center=args.tilt_center,
            max_speed_deg_per_sec=args.servo_speed, scan_speed_deg_per_sec=args.scan_speed,
            idle_timeout_sec=args.idle_detach_after, hardware=not args.no_servo,
            invert_pan=invert_pan, invert_tilt=invert_tilt
        )

        if not args.no_oled:
            mode = False if args.single_oled else (True if args.dual_oled else None)
            face_display = OLEDDisplayController(
                dual_screen=mode,
                rotate=args.oled_rotate,
                rotate_1=args.oled1_rotate,
                rotate_2=args.oled2_rotate,
                single_eye=args.mirror_eye,
            )
            face_display.start()

        # Start Groq Voice Assistant if enabled
        if not args.no_voice:
            voice_bot = GroqVoiceAssistant(
                api_key=args.groq_key,
                groq_model=args.groq_model,
                whisper_model=args.whisper_model,
                voice_callback=on_voice_event
            )
            voice_bot.start()
            if args.voice_text:
                def terminal_input_thread():
                    print("[VOICE-TEXT] Terminal chat enabled. Type your question and press Enter to talk with FORVIZ:")
                    while True:
                        try:
                            line = sys.stdin.readline()
                            if not line:
                                break
                            if line.strip():
                                voice_bot.ask_text(line.strip())
                        except Exception:
                            break
                threading.Thread(target=terminal_input_thread, daemon=True, name="forviz-text-input").start()

        state = FaceTrackingState(face_loss_sec=args.face_loss_sec)
        prev_time = time.monotonic()
        last_telemetry = 0.0
        fps = 0.0
        limiter = FrameRateLimiter(min(args.detect_fps, args.camera_fps))
        thermal = ThermalMonitor()

        while True:
            limiter.wait()
            ret, frame = camera.read()
            if not ret:
                print('[ERROR] Camera stream interrupted.')
                break

            height, width = frame.shape[:2]
            faces, latency_ms = detector.detect(frame)
            now = time.monotonic()
            dt = now - prev_time
            prev_time = now
            if dt > 0:
                fps = 0.85 * fps + 0.15 / dt if fps > 0 else 1.0 / dt

            primary_face = state.update(faces, width, height, now,
                                       invert_gaze_x=invert_gaze_x, invert_gaze_y=invert_gaze_y)

            # Move servos based on vision tracking
            if primary_face is not None:
                pan, tilt = tracker.track_face(state.smooth_cx, state.smooth_cy, width, height,
                                              state.deadband, gain_pan=args.gain_pan, gain_tilt=args.gain_tilt)
            elif state.state_name == 'HOLDING':
                pan, tilt = tracker.hold()
            else:
                pan, tilt = tracker.step_scan()

            # OLED Eye Expression logic
            if face_display:
                if args.nightmare:
                    mood = 'NIGHTMARE'
                elif args.naruto:
                    mood = 'NARUTO'
                elif args.uchiha:
                    mood = 'UCHIHA'
                elif voice_state["mood_override"]:
                    mood = voice_state["mood_override"]
                else:
                    mood = state.mood

                face_display.set_expression(
                    mood, state.gaze_x, state.gaze_y,
                    restart_effect=args.uchiha and state.just_settled
                )

            # Thermal warning checks
            thermal_status = thermal.report(now)
            if thermal_status:
                print(thermal_status)

            # Desktop preview or telemetry printing
            if not headless:
                try:
                    cv2.imshow('FORVIZ Robot Tracker & Voice Assistant',
                               draw_hud(frame, primary_face, pan, tilt, state.state_name, fps, latency_ms,
                                        voice_status=voice_state["status"]))
                    if cv2.waitKey(1) & 0xFF in (ord('q'), 27):
                        break
                except cv2.error as exc:
                    print(f'[PREVIEW WARNING] Preview unavailable; switching headless: {exc}')
                    headless = True
            elif now - last_telemetry >= 0.5:
                vtag = f" | {voice_state['status']}" if voice_state['status'] else ""
                print(f'FPS {fps:4.1f} | {state.state_name:8s} | Pan {pan:5.1f} | Tilt {tilt:5.1f}{vtag}')
                last_telemetry = now

    except KeyboardInterrupt:
        print('\n[STOP] Stopping FORVIZ robot...')
    finally:
        # Graceful cleanup of all resources
        if voice_bot is not None:
            voice_bot.stop()
        for resource, method in ((tracker, 'close'), (face_display, 'stop'), (camera, 'release')):
            if resource is not None:
                try:
                    getattr(resource, method)()
                except Exception as exc:
                    print(f'[CLEANUP WARNING] {method}: {exc}')
        if not headless:
            cv2.destroyAllWindows()
        print('FORVIZ shut down cleanly; servo PWM and voice released.')


if __name__ == '__main__':
    main()
