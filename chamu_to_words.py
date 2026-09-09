"""Adaptador chamu-cli JSON -> words JSON del pipeline + silences sidecar.

El JSON de chamu (`--format json`, tiempos con offset ya aplicado) trae
segments[].words[{w,start,end}] y silences[]. Esto lo aplana al formato
`[{"word","start","end"}]` que consumen run/v2/cut/show, y guarda los
silencios aparte para validación futura de cortes.

Usage:
  python chamu_to_words.py <chamu.json> <out_words.json>
      [--silences out_sil.json] [--offset 0.0]
"""
import json
import sys
from pathlib import Path


def main():
    args = sys.argv[1:]
    if len(args) < 2:
        sys.exit("usage: chamu_to_words.py <chamu.json> <out_words.json> "
                 "[--silences out_sil.json] [--offset 0.0]")
    src, out = Path(args[0]), Path(args[1])
    sil_out, offset = None, 0.0
    i = 2
    while i < len(args):
        if args[i] == "--silences" and i + 1 < len(args):
            sil_out = Path(args[i + 1])
            i += 2
        elif args[i] == "--offset" and i + 1 < len(args):
            offset = float(args[i + 1])
            i += 2
        else:
            sys.exit(f"flag desconocido: {args[i]}")

    doc = json.loads(src.read_text(encoding="utf-8"))
    if doc.get("version") != 1:
        sys.exit(f"chamu JSON version no soportada: {doc.get('version')}")
    words = []
    for seg in doc.get("segments", []):
        for w in seg.get("words", []):
            s, e = round(w["start"] + offset, 3), round(w["end"] + offset, 3)
            if e > s:
                words.append({"word": w["w"], "start": s, "end": e})
    words.sort(key=lambda w: w["start"])
    out.write_text(json.dumps(words, ensure_ascii=False), encoding="utf-8")

    sils = [{"start": round(s["start"] + offset, 3),
             "end": round(s["end"] + offset, 3),
             "duration": round(s["end"] - s["start"], 3)}
            for s in doc.get("silences", [])]
    if sil_out:
        sil_out.write_text(json.dumps(sils, ensure_ascii=False), encoding="utf-8")

    print(f"WORDS={len(words)} SILENCES={len(sils)}")
    if words:
        print(f"SPAN={words[0]['start']:.1f}-{words[-1]['end']:.1f}s")
        print("SAMPLE=" + " ".join(w["word"] for w in words[:40]))


main()
