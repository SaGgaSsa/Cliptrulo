"""Cut openshorts shorts: 16:9 + 9:16 vertical with burned subtitles + preview frame.

Usage:
  python openshorts_cut.py --video downloads/EPISODIO3_segunda_mitad_45-13_fin.mp4 \
      --words downloads/segunda_mitad_words.json \
      --shorts output/openshorts_segunda_mitad/shorts.json \
      --out output/openshorts_segunda_mitad
"""
import argparse
import json
import subprocess
from pathlib import Path

from openshorts_common import FF, to_srt, vertical_vf


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", default="downloads/EPISODIO3_primera_mitad_00-00_00-48.mp4")
    ap.add_argument("--words", default="downloads/primera_mitad_words.json")
    ap.add_argument("--shorts", default="output/openshorts_primera_mitad/shorts.json")
    ap.add_argument("--out", default="output/openshorts_primera_mitad")
    # 9:16 base crop tuning (fractions of crop width ow=ih*9/16):
    # shift0 = offset at clip t=0, shift1 = offset after pan. 0 = centered.
    # Positive = crop moves right (TikTok pushed right by fullscreen black panel).
    ap.add_argument("--shift0", type=float, default=0.20)
    ap.add_argument("--shift1", type=float, default=0.0)
    ap.add_argument("--pan-t0", type=float, default=12.0)
    ap.add_argument("--pan-dur", type=float, default=3.5)
    ap.add_argument("--only", type=int, default=0,
                    help="1-based short index to process (0 = all)")
    ap.add_argument("--only-9x16", action="store_true",
                    help="regenerate only the vertical mp4 (reuse existing .srt)")
    args = ap.parse_args()

    video = Path(args.video)
    words = json.loads(Path(args.words).read_text(encoding="utf-8"))
    shorts = json.loads(Path(args.shorts).read_text(encoding="utf-8"))["shorts"]
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    for n, s in enumerate(shorts, 1):
        if args.only and n != args.only:
            continue
        a, b = s["start"] - 0.0, s["end"]
        if b - a < 15:
            b = a + 15
        base = out / f"short_{n:02d}_{int(a//3600):02d}h{int(a%3600//60):02d}m{int(a%60):02d}s"
        mp4 = base.with_suffix(".mp4")
        vert = Path(str(base) + "_9x16.mp4")
        srt = base.with_suffix(".srt")
        frame = Path(str(base) + "_frame.jpg")
        if not args.only_9x16:
            srt.write_text(to_srt(words, a, b), encoding="utf-8")
            subprocess.run([FF, "-y", "-v", "error", "-ss", str(a), "-i", str(video),
                            "-t", str(round(b - a, 3)), "-c", "copy", str(mp4)], check=True)
        # NOTE: the subtitles filter misparses Windows drive-letter colons, so pass
        # only the .srt basename and run ffmpeg with cwd=out.
        # 9:16 base: TikTok window drifts (streamer resizes browser mid-live), so the
        # crop pans from shift0 to shift1 (fractions of crop width) over
        # [pan_t0, pan_t0+pan_dur] seconds of clip time. Static per clip otherwise.
        # Webcam box (title CHITRULO + face, static): x=1085..1250, y=24..266
        # measured on 1280x720 source, expressed relative so 1920x1080 scales too.
        vf = vertical_vf(args.shift0, args.shift1, args.pan_t0, args.pan_dur, srt.name)
        r = subprocess.run([FF, "-y", "-v", "error", "-ss", str(a), "-i", str(video.resolve()),
                            "-t", str(round(b - a, 3)), "-vf", vf,
                            "-c:a", "aac", vert.name], cwd=str(out))
        print(("OK " if r.returncode == 0 else "SUBTITLE-FAIL ") + vert.name)
        if args.only_9x16:
            continue
        mid = a + (b - a) / 2
        subprocess.run([FF, "-y", "-v", "error", "-ss", str(mid), "-i", str(video),
                        "-frames:v", "1", str(frame)], check=True)
        print("OK frame", frame.name)


main()
