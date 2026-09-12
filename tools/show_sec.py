"""Vuelca palabras con timings de un words.json en un rango a un txt legible.

Uso:
  python tools/show_sec.py <words.json> <a-b> <out.txt>
"""
import json
import sys

words_path, rng, out_path = sys.argv[1], sys.argv[2], sys.argv[3]
a, b = (float(x) for x in rng.split("-"))
w = json.load(open(words_path, encoding="utf-8"))
ws = [x for x in w if a <= x["start"] <= b]
toks = [f"{x['word']}({x['start']:.2f}-{x['end']:.2f})" for x in ws]
lines = [" ".join(toks[i:i + 12]) for i in range(0, len(toks), 12)]
open(out_path, "w", encoding="utf-8").write("\n".join(lines) + "\n")
print(f"OK {out_path} ({len(ws)} palabras)")
