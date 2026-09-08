"""Shorts v2: segment -> highlight -> montage per live section (pilot: El Concesionario).

Usage:
  python openshorts_v2.py --video downloads/EPISODIO3_segunda_mitad_45-13_fin.mp4 \
      --words downloads/segunda_mitad_words.json \
      --section "58:31-1:10:40" --offset 2713 --out output/v2/concesionario --phase segment
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "vendor" / "openshorts"))

from openshorts_common import FF, LANGUAGE, build_segments, stage, to_srt
from openshorts_v2lib import HIGHLIGHT_PROMPT_TEMPLATE, HighlightResponse, SEGMENT_PROMPT_TEMPLATE, SegmentResponse, montage_filter, montage_srt, resolve_section
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


def phase_highlight(words, items, n_clips=4):
    scored = sorted([it for it in items if it["kind"] != "relleno"],
                    key=lambda x: x.get("score", 0), reverse=True)[:n_clips]
    flat = [{"w": w["word"], "s": w["start"], "e": w["end"]} for w in words]
    montages = []
    for rank, it in enumerate(scored, 1):
        segments = build_segments(section_words(words, it["start"], it["end"]))
        transcript = {"language": LANGUAGE, "segments": segments,
                      "text": " ".join(w["word"] for w in section_words(words, it["start"], it["end"]))}
        windows = build_transcript_windows(transcript, it["end"] - it["start"],
                                           window_seconds=90, overlap_seconds=30)
        payload = [{"id": w["id"], "start": w["start"], "end": w["end"], "text": w["text"]}
                   for w in windows]
        prompt = HIGHLIGHT_PROMPT_TEMPLATE.format(
            item_a=round(it["start"], 3), item_b=round(it["end"], 3),
            windows_json=json.dumps(payload, ensure_ascii=False))
        parsed = stage(prompt, HighlightResponse, f"v2-highlight-{rank}")
        spans = []
        for sp in parsed.get("spans") or []:
            ns, ne = snap_clip_to_words(sp["start"], sp["end"], flat, it["end"],
                                        min_duration=2.0, max_duration=30.0)
            spans.append({"start": ns, "end": ne, "role": sp["role"]})
        spans.sort(key=lambda s: s["start"])
        # Regla dura: total <= 60s. Recortar rol 'comentarios' primero (del final).
        total = sum(s["end"] - s["start"] for s in spans)
        while total > 60.0:
            droppable = [s for s in reversed(spans) if s["role"] == "comentarios"]
            pool = droppable or list(reversed(spans))
            if len(spans) <= 1:
                raise RuntimeError(f"clip {rank}: un solo span de {total:.1f}s > 60s")
            spans.remove(pool[0])
            total = sum(s["end"] - s["start"] for s in spans)
        total = round(total, 3)
        if total < 15.0:
            print(f"  WARN clip {rank}: total {total:.1f}s < 15s, se extiende en montaje")
        montages.append({"rank": rank, "item": it, "spans": spans, "total": total})
    return {"montages": montages}


def phase_montage(video, words, montages, out, shift0=0.0, shift1=0.0,
                  pan_t0=0.0, pan_dur=1.0):
    for m in montages["montages"]:
        spans = [dict(s) for s in m["spans"]]
        # Clamp a timeline monótona: ningún span empieza antes del fin del anterior.
        for i in range(1, len(spans)):
            if spans[i]["start"] < spans[i-1]["end"]:
                spans[i]["start"] = spans[i-1]["end"]
        if m["total"] < 15.0:
            # Extender el ÚLTIMO span (conserva narrativa) hasta 15s.
            need = 15.0 - m["total"]
            spans[-1] = dict(spans[-1], end=spans[-1]["end"] + need)
            m["total"] = 15.0
        srt_text = montage_srt(to_srt, words, spans)
        base = out / f"clip_{m['rank']:02d}"
        srt = base.with_suffix(".srt")
        vert = Path(str(base) + "_9x16.mp4")
        srt.write_text(srt_text, encoding="utf-8")
        cmd = [FF, "-y", "-v", "error"]
        for sp in spans:
            cmd += ["-ss", str(sp["start"]), "-t", str(round(sp["end"] - sp["start"], 3)),
                    "-i", str(Path(video).resolve())]
        cmd += ["-filter_complex",
                montage_filter(len(spans), shift0, shift1, pan_t0, pan_dur, srt.name),
                "-map", "[vout]", "-map", "[acat]", "-c:a", "aac", vert.name]
        r = subprocess.run(cmd, cwd=str(out))
        print(("OK " if r.returncode == 0 else "MONTAGE-FAIL ") + vert.name)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--words", required=True)
    ap.add_argument("--section", required=True, help="'MM:SS-MM:SS' en tiempo del vivo")
    ap.add_argument("--offset", type=float, default=0.0)
    ap.add_argument("--out", required=True)
    ap.add_argument("--phase", default="all",
                    choices=["segment", "highlight", "montage", "all"])
    ap.add_argument("--clips", type=int, default=4)
    ap.add_argument("--shift0", type=float, default=0.20)
    ap.add_argument("--shift1", type=float, default=0.0)
    ap.add_argument("--pan-t0", type=float, default=12.0)
    ap.add_argument("--pan-dur", type=float, default=3.5)
    ap.add_argument("--only", type=int, default=0)
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

    if args.phase in ("highlight", "all"):
        seg = json.loads((out / "items.json").read_text(encoding="utf-8"))
        mon = phase_highlight(words, seg["items"], args.clips)
        (out / "montages.json").write_text(json.dumps(mon, indent=2, ensure_ascii=False),
                                           encoding="utf-8")
        for m in mon["montages"]:
            print(f"- clip {m['rank']}: total={m['total']:.1f}s spans={len(m['spans'])}")

    if args.phase in ("montage", "all"):
        mon = json.loads((out / "montages.json").read_text(encoding="utf-8"))
        if args.only:
            mon = {"montages": [x for x in mon["montages"] if x["rank"] == args.only]}
        phase_montage(args.video, words, mon, out, args.shift0, args.shift1,
                      args.pan_t0, args.pan_dur)


main()
