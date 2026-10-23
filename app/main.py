import os
import queue
import threading
import time
import wave
import subprocess
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from datetime import datetime

try:
    import soundcard as sc
except ImportError:
    sc = None

APP_NAME = "JASS Direct Audio Recorder"
SAMPLE_RATE = 48000
CHANNELS = 2
BLOCK_SECONDS = 0.25

class RecorderApp:
    def __init__(self, root):
        self.root = root
        self.root.title(APP_NAME)
        self.root.geometry("680x470")
        self.root.minsize(620, 430)

        self.recording = False
        self.worker = None
        self.started_at = None
        self.frames_written = 0
        self.wav_path = None
        self.output_dir = os.path.join(os.path.expanduser("~"), "Music", "JASS Recordings")
        os.makedirs(self.output_dir, exist_ok=True)

        self.status = tk.StringVar(value="Ready")
        self.timer = tk.StringVar(value="00:00:00")
        self.folder = tk.StringVar(value=self.output_dir)
        self.filename = tk.StringVar(
            value="Recording_" + datetime.now().strftime("%Y%m%d_%H%M%S")
        )

        self._build_ui()
        self._check_dependencies()
        self.root.after(250, self._tick)

    def _build_ui(self):
        outer = ttk.Frame(self.root, padding=20)
        outer.pack(fill="both", expand=True)

        ttk.Label(outer, text="JASS Direct Audio Recorder",
                  font=("Segoe UI", 18, "bold")).pack(anchor="w")
        ttk.Label(outer, text="Capture your computer's audio directly — no microphone",
                  font=("Segoe UI", 10)).pack(anchor="w", pady=(2, 18))

        status_frame = ttk.LabelFrame(outer, text="Recording status", padding=12)
        status_frame.pack(fill="x")
        ttk.Label(status_frame, textvariable=self.status,
                  font=("Segoe UI", 11, "bold")).pack(anchor="w")
        ttk.Label(status_frame, textvariable=self.timer,
                  font=("Consolas", 24)).pack(anchor="w", pady=(5, 0))

        ttk.Label(outer, text="Output filename (without extension)").pack(anchor="w", pady=(16, 4))
        ttk.Entry(outer, textvariable=self.filename).pack(fill="x")

        ttk.Label(outer, text="Save folder").pack(anchor="w", pady=(12, 4))
        folder_row = ttk.Frame(outer)
        folder_row.pack(fill="x")
        ttk.Entry(folder_row, textvariable=self.folder).pack(side="left", fill="x", expand=True)
        ttk.Button(folder_row, text="Browse…", command=self._browse_folder).pack(side="left", padx=(8, 0))

        controls = ttk.Frame(outer)
        controls.pack(fill="x", pady=(18, 0))
        self.start_btn = ttk.Button(controls, text="●  Start Recording", command=self.start_recording)
        self.start_btn.pack(side="left")
        self.stop_btn = ttk.Button(controls, text="■  Stop & Save", command=self.stop_recording, state="disabled")
        self.stop_btn.pack(side="left", padx=8)

        ttk.Label(outer, text="Output: WAV recording, then MP3 conversion with FFmpeg",
                  foreground="#555555").pack(anchor="w", pady=(14, 0))

    def _check_dependencies(self):
        if sc is None:
            self.status.set("Setup required: soundcard package missing")
            messagebox.showerror(
                APP_NAME,
                "The audio recording package is missing.\n\n"
                "Run the setup commands in the project README or reinstall soundcard."
            )
            return
        try:
            ffmpeg = self._find_ffmpeg()
            if not ffmpeg:
                self.status.set("Ready — FFmpeg not found")
            else:
                self.status.set("Ready — audio loopback available to test")
        except Exception as exc:
            self.status.set("Ready — check audio device")

    def _find_ffmpeg(self):
        from shutil import which
        found = which("ffmpeg")
        if found:
            return found
        candidates = [
            os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "WinGet",
                         "Packages", "Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe"),
        ]
        for base in candidates:
            if os.path.isdir(base):
                for root, _, files in os.walk(base):
                    if "ffmpeg.exe" in files:
                        return os.path.join(root, "ffmpeg.exe")
        return None

    def _browse_folder(self):
        selected = filedialog.askdirectory(initialdir=self.folder.get() or os.path.expanduser("~"))
        if selected:
            self.folder.set(selected)

    def _loopback_microphone(self):
        # SoundCard exposes Windows WASAPI loopback devices as loopback microphones.
        speakers = sc.default_speaker()
        if speakers is None:
            raise RuntimeError("Windows did not report a default speaker device.")
        mic = sc.get_microphone(id=str(speakers.name), include_loopback=True)
        if mic is None:
            raise RuntimeError("Could not find the speaker's loopback device.")
        return mic

    def start_recording(self):
        if self.recording:
            return
        if sc is None:
            messagebox.showerror(APP_NAME, "Install the soundcard package first.")
            return

        name = self.filename.get().strip()
        if not name:
            messagebox.showwarning(APP_NAME, "Please enter a filename.")
            return
        if any(ch in name for ch in '<>:"/\\|?*'):
            messagebox.showwarning(APP_NAME, "Please remove Windows-invalid filename characters.")
            return

        output_dir = self.folder.get().strip()
        if not output_dir:
            messagebox.showwarning(APP_NAME, "Please select a save folder.")
            return

        try:
            os.makedirs(output_dir, exist_ok=True)
            self.mic = self._loopback_microphone()
        except Exception as exc:
            messagebox.showerror(
                APP_NAME,
                "Could not open Windows audio loopback.\n\n"
                f"{exc}\n\nCheck that your speakers are enabled and try again."
            )
            return

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base = os.path.join(output_dir, name)
        if os.path.exists(base + ".wav") or os.path.exists(base + ".mp3"):
            base = base + "_" + stamp
        self.wav_path = base + ".wav"
        self.mp3_path = base + ".mp3"
        self.recording = True
        self.started_at = time.monotonic()
        self.frames_written = 0
        self.status.set("Recording computer audio…")
        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.worker = threading.Thread(target=self._record_loop, daemon=True)
        self.worker.start()

    def _record_loop(self):
        try:
            with wave.open(self.wav_path, "wb") as wav:
                wav.setnchannels(CHANNELS)
                wav.setsampwidth(2)
                wav.setframerate(SAMPLE_RATE)
                with self.mic.recorder(samplerate=SAMPLE_RATE, channels=CHANNELS) as recorder:
                    while self.recording:
                        data = recorder.record(numframes=int(SAMPLE_RATE * BLOCK_SECONDS))
                        if data is None or len(data) == 0:
                            continue
                        # SoundCard returns floating-point samples; convert to signed 16-bit PCM.
                        import numpy as np
                        data = np.asarray(data)
                        data = np.nan_to_num(data, nan=0.0, posinf=1.0, neginf=-1.0)
                        pcm = (np.clip(data, -1.0, 1.0) * 32767.0).astype("<i2")
                        wav.writeframesraw(pcm.tobytes())
                        self.frames_written += len(pcm)
        except Exception as exc:
            self.root.after(0, lambda msg=str(exc): self._record_error(msg))

    def _record_error(self, msg):
        self.recording = False
        self.status.set("Recording error")
        self.start_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")
        messagebox.showerror(APP_NAME, "Recording failed:\n\n" + msg)

    def stop_recording(self):
        if not self.recording:
            return
        self.recording = False
        self.status.set("Finishing recording…")
        self.stop_btn.configure(state="disabled")
        self.root.after(200, self._wait_for_worker)

    def _wait_for_worker(self):
        if self.worker and self.worker.is_alive():
            self.root.after(200, self._wait_for_worker)
            return
        self._convert_to_mp3()

    def _convert_to_mp3(self):
        if not self.wav_path or not os.path.exists(self.wav_path):
            self.status.set("No recording file created")
            self.start_btn.configure(state="normal")
            messagebox.showerror(APP_NAME, "No WAV recording was created.")
            return

        if self.frames_written < SAMPLE_RATE:
            self.status.set("Recording too short")
            self.start_btn.configure(state="normal")
            messagebox.showwarning(APP_NAME, "The recording is under one second. Please test again.")
            return

        ffmpeg = self._find_ffmpeg()
        if not ffmpeg:
            self.status.set("WAV saved — FFmpeg not found")
            self.start_btn.configure(state="normal")
            messagebox.showwarning(
                APP_NAME,
                f"Recording saved as WAV:\n{self.wav_path}\n\n"
                "FFmpeg was not found, so MP3 conversion was skipped."
            )
            return

        try:
            result = subprocess.run(
                [ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                 "-i", self.wav_path, "-codec:a", "libmp3lame", "-b:a", "192k",
                 self.mp3_path],
                capture_output=True, text=True, timeout=180
            )
            if result.returncode != 0:
                raise RuntimeError(result.stderr.strip() or "FFmpeg conversion failed")
            self.status.set("Saved MP3 successfully")
            self.start_btn.configure(state="normal")
            messagebox.showinfo(
                APP_NAME,
                "Recording saved successfully:\n\n"
                f"MP3: {self.mp3_path}\n\n"
                f"Backup WAV: {self.wav_path}"
            )
        except Exception as exc:
            self.status.set("WAV saved — MP3 conversion failed")
            self.start_btn.configure(state="normal")
            messagebox.showerror(
                APP_NAME,
                f"WAV recording is safe:\n{self.wav_path}\n\nMP3 conversion failed:\n{exc}"
            )

    def _tick(self):
        if self.recording and self.started_at is not None:
            seconds = int(time.monotonic() - self.started_at)
            h, rem = divmod(seconds, 3600)
            m, s = divmod(rem, 60)
            self.timer.set(f"{h:02d}:{m:02d}:{s:02d}")
        self.root.after(250, self._tick)

def main():
    root = tk.Tk()
    app = RecorderApp(root)
    root.mainloop()

if __name__ == "__main__":
    main()
