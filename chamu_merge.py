"""Une partes de chamu JSON (transcriptas por tramos con --time-offset absoluto)
en un solo documento: concatena segmentos, renumera ids y recalcula
silences[] como gaps entre palabras >= umbral. Uso:
  python chamu_merge.py out.json p1.json p2.json [--silence-threshold 1.0]
"""
import json
import sys

paths = [a for a in sys.argv[1:] if not a.startswith("--")]
out_path = paths[0]
in_paths = paths[1:]
th = 1.0
for a in sys.argv[1:]:
    if a.startswith("--silence-threshold"):
        th = float(a.split("=", 1)[1])

segs = []
meta = {}
for p in in_paths:
    with open(p, encoding="utf-8") as f:
        doc = json.load(f)
    meta = {k: doc.get(k) for k in ("version", "source", "language", "model")}
    segs.extend(doc["segments"])
segs.sort(key=lambda s: s["start"])
for i, s in enumerate(segs):
    s["id"] = i

words = [w for s in segs for w in s.get("words", [])]
silences = []
for a, b in zip(words, words[1:]):
    gap = b["start"] - a["end"]
    if gap >= th:
        silences.append({"start": round(a["end"], 2), "end": round(b["start"], 2),
                         "dur": round(gap, 2)})

doc = {"duration": round(segs[-1]["end"], 2) if segs else 0.0,
       "offset_base": 0.0, "segments": segs, "silences": silences}
doc.update({k: v for k, v in meta.items() if v is not None})
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(doc, f, ensure_ascii=False)
nw = len(words)
print(f"MERGED segments={len(segs)} words={nw} silences={len(silences)} "
      f"span=0-{doc['duration']}s -> {out_path}")
