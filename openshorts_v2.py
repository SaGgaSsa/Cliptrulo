"""Shorts v2: segment -> highlight -> montage per live section (pilot: El Concesionario).

Usage:
  python openshorts_v2.py --video downloads/EPISODIO3_segunda_mitad_45-13_fin.mp4 \
      --words downloads/segunda_mitad_words.json \
      --section "58:31-1:10:40" --offset 2713 --out output/v2/concesionario --phase segment
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "vendor" / "openshorts"))

from openshorts_common import LANGUAGE, build_segments, stage
from openshorts_v2lib import SEGMENT_PROMPT_TEMPLATE, SegmentResponse, resolve_section
from clip_selection import build_transcript_windows, snap_clip_to_words


def section_words(words, a, b):
    return [w for w in words if w["end"] >= a and w["start"] <= b]


def phase_segment(words, sec_a, sec_b):
    segments = build_segments(section_words(words, sec_a, sec_b))
    transcript = {"language": LANGUAGE, "segments": segments,
                  "text": " ".join(w["word"] for w in section_words(words, sec_a, sec_b))}
    windows = build_transcript_windows(transcript, sec_b - sec_a,
                                       window_seconds=90, overlap_seconds=30)
    print(f"segment: words-in-section, windows={len(windows)}")
    # build_transcript_windows devuelve tiempos ABSOLUTOS (los segmentos ya vienen
    # en tiempo de archivo): NO sumar sec_a.
    payload = [{"id": w["id"], "start": w["start"], "end": w["end"], "text": w["text"]}
               for w in windows]
    prompt = SEGMENT_PROMPT_TEMPLATE.format(
        sec_a=round(sec_a, 3), sec_b=round(sec_b, 3),
        windows_json=json.dumps(payload, ensure_ascii=False))
    parsed = stage(prompt, SegmentResponse, "v2-segment")
    flat = [{"w": w["word"], "s": w["start"], "e": w["end"]} for w in words]
    items = []
    for it in parsed.get("items") or []:
        ns, ne = snap_clip_to_words(it["start"], it["end"], flat, sec_b,
                                    min_duration=3.0, max_duration=600.0)
        items.append({"start": ns, "end": ne, "kind": it["kind"],
                      "score": it["score"], "summary": it.get("summary", "")})
    return {"sec_a": sec_a, "sec_b": sec_b, "items": items}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--words", required=True)
    ap.add_argument("--section", required=True, help="'MM:SS-MM:SS' en tiempo del vivo")
    ap.add_argument("--offset", type=float, default=0.0)
    ap.add_argument("--out", required=True)
    ap.add_argument("--phase", default="all",
                    choices=["segment", "highlight", "montage", "all"])
    args = ap.parse_args()

    words = json.loads(Path(args.words).read_text(encoding="utf-8"))
    sec_a, sec_b = resolve_section(args.section, args.offset)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    if args.phase in ("segment", "all"):
        seg = phase_segment(words, sec_a, sec_b)
        (out / "items.json").write_text(json.dumps(seg, indent=2, ensure_ascii=False),
                                        encoding="utf-8")
        for it in seg["items"]:
            print(f"- [{it['start']:.0f}-{it['end']:.0f}] {it['kind']} score={it['score']} {it['summary'][:80]}")


main()
