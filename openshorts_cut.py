"""Cut openshorts shorts: 16:9 + 9:16 vertical with burned subtitles + preview frame.

Usage:
  python openshorts_cut.py --video downloads/EPISODIO3_segunda_mitad_45-13_fin.mp4 \
      --words downloads/segunda_mitad_words.json \
      --shorts output/openshorts_segunda_mitad/shorts.json \
      --out output/openshorts_segunda_mitad
"""
import argparse
import glob
import json
import os
import shutil
import subprocess
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


FF = find_ffmpeg()


def to_srt(words, a, b):
    lines, i, cur = [], 1, []
    def fmt(t):
        ms = int(t * 1000)
        return f"{ms//3600000:02d}:{(ms//60000)%60:02d}:{(ms//1000)%60:02d},{ms%1000:03d}"
    for w in words:
        if w["end"] < a or w["start"] > b:
            continue
        cur.append(w)
        text = " ".join(x["word"] for x in cur)
        if len(text) >= 42 or w["end"] - cur[0]["start"] >= 2.5:
            lines.append(f"{i}\n{fmt(max(cur[0]['start'],a) - a)} --> {fmt(min(cur[-1]['end'],b) - a)}\n{text}\n")
            i += 1
            cur = []
    if cur:
        lines.append(f"{i}\n{fmt(max(cur[0]['start'],a) - a)} --> {fmt(min(cur[-1]['end'],b) - a)}\n{' '.join(x['word'] for x in cur)}\n")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", default="downloads/EPISODIO3_primera_mitad_00-00_00-48.mp4")
    ap.add_argument("--words", default="downloads/primera_mitad_words.json")
    ap.add_argument("--shorts", default="output/openshorts_primera_mitad/shorts.json")
    ap.add_argument("--out", default="output/openshorts_primera_mitad")
    args = ap.parse_args()

    video = Path(args.video)
    words = json.loads(Path(args.words).read_text(encoding="utf-8"))
    shorts = json.loads(Path(args.shorts).read_text(encoding="utf-8"))["shorts"]
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    for n, s in enumerate(shorts, 1):
        a, b = s["start"] - 0.0, s["end"]
        if b - a < 15:
            b = a + 15
        base = out / f"short_{n:02d}_{int(a//3600):02d}h{int(a%3600//60):02d}m{int(a%60):02d}s"
        mp4 = base.with_suffix(".mp4")
        vert = Path(str(base) + "_9x16.mp4")
        srt = base.with_suffix(".srt")
        frame = Path(str(base) + "_frame.jpg")
        srt.write_text(to_srt(words, a, b), encoding="utf-8")
        subprocess.run([FF, "-y", "-v", "error", "-ss", str(a), "-i", str(video),
                        "-t", str(round(b - a, 3)), "-c", "copy", str(mp4)], check=True)
        # NOTE: the subtitles filter misparses Windows drive-letter colons, so pass
        # only the .srt basename and run ffmpeg with cwd=out.
        # 9:16 base (center crop of the vertical TikTok area) + Chitrulo webcam PiP.
        # Webcam box in 1920x1080 source ~ x=1670..1905, y=8..258 (stable across segments).
        vf = (
            "[0:v]split=2[full1][full2];"
            "[full1]crop=ih*9/16:ih,scale=1080:1920[base];"
            "[full2]crop=235:250:1670:8,scale=340:362[cam];"
            "[base][cam]overlay=1080-340-20:20,"
            f"subtitles={srt.name}"
        )
        r = subprocess.run([FF, "-y", "-v", "error", "-ss", str(a), "-i", str(video.resolve()),
                            "-t", str(round(b - a, 3)), "-vf", vf,
                            "-c:a", "aac", vert.name], cwd=str(out))
        print(("OK " if r.returncode == 0 else "SUBTITLE-FAIL ") + vert.name)
        mid = a + (b - a) / 2
        subprocess.run([FF, "-y", "-v", "error", "-ss", str(mid), "-i", str(video),
                        "-frames:v", "1", str(frame)], check=True)
        print("OK frame", frame.name)


main()
