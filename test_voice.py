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
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
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


def generate_sine_wave(freq=440.0, duration_sec=1.5, sample_rate=16000, volume=0.85):
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
            if (0.0 <= t <= 0.35) or (0.55 <= t <= 0.95):
                val = int(volume * 32767.0 * math.sin(2.0 * math.pi * freq * t))
            else:
                val = 0
            frames.extend(struct.pack('<h', val))
        wf.writeframes(frames)
    return wav_io.getvalue()


def get_alsa_cards():
    """Parse aplay -l and arecord -l to get card numbers and names."""
    play_cards = []
    rec_cards = []

    if shutil.which("aplay"):
        try:
            res = subprocess.run(["aplay", "-l"], capture_output=True, text=True, timeout=5)
            for line in res.stdout.splitlines():
                m = re.match(r"^card (\d+): ([^\[]+)\[([^\]]+)\]", line)
                if m:
                    card_num = int(m.group(1))
                    card_id = m.group(2).strip()
                    card_name = m.group(3).strip()
                    play_cards.append((card_num, card_id, card_name))
        except Exception:
            pass

    if shutil.which("arecord"):
        try:
            res = subprocess.run(["arecord", "-l"], capture_output=True, text=True, timeout=5)
            for line in res.stdout.splitlines():
                m = re.match(r"^card (\d+): ([^\[]+)\[([^\]]+)\]", line)
                if m:
                    card_num = int(m.group(1))
                    card_id = m.group(2).strip()
                    card_name = m.group(3).strip()
                    rec_cards.append((card_num, card_id, card_name))
        except Exception:
            pass

    return play_cards, rec_cards


def unmute_alsa():
    """Unmute ALSA mixer controls, set volume to 100%, and switch output to headphones."""
    print("\n[AUDIO] Unmuting ALSA audio controls and maximizing volume...")
    if not shutil.which("amixer"):
        print("  [NOTE] amixer not found. Skipping ALSA mixer adjustment.")
        return

    # Force Raspberry Pi onboard routing to 3.5mm jack (1=jack, 2=HDMI, 0=auto)
    try:
        subprocess.run(["amixer", "cset", "numid=3", "1"], capture_output=True, timeout=2)
    except Exception:
        pass

    # Try unmuting across cards 0, 1, 2, Headphones
    for card in [0, 1, 2, "Headphones", "bcm2835_headpho"]:
        for control in ["Master", "Headphone", "PCM", "Speaker", "Capture", "Mic"]:
            try:
                cmd = ["amixer", "-c", str(card), "set", control, "100%", "unmute"]
                subprocess.run(cmd, capture_output=True, timeout=2)
            except Exception:
                pass

    # Unmute default controls
    for control in ["Master", "Headphone", "PCM", "Speaker", "Capture", "Mic"]:
        try:
            subprocess.run(["amixer", "sset", control, "100%", "unmute"],
                           capture_output=True, timeout=2)
        except Exception:
            pass

    # Check for PipeWire / wpctl on modern Pi OS Bookworm
    if shutil.which("wpctl"):
        try:
            subprocess.run(["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", "1.0"], capture_output=True, timeout=2)
            subprocess.run(["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "0"], capture_output=True, timeout=2)
            subprocess.run(["wpctl", "set-mute", "@DEFAULT_AUDIO_SOURCE@", "0"], capture_output=True, timeout=2)
        except Exception:
            pass

    print("  [SUCCESS] Volume commands executed.")


def scan_devices():
    """Print complete audio diagnostics for Pi/PC."""
    print("=" * 65)
    print("           FORVIZ AUDIO & HEADSET DIAGNOSTIC SCANNER")
    print("=" * 65)

    # 1. System audio tools
    print("\n--- 1. System Audio Tools ---")
    for tool in ["aplay", "arecord", "amixer", "wpctl", "pactl", "mpg123", "mpv", "ffplay", "espeak"]:
        path = shutil.which(tool)
        status = f"Available ({path})" if path else "NOT INSTALLED"
        print(f"  {tool:12s}: {status}")

    # 2. Python audio packages
    print("\n--- 2. Python Audio Modules ---")
    print(f"  groq        : {'Installed' if GROQ_AVAILABLE else 'NOT installed (pip install groq)'}")
    print(f"  pyaudio     : {'Installed' if PYAUDIO_AVAILABLE else 'NOT installed (sudo apt install python3-pyaudio)'}")
    print(f"  pygame      : {'Installed' if PYGAME_AVAILABLE else 'NOT installed (pip install pygame)'}")
    print(f"  gTTS        : {'Installed' if GTTS_AVAILABLE else 'NOT installed (pip install gtts)'}")
    print(f"  edge-tts    : {'Installed' if EDGE_TTS_AVAILABLE else 'NOT installed (pip install edge-tts)'}")

    # 3. ALSA Hardware Cards
    print("\n--- 3. Connected Hardware Audio Devices (ALSA) ---")
    play_cards, rec_cards = get_alsa_cards()
    print("Detected Output Devices (Speakers / Headphones):")
    if play_cards:
        for cnum, cid, cname in play_cards:
            print(f"  [Card {cnum}] {cid} -> {cname} (ALSA: plughw:{cnum},0)")
    else:
        print("  (No ALSA cards detected via aplay -l)")

    print("\nDetected Input Devices (Microphone):")
    if rec_cards:
        for cnum, cid, cname in rec_cards:
            print(f"  [Card {cnum}] {cid} -> {cname} (ALSA: plughw:{cnum},0)")
    else:
        print("  [CRITICAL NOTICE] No microphone detected via arecord -l!")
        print("  **IMPORTANT RASPBERRY PI HARDWARE FACT**:")
        print("  The round 3.5mm jack on Raspberry Pi 4 is OUTPUT-ONLY (Stereo + Video).")
        print("  It has NO microphone wiring. If your headset uses a single 3.5mm plug,")
        print("  you MUST plug it into a USB port using a cheap USB Audio Adapter, or use a USB headset!")

    # 4. Check Groq API Key
    print("\n--- 4. Groq Cloud Credentials ---")
    key = os.environ.get("GROQ_API_KEY")
    if not key:
        for p in [Path.cwd() / ".env", Path.home() / ".env"]:
            if p.is_file():
                try:
                    for line in p.read_text(encoding="utf-8").splitlines():
                        if line.strip().startswith("GROQ_API_KEY="):
                            key = line.split("=", 1)[1].strip().strip('"\'')
                            break
                except Exception:
                    pass
    if key:
        print(f"  GROQ_API_KEY: Configured (starts with: {key[:8]}..., length: {len(key)})")
    else:
        print("  GROQ_API_KEY: NOT SET! Run: export GROQ_API_KEY='gsk_...'")

    print("\n" + "=" * 65)


def play_audio_file(file_path, alsa_device=None):
    """Play audio file using the best available player, optionally targeting a specific ALSA device."""
    # Method 1: aplay directly (great for WAV files to specific cards)
    if shutil.which("aplay") and file_path.endswith(".wav"):
        try:
            dev_args = ["-D", alsa_device] if alsa_device else []
            subprocess.run(["aplay", "-q"] + dev_args + [file_path], timeout=10, check=True)
            return True
        except Exception:
            pass

    # Method 2: mpg123
    if shutil.which("mpg123") and file_path.endswith(".mp3"):
        try:
            dev_args = ["-a", alsa_device] if alsa_device else []
            subprocess.run(["mpg123", "-q"] + dev_args + [file_path], timeout=10, check=True)
            return True
        except Exception:
            pass

    # Method 3: Pygame
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

    # Method 4: mpv or ffplay
    for player in ["mpv", "ffplay"]:
        if shutil.which(player):
            try:
                extra = ["--no-video", "-q"] if player == "mpv" else ["-nodisp", "-autoexit", "-loglevel", "quiet"]
                subprocess.run([player] + extra + [file_path], timeout=10, check=True)
                return True
            except Exception:
                pass

    return False


def test_playback():
    """Play a test tone through default and each hardware card so user finds their headphones."""
    print("\n" + "=" * 65)
    print("                  AUDIO OUTPUT PLAYBACK TEST")
    print("=" * 65)
    print("Put on your headphones now.")
    unmute_alsa()

    sine_wav = generate_sine_wave(freq=520.0, duration_sec=1.2, volume=0.9)
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp.write(sine_wav)
        sine_path = tmp.name

    # 1. Test Default Output
    print("\n[TEST 1] Playing test tone through DEFAULT audio device...")
    play_audio_file(sine_path)

    # 2. Test each individual ALSA hardware card if on Linux/Pi
    play_cards, _ = get_alsa_cards()
    card_results = {}
    if play_cards:
        print("\nNow testing each detected hardware audio card one by one:")
        for cnum, cid, cname in play_cards:
            dev = f"plughw:{cnum},0"
            print(f"  -> Testing Card {cnum} ({cname}) via {dev}...")
            played = play_audio_file(sine_path, alsa_device=dev)
            time.sleep(0.5)
            ans = input(f"     Did you hear the double-beep on Card {cnum} ({cname})? (y/n): ").strip().lower()
            if ans == 'y':
                card_results[cnum] = dev
                print(f"     [FOUND!] Your headphones are on Card {cnum}: {dev}")
                break

    try:
        os.remove(sine_path)
    except OSError:
        pass

    # 3. Speech test
    best_device = list(card_results.values())[0] if card_results else None
    print(f"\n[TEST 2] Generating spoken greeting using {'Card ' + best_device if best_device else 'default output'}...")
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
        speech_path = tmp.name

    tts_ready = False
    if shutil.which("edge-tts"):
        try:
            cmd = ["edge-tts", "--voice", "en-US-ChristopherNeural",
                   "--text", "Hello! This is FORVIZ. Your headphones and audio output are working!",
                   "--write-media", speech_path]
            subprocess.run(cmd, timeout=8, check=True)
            tts_ready = True
        except Exception:
            pass

    if not tts_ready and GTTS_AVAILABLE:
        try:
            tts = gTTS(text="Hello! This is FORVIZ. Your headphones and audio output are working!", lang='en')
            tts.save(speech_path)
            tts_ready = True
        except Exception:
            pass

    if tts_ready:
        play_audio_file(speech_path, alsa_device=best_device)
        try:
            os.remove(speech_path)
        except OSError:
            pass
    elif shutil.which("espeak"):
        try:
            subprocess.run(["espeak", "-v", "en-us", "Hello! This is FORVIZ. Audio output is working."], timeout=5)
        except Exception:
            pass

    if best_device:
        print(f"\n  [SUCCESS] Use this command to run FORVIZ with your working audio card:")
        print(f"  python3 forviz.py --audio-device {best_device}")
        return True
    else:
        ans = input("\nDid you hear any test sound in your headphones during the test? (y/n): ").strip().lower()
        return ans == 'y'


def test_microphone():
    """Test headset mic capture."""
    print("\n" + "=" * 65)
    print("                  HEADSET MICROPHONE TEST")
    print("=" * 65)

    _, rec_cards = get_alsa_cards()
    if not rec_cards and sys.platform.startswith("linux"):
        print("[HARDWARE NOTICE]")
        print("  No audio recording/capture devices are detected by Linux!")
        print("  On Raspberry Pi 4:")
        print("  - The 3.5mm onboard round jack is STEREO OUTPUT ONLY (cannot record mic).")
        print("  - If your fintech headset has a 3.5mm plug, you must plug it into a")
        print("    USB Audio Adapter / Sound Dongle so the Pi gets a USB microphone line.")
        print("  - If it is a USB headset, make sure it is firmly plugged into a Pi USB port.")
        return False

    mic_dev = f"plughw:{rec_cards[0][0]},0" if rec_cards else "default"
    print(f"Using recording device: {mic_dev}")
    print("We will record 3 seconds from your mic, then play it right back.")
    input("Press [ENTER] to start recording... ")

    sample_rate = 16000
    duration = 3.0
    recorded_bytes = None

    print(f"\n[RECORDING] Please speak into your headset mic now for {duration:.0f} seconds...")

    # PyAudio recording
    if PYAUDIO_AVAILABLE:
        try:
            p = pyaudio.PyAudio()
            stream = p.open(format=pyaudio.paInt16, channels=1, rate=sample_rate,
                            input=True, frames_per_buffer=1024)
            frames = []
            for _ in range(int(sample_rate / 1024 * duration)):
                data = stream.read(1024, exception_on_overflow=False)
                frames.append(data)
                vol = sum(abs(b - 128) for b in data[:128]) // 128
                bar = "#" * min(30, vol // 2)
                sys.stdout.write(f"\r  Mic Level: [{bar:<30}]")
                sys.stdout.flush()
            sys.stdout.write("\n")
            stream.stop_stream()
            stream.close()
            p.terminate()

            wav_io = io.BytesIO()
            with wave.open(wav_io, 'wb') as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(sample_rate)
                wf.writeframes(b''.join(frames))
            recorded_bytes = wav_io.getvalue()
        except Exception as e:
            print(f"  PyAudio record notice: {e}")

    # Fallback to arecord
    if recorded_bytes is None and shutil.which("arecord"):
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp_path = tmp.name
            cmd = ["arecord", "-D", mic_dev, "-f", "S16_LE", "-r", str(sample_rate),
                   "-c", "1", "-d", str(int(duration)), "-q", tmp_path]
            subprocess.run(cmd, timeout=duration + 2, check=True)
            recorded_bytes = Path(tmp_path).read_bytes()
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        except Exception as e:
            print(f"  arecord notice: {e}")

    if not recorded_bytes or len(recorded_bytes) < 1000:
        print("\n  [ERROR] No audio data recorded.")
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
    return ans == 'y'


def test_groq_api():
    """Test Groq API connectivity and diagnose HTTP errors."""
    print("\n" + "=" * 65)
    print("                    GROQ CLOUD API TEST")
    print("=" * 65)
    key = os.environ.get("GROQ_API_KEY")
    if not key:
        for p in [Path.cwd() / ".env", Path.home() / ".env"]:
            if p.is_file():
                try:
                    for line in p.read_text(encoding="utf-8").splitlines():
                        if line.strip().startswith("GROQ_API_KEY="):
                            key = line.split("=", 1)[1].strip().strip('"\'')
                            break
                except Exception:
                    pass

    if not key:
        print("[FAIL] GROQ_API_KEY not found in environment or .env file.")
        print("To fix:")
        print("  1. Get a free key from https://console.groq.com/keys")
        print("  2. Run: export GROQ_API_KEY='gsk_your_key_here'")
        print("  3. Or create .env with GROQ_API_KEY=gsk_your_key_here")
        return False

    key = key.strip()
    print(f"Using GROQ_API_KEY: {key[:8]}... (length: {len(key)})")

    if not key.startswith("gsk_"):
        print("\n[WARNING] Your Groq API key does not start with 'gsk_'!")
        print("Groq API keys always start with 'gsk_'. Please verify you copied the full key from console.groq.com.")

    # 1. Try official Groq SDK (httpx backend with verified headers)
    if GROQ_AVAILABLE:
        try:
            print("  Connecting via official Groq Python SDK...")
            client = Groq(api_key=key)
            t0 = time.perf_counter()
            response = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "system", "content": "You are FORVIZ robot. Keep reply under 10 words."},
                    {"role": "user", "content": "Hello robot, give me a quick status check."}
                ],
                max_tokens=30
            )
            latency_ms = (time.perf_counter() - t0) * 1000
            reply = response.choices[0].message.content.strip()
            print(f"\n  [SUCCESS] Groq API Responded in {latency_ms:.0f} ms via SDK!")
            print(f"  Robot Response: \"{reply}\"")
            return True
        except Exception as e:
            print(f"  [SDK Notice]: {e}")

    # 2. HTTP request with browser User-Agent (avoids Cloudflare 403 Forbidden)
    print("  Connecting via HTTP API with browser User-Agent...")
    try:
        payload = json.dumps({
            "model": "llama-3.3-70b-versatile",
            "messages": [
                {"role": "system", "content": "You are FORVIZ robot. Keep reply under 10 words."},
                {"role": "user", "content": "Hello robot, give me a quick status check."}
            ],
            "max_tokens": 30
        }).encode("utf-8")

        req = urllib.request.Request(
            "https://api.groq.com/openai/v1/chat/completions",
            data=payload,
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 FORVIZ/1.0"
            }
        )
        t0 = time.perf_counter()
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            latency_ms = (time.perf_counter() - t0) * 1000
            reply = data["choices"][0]["message"]["content"].strip()
            print(f"\n  [SUCCESS] Groq API Responded in {latency_ms:.0f} ms via direct HTTP!")
            print(f"  Robot Response: \"{reply}\"")
            return True
    except urllib.error.HTTPError as e:
        print(f"\n  [FAIL] Groq API HTTP Error {e.code}: {e.reason}")
        try:
            body = e.read().decode("utf-8", errors="ignore")
            print(f"  Server error response: {body}")
        except Exception:
            pass
        if e.code == 403:
            print("\n  [HOW TO RESOLVE 403 FORBIDDEN]:")
            print("  1. The API key may be invalid, truncated, or revoked.")
            print("  2. Go to https://console.groq.com/keys, create a brand-new API key.")
            print("  3. Set it in your terminal:")
            print("     export GROQ_API_KEY='gsk_paste_new_key_here'")
            print("  4. If your Raspberry Pi is connected to a VPN or restricted network, Cloudflare might block the IP.")
        return False
    except Exception as e:
        print(f"\n  [FAIL] Connection failed: {e}")
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


if __name__ == "__main__":
    main()
