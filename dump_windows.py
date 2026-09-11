"""Vuelca words+silences de una seccion a texto legible para seleccion manual.

Uso:
  python dump_windows.py --words downloads/X_words.json --silences downloads/X_silences.json \
      --section 0-1380 --out output/EP2/relatando/transcript.txt
"""
import argparse
import json
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--words", required=True)
    ap.add_argument("--silences", default="")
    ap.add_argument("--section", required=True, help="'a-b' en segundos de archivo")
    ap.add_argument("--block", type=float, default=60.0)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    a, b = (float(x) for x in args.section.split("-"))
    words = [w for w in json.loads(Path(args.words).read_text(encoding="utf-8"))
             if w["end"] >= a and w["start"] <= b]
    sils = []
    if args.silences:
        sils = [s for s in json.loads(Path(args.silences).read_text(encoding="utf-8"))
                if s["end"] >= a and s["start"] <= b]

    events = [("w", w["start"], w) for w in words]
    events += [("s", s["start"], s) for s in sils]
    events.sort(key=lambda e: e[1])

    lines = [f"# seccion {a:g}-{b:g}s, words={len(words)} silencios={len(sils)}",
             "# cortes de spans SOLO donde hay [SILENCIO]; no cortar mid-sentence"]
    cur_block, buf = None, []
    for kind, _, e in events:
        blk = int((e["start"] - a) // args.block)
        if blk != cur_block:
            if buf:
                lines.append(" ".join(buf))
                buf = []
            cur_block = blk
            lines.append(f"\n== {a + blk * args.block:.0f}-"
                         f"{min(a + (blk + 1) * args.block, b):.0f}s ==")
        if kind == "s":
            if buf:
                lines.append(" ".join(buf))
                buf = []
            lines.append(f"[SILENCIO {e['duration']:.1f}s {e['start']:.1f}-{e['end']:.1f}]")
        else:
            if not buf:
                buf.append(f"[{e['start']:.1f}]")
            buf.append(e["word"])
            if len(buf) > 13:
                lines.append(" ".join(buf))
                buf = []
    if buf:
        lines.append(" ".join(buf))
    Path(args.out).write_text("\n".join(lines), encoding="utf-8")
    print(f"OK {args.out} ({len(lines)} lineas)")


if __name__ == "__main__":
    main()
