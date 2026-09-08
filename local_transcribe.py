"""Transcribe video with local faster-whisper and cache words as JSON.

Usage (from project root):
  .\\.venv\\Scripts\\python.exe local_transcribe.py <video.mp4> <out_words.json> [model_size=base]
"""
import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def find_ffmpeg() -> str:
    p = shutil.which("ffmpeg")
    if p:
        return p
    base = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft",
                        "WinGet", "Packages")
    for root in glob.glob(os.path.join(base, "Gyan.FFmpeg*")):
        for cand in Path(root).glob("ffmpeg-*-full_build/bin/ffmpeg.exe"):
            return str(cand)
    raise RuntimeError("ffmpeg not found (not on PATH, no Gyan WinGet package)")


def main():
    video = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else None
    model_size = sys.argv[3] if len(sys.argv) > 3 else "base"
    if not video or not out:
        sys.exit("usage: local_transcribe.py <video.mp4> <out_words.json> [model_size]")

    from faster_whisper import WhisperModel

    ff = find_ffmpeg()
    audio = Path(tempfile.mktemp(suffix=".wav"))
    subprocess.run([ff, "-y", "-v", "error", "-i", str(video),
                    "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
                    str(audio)], check=True)
    try:
        model = WhisperModel(model_size, device="cpu", compute_type="int8")
        segments, _info = model.transcribe(str(audio), word_timestamps=True,
                                           language="es")
        data = [{"word": w.word.strip(), "start": w.start, "end": w.end}
                for seg in segments for w in (seg.words or [])]
    finally:
        audio.unlink(missing_ok=True)

    out.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    print(f"WORDS={len(data)}")
    if data:
        print(f"SPAN={data[0]['start']:.1f}-{data[-1]['end']:.1f}s")
        print("SAMPLE=" + " ".join(w["word"] for w in data[:40]))


main()
