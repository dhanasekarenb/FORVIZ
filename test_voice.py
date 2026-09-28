"""FORVIZ Voice & Audio Diagnostic Test Tool
===================================================
Tests headphones, microphone, ALSA audio routing, volume, and Groq API.

Usage:
  python3 test_voice.py             # Full interactive audio diagnostic & test
  python3 test_voice.py --scan      # Scan audio input/output devices & volume
  python3 test_voice.py --play-test # Play test audio through all available outputs
  python3 test_voice.py --mic-test  # Record from mic and play back through headphones
  python3 test_voice.py --groq-test # Test Groq API (Whisper + Llama)
  python3 test_voice.py --unmute    # Unmute all audio channels and set volume to 100%
"""
__test__ = False  # Exclude from automated test runners

import argparse
import io
import json
import math
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import wave

# Optional imports
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
    import edge_tts
    import asyncio
    EDGE_TTS_AVAILABLE = True
except ImportError:
    EDGE_TTS_AVAILABLE = False

try:
    import pyaudio
    PYAUDIO_AVAILABLE = True
except ImportError:
    PYAUDIO_AVAILABLE = False

try:
    from groq import Groq
    GROQ_AVAILABLE = True
except ImportError:
    GROQ_AVAILABLE = False


def generate_sine_wave(freq=440.0, duration_sec=1.5, sample_rate=16000, volume=0.7):
    """Generate a clean 16-bit PCM mono sine wave in memory as WAV bytes."""
    num_samples = int(duration_sec * sample_rate)
    wav_io = io.BytesIO()
    with wave.open(wav_io, 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        frames = bytearray()
        for i in range(num_samples):
            # Double beep pattern
            t = i / sample_rate
            if (0.0 <= t <= 0.4) or (0.6 <= t <= 1.0):
                val = int(volume * 32767.0 * math.sin(2.0 * math.pi * freq * t))
            else:
                val = 0
            frames.extend(struct.pack('<h', val))
        wf.writeframes(frames)
    return wav_io.getvalue()


def get_alsa_devices():
    """List all ALSA playback and capture devices."""
    play_devices = []
    rec_devices = []

    if shutil.which("aplay"):
        try:
            res = subprocess.run(["aplay", "-l"], capture_output=True, text=True, timeout=5)
            for line in res.stdout.splitlines():
                if line.startswith("card "):
                    play_devices.append(line.strip())
        except Exception:
            pass

    if shutil.which("arecord"):
        try:
            res = subprocess.run(["arecord", "-l"], capture_output=True, text=True, timeout=5)
            for line in res.stdout.splitlines():
                if line.startswith("card "):
                    rec_devices.append(line.strip())
        except Exception:
            pass

    return play_devices, rec_devices


def unmute_alsa():
    """Unmute ALSA mixer controls and set volume to 100%."""
    print("\n[AUDIO] Unmuting ALSA audio controls and setting volume to 100%...")
    if not shutil.which("amixer"):
        print("  [NOTE] amixer not found. Skipping ALSA mixer adjustment.")
        return

    # Try setting volume on card 0, card 1, card 2
    for card in [0, 1, 2, "Headphones", "bcm2835_headpho"]:
        for control in ["Master", "Headphone", "PCM", "Speaker"]:
            try:
                cmd = ["amixer", "-c", str(card), "set", control, "100%", "unmute"]
                subprocess.run(cmd, capture_output=True, timeout=2)
            except Exception:
                pass

    # If amixer supports default sset
    for control in ["Master", "Headphone", "PCM", "Speaker"]:
        try:
            subprocess.run(["amixer", "sset", control, "100%", "unmute"],
                           capture_output=True, timeout=2)
        except Exception:
            pass

    # On Raspberry Pi, force route to 3.5mm headphone jack if using onboard audio
    try:
        subprocess.run(["amixer", "cset", "numid=3", "1"], capture_output=True, timeout=2)
    except Exception:
        pass

    print("  [SUCCESS] Volume commands sent to ALSA mixer.")


def scan_devices():
    """Print complete audio diagnostics for Pi/PC."""
    print("=" * 65)
    print("           FORVIZ AUDIO & HEADSET DIAGNOSTIC SCANNER")
    print("=" * 65)

    # 1. Check system tools
    print("\n--- 1. System Audio Tools ---")
    for tool in ["aplay", "arecord", "amixer", "alsamixer", "mpg123", "mpv", "ffplay", "espeak"]:
        path = shutil.which(tool)
        status = f"Available ({path})" if path else "NOT INSTALLED"
        print(f"  {tool:12s}: {status}")

    # 2. Check Python audio modules
    print("\n--- 2. Python Audio Modules ---")
    print(f"  pyaudio     : {'Installed' if PYAUDIO_AVAILABLE else 'NOT installed (sudo apt install python3-pyaudio)'}")
    print(f"  pygame      : {'Installed' if PYGAME_AVAILABLE else 'NOT installed (pip install pygame)'}")
    print(f"  gTTS        : {'Installed' if GTTS_AVAILABLE else 'NOT installed (pip install gtts)'}")
    print(f"  edge-tts    : {'Installed' if EDGE_TTS_AVAILABLE else 'NOT installed (pip install edge-tts)'}")
    print(f"  groq        : {'Installed' if GROQ_AVAILABLE else 'NOT installed (pip install groq)'}")

    # 3. List ALSA Hardware Cards
    print("\n--- 3. Connected Hardware Audio Devices (ALSA) ---")
    play_devs, rec_devs = get_alsa_devices()
    print("Playback Devices (Speakers / Headphones):")
    if play_devs:
        for d in play_devs:
            print(f"  -> {d}")
    else:
        print("  (None detected via aplay -l or running on Windows/Mac)")

    print("\nCapture Devices (Microphone):")
    if rec_devs:
        for d in rec_devs:
            print(f"  -> {d}")
    else:
        print("  [WARNING] No microphone detected via arecord -l!")
        print("  Note: Raspberry Pi 4's 3.5mm jack is OUTPUT ONLY (no mic).")
        print("  For microphone, plug in a USB Headset or a $2 USB audio dongle.")

    # 4. Check PyAudio devices if available
    if PYAUDIO_AVAILABLE:
        print("\n--- 4. PyAudio Device List ---")
        try:
            p = pyaudio.PyAudio()
            for i in range(p.get_device_count()):
                info = p.get_device_info_by_index(i)
                name = info.get("name")
                max_in = info.get("maxInputChannels", 0)
                max_out = info.get("maxOutputChannels", 0)
                print(f"  Device [{i}]: {name} (Inputs: {max_in}, Outputs: {max_out})")
            p.terminate()
        except Exception as e:
            print(f"  PyAudio scan error: {e}")

    # 5. Check Groq API Key
    print("\n--- 5. Groq Cloud Credentials ---")
    key = os.environ.get("GROQ_API_KEY")
    if not key:
        dotenv = Path.cwd() / ".env"
        if dotenv.is_file():
            for line in dotenv.read_text(encoding="utf-8").splitlines():
                if line.strip().startswith("GROQ_API_KEY="):
                    key = line.split("=", 1)[1].strip().strip('"\'')
                    break
    if key:
        print(f"  GROQ_API_KEY: Configured (starts with: {key[:8]}...)")
    else:
        print("  GROQ_API_KEY: NOT SET! Voice assistant will not be able to query Groq.")
        print("  To set it: export GROQ_API_KEY='gsk_...' or add to .env file.")

    print("\n" + "=" * 65)


def play_audio_file(file_path):
    """Play audio file using the best available player."""
    # Method 1: Pygame
    if PYGAME_AVAILABLE:
        try:
            pygame.mixer.init()
            pygame.mixer.music.load(file_path)
            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy():
                time.sleep(0.05)
            if hasattr(pygame.mixer.music, 'unload'):
                pygame.mixer.music.unload()
            return True
        except Exception:
            pass

    # Method 2: System players on Linux
    for player in ["aplay", "mpg123", "mpv", "ffplay"]:
        if shutil.which(player):
            try:
                if player == "aplay":
                    # aplay only plays WAV directly
                    subprocess.run(["aplay", "-q", file_path], timeout=10, check=True)
                    return True
                extra = ["-nodisp", "-autoexit"] if player == "ffplay" else (["--no-video"] if player == "mpv" else ["-q"])
                subprocess.run([player] + extra + [file_path], timeout=10, check=True)
                return True
            except Exception:
                pass
    return False


def test_playback():
    """Play a test beep and spoken speech to test output."""
    print("\n" + "=" * 65)
    print("                  AUDIO OUTPUT PLAYBACK TEST")
    print("=" * 65)
    print("Put on your headphones now.")
    print("First, unmuting ALSA volume to ensure it's not muted...")
    unmute_alsa()

    # 1. Beep test
    print("\n[TEST 1/2] Generating and playing double test tone (Beep-Beep)...")
    sine_wav = generate_sine_wave(freq=520.0, duration_sec=1.2, volume=0.85)
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp.write(sine_wav)
        sine_path = tmp.name

    played = play_audio_file(sine_path)
    try:
        os.remove(sine_path)
    except OSError:
        pass

    if played:
        print("  -> Playback command executed.")
    else:
        print("  [ERROR] No audio player was able to play the tone!")

    # 2. Spoken voice test
    print("\n[TEST 2/2] Generating speech: 'Hello! This is a test of your FORVIZ robot.'")
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
        speech_path = tmp.name

    tts_ready = False
    if shutil.which("edge-tts"):
        try:
            cmd = ["edge-tts", "--voice", "en-US-ChristopherNeural",
                   "--text", "Hello! This is a test of your FORVIZ robot audio output. If you can hear this, your headphones are working perfectly!",
                   "--write-media", speech_path]
            subprocess.run(cmd, timeout=8, check=True)
            tts_ready = True
        except Exception:
            pass

    if not tts_ready and GTTS_AVAILABLE:
        try:
            tts = gTTS(text="Hello! This is a test of your FORVIZ robot audio output. If you can hear this, your headphones are working perfectly!", lang='en')
            tts.save(speech_path)
            tts_ready = True
        except Exception:
            pass

    if tts_ready:
        print("  -> Playing spoken voice to headphones...")
        play_audio_file(speech_path)
        try:
            os.remove(speech_path)
        except OSError:
            pass
    elif shutil.which("espeak"):
        print("  -> Using espeak for local voice synthesis...")
        try:
            subprocess.run(["espeak", "-v", "en-us", "Hello! If you can hear this, your headphones are working."], timeout=5)
        except Exception:
            pass
    else:
        print("  [NOTE] Neither edge-tts, gTTS, nor espeak available for speech synthesis.")

    ans = input("\nDid you hear the sound in your headphones? (y/n): ").strip().lower()
    if ans == 'y':
        print("\n  [SUCCESS] Audio output is working properly!")
        return True
    else:
        print("\n  [TROUBLESHOOTING]: If you heard nothing:")
        print("  1. If using 3.5mm jack:")
        print("     - Run 'amixer cset numid=3 1' to force output to the 3.5mm jack instead of HDMI.")
        print("     - Open 'alsamixer' in terminal, select 'Headphones' card, and press Up Arrow to raise volume.")
        print("  2. If using a USB Headset:")
        print("     - Check 'aplay -l' to see which card number it is (e.g. Card 1).")
        print("     - Test directly with: aplay -D plughw:1,0 /usr/share/sounds/alsa/Front_Center.wav")
        return False


def test_microphone():
    """Record 3 seconds of audio and play it back immediately to test headset mic."""
    print("\n" + "=" * 65)
    print("                  HEADSET MICROPHONE TEST")
    print("=" * 65)
    print("We will record 3 seconds from your headset microphone, then play it right back.")
    input("Press [ENTER] to start recording... ")

    sample_rate = 16000
    channels = 1
    duration = 3.0
    recorded_bytes = None

    print(f"\n[RECORDING] Please speak into your headset mic now for {duration:.0f} seconds...")

    # PyAudio recording
    if PYAUDIO_AVAILABLE:
        try:
            p = pyaudio.PyAudio()
            stream = p.open(format=pyaudio.paInt16, channels=channels, rate=sample_rate,
                            input=True, frames_per_buffer=1024)
            frames = []
            for _ in range(int(sample_rate / 1024 * duration)):
                data = stream.read(1024, exception_on_overflow=False)
                frames.append(data)
                # Show simple volume meter
                vol = sum(abs(b - 128) for b in data[:128]) // 128
                bar = "#" * min(30, vol // 2)
                sys.stdout.write(f"\r  Volume: [{bar:<30}]")
                sys.stdout.flush()
            sys.stdout.write("\n")
            stream.stop_stream()
            stream.close()
            p.terminate()

            wav_io = io.BytesIO()
            with wave.open(wav_io, 'wb') as wf:
                wf.setnchannels(channels)
                wf.setsampwidth(2)
                wf.setframerate(sample_rate)
                wf.writeframes(b''.join(frames))
            recorded_bytes = wav_io.getvalue()
        except Exception as e:
            print(f"  PyAudio record error: {e}")

    # Fallback: ALSA arecord on Pi Linux
    if recorded_bytes is None and shutil.which("arecord"):
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp_path = tmp.name
            cmd = ["arecord", "-D", "default", "-f", "S16_LE", "-r", str(sample_rate),
                   "-c", "1", "-d", str(int(duration)), "-q", tmp_path]
            subprocess.run(cmd, timeout=duration + 2, check=True)
            recorded_bytes = Path(tmp_path).read_bytes()
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        except Exception as e:
            print(f"  arecord error: {e}")

    if not recorded_bytes or len(recorded_bytes) < 1000:
        print("\n  [ERROR] No audio recorded! Check headset connection.")
        print("  Note: Pi 4 onboard 3.5mm jack DOES NOT support microphone input.")
        print("  You must use a USB headset or a USB sound adapter for microphone.")
        return False

    print("\n[PLAYBACK] Playing back your recorded voice through headphones...")
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp.write(recorded_bytes)
        play_path = tmp.name

    play_audio_file(play_path)
    try:
        os.remove(play_path)
    except OSError:
        pass

    ans = input("\nDid you hear your own voice playback clearly? (y/n): ").strip().lower()
    if ans == 'y':
        print("\n  [SUCCESS] Headset microphone is working perfectly!")
        return True
    else:
        print("\n  [WARNING] Microphone recorded silence or noise. Check mic mute switch.")
        return False


def test_groq_api():
    """Test Groq API connectivity and models."""
    print("\n" + "=" * 65)
    print("                    GROQ CLOUD API TEST")
    print("=" * 65)
    key = os.environ.get("GROQ_API_KEY")
    if not key:
        dotenv = Path.cwd() / ".env"
        if dotenv.is_file():
            for line in dotenv.read_text(encoding="utf-8").splitlines():
                if line.strip().startswith("GROQ_API_KEY="):
                    key = line.split("=", 1)[1].strip().strip('"\'')
                    break

    if not key:
        print("[FAIL] GROQ_API_KEY not found in environment or .env file.")
        print("To fix:")
        print("  1. Get a free key from https://console.groq.com/")
        print("  2. Run: export GROQ_API_KEY='gsk_your_key_here'")
        print("  3. Or create .env with GROQ_API_KEY='gsk_your_key_here'")
        return False

    print(f"Using GROQ_API_KEY: {key[:8]}...")
    if not GROQ_AVAILABLE:
        print("[WARNING] python 'groq' package not installed. Testing via standard HTTP request...")

    try:
        import urllib.request
        payload = json.dumps({
            "model": "llama-3.3-70b-versatile",
            "messages": [
                {"role": "system", "content": "You are FORVIZ robot. Keep reply under 15 words."},
                {"role": "user", "content": "Hello robot, give me a quick status check."}
            ],
            "max_tokens": 50
        }).encode("utf-8")

        req = urllib.request.Request(
            "https://api.groq.com/openai/v1/chat/completions",
            data=payload,
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json"
            }
        )
        t0 = time.perf_counter()
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            latency_ms = (time.perf_counter() - t0) * 1000
            reply = data["choices"][0]["message"]["content"]
            print(f"\n  [SUCCESS] Groq API Responded in {latency_ms:.0f} ms!")
            print(f"  Robot Response: \"{reply}\"")
            return True
    except Exception as e:
        print(f"\n  [FAIL] Groq API call failed: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="FORVIZ Audio & Voice Assistant Diagnostics")
    parser.add_argument("--scan", action="store_true", help="Scan and list all audio hardware devices")
    parser.add_argument("--unmute", action="store_true", help="Unmute ALSA volume channels and set to 100%%")
    parser.add_argument("--play-test", action="store_true", help="Test headphone audio playback")
    parser.add_argument("--mic-test", action="store_true", help="Test microphone capture and echo playback")
    parser.add_argument("--groq-test", action="store_true", help="Test Groq Cloud API connection")
    args = parser.parse_args()

    if args.unmute:
        unmute_alsa()
        return

    if args.scan:
        scan_devices()
        return

    if args.play_test:
        test_playback()
        return

    if args.mic_test:
        test_microphone()
        return

    if args.groq_test:
        test_groq_api()
        return

    # Interactive full flow
    scan_devices()
    test_playback()
    test_microphone()
    test_groq_api()

    print("\n" + "=" * 65)
    print("                 DIAGNOSTIC TEST COMPLETE")
    print("=" * 65)
    print("To launch FORVIZ with face tracking + voice:")
    print("  python3 forviz.py")
    print("=" * 65 + "\n")


if __name__ == "__main__":
    main()
