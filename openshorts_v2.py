"""Cut agent-selected clips into raws and external subtitles."""
import argparse
import json
import subprocess
from pathlib import Path

from openshorts_common import FF, MIN_CLIP_S, STD_CODEC_ARGS, fps_args, to_srt
from openshorts_v2lib import crudo_filter, montage_srt, resolve_section


def phase_crudo(video, words, clips, out):
    """Corta crudo 16:9 continuo + .srt por clip; el vertical va en Shotcut."""
    out_args = STD_CODEC_ARGS + fps_args(video)
    for m in clips["clips"]:
        total = round(m["end"] - m["start"], 3)
        if total <= 0:
            print(f"  SKIP clip {m['rank']}: rango vacio")
            continue
        if total > 180.0:
            print(f"  WARN clip {m['rank']}: total {total:.1f}s > 180s (tope Shorts 3min)")
        srt_text = to_srt(words, m["start"], m["end"])
        base = out / f"clip_{m['rank']:02d}"
        srt = base.with_suffix(".srt")
        raw = base.with_suffix(".mp4")
        srt.write_text(srt_text, encoding="utf-8")
        cmd = [FF, "-y", "-v", "error",
               "-ss", str(m["start"]), "-t", str(total),
               "-i", str(Path(video).resolve())] + out_args + [str(raw.resolve())]
        r = subprocess.run(cmd)
        print(("OK " if r.returncode == 0 else "CRUD0-FAIL ") + raw.name)


def phase_montage(video, words, montages, out):
    """Corta crudo 16:9 + .srt por clip; el vertical se monta en Shotcut."""
    out_args = STD_CODEC_ARGS + fps_args(video)
    for m in montages["montages"]:
        spans = [dict(s) for s in m["spans"]]
        if not spans:
            print(f"  SKIP clip {m['rank']}: sin spans")
            continue
        for i in range(1, len(spans)):
            if spans[i]["start"] < spans[i-1]["end"]:
                spans[i]["start"] = spans[i-1]["end"]
        spans = [s for s in spans if s["end"] > s["start"]]
        if not spans:
            print(f"  SKIP clip {m['rank']}: spans vacíos tras clamp")
            continue
        total = round(sum(s["end"] - s["start"] for s in spans), 3)
        if total < MIN_CLIP_S:
            need = MIN_CLIP_S - total
            spans[-1] = dict(spans[-1], end=spans[-1]["end"] + need)
            total = MIN_CLIP_S
            m["total"] = total
        if total > 180.0:
            print(f"  WARN clip {m['rank']}: total {total:.1f}s > 180s (tope Shorts 3min)")
        srt_text = montage_srt(to_srt, words, spans)
        base = out / f"clip_{m['rank']:02d}"
        srt = base.with_suffix(".srt")
        raw = base.with_suffix(".mp4")
        srt.write_text(srt_text, encoding="utf-8")
        cmd = [FF, "-y", "-v", "error"]
        for sp in spans:
            cmd += ["-ss", str(sp["start"]), "-t", str(round(sp["end"] - sp["start"], 3)),
                    "-i", str(Path(video).resolve())]
        cmd += ["-filter_complex", crudo_filter(len(spans)),
                "-map", "[vout]", "-map", "[acat]"] + out_args + [str(raw.resolve())]
        r = subprocess.run(cmd)
        print(("OK " if r.returncode == 0 else "MONTAGE-FAIL ") + raw.name)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--words", required=True)
    ap.add_argument("--section", required=True, help="'00:00-MM:SS' en tiempo local de sección")
    ap.add_argument("--offset", type=float, default=0.0, choices=[0.0])
    ap.add_argument("--out", required=True)
    ap.add_argument("--phase", default="montage", choices=["montage", "crudo"])
    ap.add_argument("--only", type=int, default=0)
    args = ap.parse_args()

    resolve_section(args.section, args.offset)
    words = json.loads(Path(args.words).read_text(encoding="utf-8"))
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    if args.phase == "crudo":
        mon = json.loads((out / "clips.json").read_text(encoding="utf-8"))
        if args.only:
            mon = {"clips": [x for x in mon["clips"] if x["rank"] == args.only]}
        phase_crudo(args.video, words, mon, out)
        return
    mon = json.loads((out / "montages.json").read_text(encoding="utf-8"))
    if args.only:
        mon = {"montages": [x for x in mon["montages"] if x["rank"] == args.only]}
    phase_montage(args.video, words, mon, out)


if __name__ == "__main__":
    main()
