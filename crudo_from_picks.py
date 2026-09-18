"""Valida picks de crudo continuo y arma clips.json (sin IA, sin edicion).

picks.json: {"clips": [{"rank": 1, "start": 525.2, "end": 632.0,
  "score": 72, "hook": "...", "summary": "..."}]}
Un unico tramo continuo por clip, con pausas y silencios intactos.

Valida: bordes fuera de palabra (snap a palabra completa, corte en mitad de
silencio), duracion 60-180s (falla si no, el agente ajusta), minimo 3 clips.
Avisa si un corte cae lejos de silencios verificados. Conserva ranks no
mencionados del clips.json existente.

Uso:
  python crudo_from_picks.py --words downloads/X_words.json \
      --silences downloads/X_silences.json --items output/.../items.json \
      --picks output/.../picks.json --clips output/.../clips.json
"""
import argparse
import json
from pathlib import Path

from openshorts_common import CRUDO_MAX_S, CRUDO_MIN_S

EPS = 0.001  # cortes 1ms antes del borde: el .srt incluye palabras con start <= fin


def fix_start(t, words):
    """Si el inicio cae dentro de una palabra, retrocede a su inicio."""
    t = round(t, 3)
    for w in words:
        if w["start"] < t < w["end"]:
            return round(w["start"], 3)
    return t


def fix_end(t, words):
    """Si el fin cae dentro de una palabra o justo en su borde inicial, la
    incluye ENTERA y retrocede 1ms para no alcanzar la palabra siguiente."""
    t = round(t, 3)
    hit = [w for w in words if w["start"] <= t < w["end"] or w["start"] == t]
    if hit:
        t = round(max(w["end"] for w in hit), 3)
    return round(t - EPS, 3)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--words", required=True)
    ap.add_argument("--silences", default="")
    ap.add_argument("--items", required=True)
    ap.add_argument("--picks", required=True)
    ap.add_argument("--clips", required=True)
    args = ap.parse_args()

    words = json.loads(Path(args.words).read_text(encoding="utf-8"))
    sils = []
    if args.silences:
        sils = json.loads(Path(args.silences).read_text(encoding="utf-8"))
    items = json.loads(Path(args.items).read_text(encoding="utf-8"))["items"]
    picks = json.loads(Path(args.picks).read_text(encoding="utf-8"))["clips"]
    keep = {}
    if Path(args.clips).exists():
        for m in json.loads(Path(args.clips).read_text(encoding="utf-8"))["clips"]:
            keep[m["rank"]] = m

    def near_silence(t):
        return any(s["start"] - 1.0 <= t <= s["end"] + 1.0 for s in sils)

    if len(picks) + len([r for r in keep if r not in {p["rank"] for p in picks}]) < 3:
        print("  AVISO: se piden minimo 3 clips por seccion")

    for p in picks:
        assert "spans" not in p, (
            f"rank {p['rank']}: formato montaje no admitido en crudo "
            "(usar start/end unicos, sin spans)")
        ns, ne = fix_start(p["start"], words), fix_end(p["end"], words)
        assert ne > ns, f"rank {p['rank']}: rango vacio tras snap"
        total = round(ne - ns, 3)
        if total < CRUDO_MIN_S:
            raise SystemExit(f"FAIL rank {p['rank']}: total {total:.1f}s < "
                             f"{CRUDO_MIN_S:.0f}s, ampliar y reintentar")
        if total > CRUDO_MAX_S:
            raise SystemExit(f"FAIL rank {p['rank']}: total {total:.1f}s > "
                             f"{CRUDO_MAX_S:.0f}s, recortar y reintentar")
        for edge in (ns, ne):
            if sils and not near_silence(edge):
                print(f"  AVISO rank {p['rank']}: corte en {edge:.1f}s "
                      f"lejos de silencios verificados")
        keep[p["rank"]] = {"rank": p["rank"], "start": ns, "end": ne,
                           "total": total, "score": p.get("score", 0),
                           "hook": p.get("hook", ""),
                           "summary": p.get("summary", "")}
        print(f"OK rank {p['rank']}: total={total:.1f}s [{ns:.1f}-{ne:.1f}]")

    items_by_range = {(round(i["start"], 1), round(i["end"], 1)) for i in items}
    for p in picks:
        if "item" in p and isinstance(p["item"], dict):
            key = (round(p["item"]["start"], 1), round(p["item"]["end"], 1))
            if key not in items_by_range:
                print(f"  AVISO rank {p['rank']}: item fuera de items.json, agregalo")

    out = {"clips": [keep[r] for r in sorted(keep)]}
    Path(args.clips).write_text(json.dumps(out, indent=2, ensure_ascii=False),
                                encoding="utf-8")
    print(f"OK {args.clips}")


if __name__ == "__main__":
    main()
