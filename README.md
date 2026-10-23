JASS Direct Audio Recorder v1.0

Requirements:
- Python 3.10 or newer
- FFmpeg available on PATH
- Windows audio output device

Setup (PowerShell):
  cd D:\Github\JASS-Direct-Audio-Recorder
  python -m pip install soundcard numpy

Run:
  .\run.bat

The recorder captures the default speaker output using Windows loopback.
It writes a WAV backup and then converts it to a 192 kbps MP3 with FFmpeg.
Test with a short recording before capturing a full song.
