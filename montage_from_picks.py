"""Valida picks manuales del agente y arma montages.json (sin IA).

picks.json: {"clips": [{"rank": 1,
  "item": {"start": 649.0, "end": 740.0, "kind": "visionado",
           "score": 85, "summary": "..."},
  "spans": [{"start": 649.8, "end": 678.8, "role": "presentacion"}, ...]}]}
Roles validos: presentacion | mejor_reaccion | comentarios (orden libre).

Valida: snap a palabras, spans monotonos, 1-6 spans por clip (momentos con
contenido; los silencios/baches se saltean y el montaje los elimina),
total<=180s (tope Shorts 3min; si pasa, falla y el agente recorta),
total<15 (extiende ultimo span), cola de ~2s tras la ultima palabra
(hasta la proxima palabra o fin del item, lo que llegue antes), cortes cerca
de silencios reales (aviso). Conserva ranks no mencionados del montages
existente.

Uso:
  python montage_from_picks.py --words downloads/X_words.json \
      --silences downloads/X_silences.json --items output/.../items.json \
      --picks output/.../picks.json --montages output/.../montages.json
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "vendor" / "openshorts"))
from clip_selection import snap_clip_to_words  # noqa: E402

from openshorts_common import MIN_CLIP_S  # noqa: E402

ROLES = ("presentacion", "mejor_reaccion", "comentarios")
MAX_SHORT_S = 180.0  # YouTube Shorts admite hasta 3 min
TAIL_S = 2.5  # cola tras la ultima palabra aunque haya silencio
EPS = 0.001  # los cortes van 1ms antes del borde: el .srt incluye palabras
# con start <= fin, asi un corte justo en un borde mete subtitulo sin audio


def fix_start(t, words):
    """Si el inicio cae dentro de una palabra, retrocede a su inicio."""
    t = round(t, 3)
    for w in words:
        if w["start"] < t < w["end"]:
            return round(w["start"], 3)
    return t


def fix_end(t, words, hard=False):
    """Lleva el corte a mitad de silencio: si cae dentro de una palabra o
    justo en su borde inicial, la incluye ENTERA (hasta la siguiente palabra,
    como pide el criterio) y retrocede 1ms para que el .srt no alcance la
    palabra siguiente. Con hard=True (corte de split, no cola final) el fin
    queda exacto en el fin de palabra sin extenderse a la siguiente."""
    t = round(t, 3)
    if hard:
        hit = [w for w in words if w["start"] < t <= w["end"]]
    else:
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
    ap.add_argument("--montages", required=True)
    args = ap.parse_args()

    words = json.loads(Path(args.words).read_text(encoding="utf-8"))
    flat = [{"w": w["word"], "s": w["start"], "e": w["end"]} for w in words]
    sils = []
    if args.silences:
        sils = json.loads(Path(args.silences).read_text(encoding="utf-8"))
    items = json.loads(Path(args.items).read_text(encoding="utf-8"))["items"]
    picks = json.loads(Path(args.picks).read_text(encoding="utf-8"))["clips"]
    keep = {}
    if Path(args.montages).exists():
        for m in json.loads(Path(args.montages).read_text(encoding="utf-8"))["montages"]:
            keep[m["rank"]] = m

    def near_silence(t):
        return any(s["start"] - 1.0 <= t <= s["end"] + 1.0 for s in sils)

    for p in picks:
        it, spans = p["item"], [dict(s) for s in p["spans"]]
        assert it["kind"] in ("presentacion", "visionado", "reaccion", "comentarios"), it
        assert 1 <= len(spans) <= 6, f"rank {p['rank']}: {len(spans)} spans (1-6)"
        assert all(s["role"] in ROLES for s in spans), spans
        out = []
        for sp in spans:
            ns, ne = snap_clip_to_words(sp["start"], sp["end"], flat, it["end"],
                                        min_duration=2.0, max_duration=600.0)
            out.append({"start": fix_start(ns, words),
                        "end": fix_end(ne, words, hard=sp.get("hard", False)),
                        "role": sp["role"]})
        out.sort(key=lambda s: s["start"])
        for i in range(1, len(out)):
            if out[i]["start"] <= out[i - 1]["end"]:
                out[i - 1]["end"] = round(out[i]["start"] - EPS, 3)
        out = [s for s in out if s["end"] > s["start"]]
        # Cola: ~2s despues de la ultima palabra (hasta la proxima o fin de item).
        # No se aplica si el ultimo span es corte de split ("hard": true).
        if not spans[-1].get("hard", False):
            nxt = min([w["start"] for w in words if w["start"] > out[-1]["end"]] + [it["end"]])
            out[-1]["end"] = fix_end(min(out[-1]["end"] + TAIL_S, nxt, it["end"]), words)
        total = round(sum(s["end"] - s["start"] for s in out), 3)
        if total > MAX_SHORT_S:
            raise SystemExit(f"FAIL rank {p['rank']}: total {total:.1f}s > 180s, "
                             f"recorta y reintenta")
        if total < MIN_CLIP_S:
            out[-1]["end"] = round(out[-1]["end"] + (MIN_CLIP_S - total), 3)
            total = MIN_CLIP_S
            print(f"  nota rank {p['rank']}: extendido a 15s")
        for s in out:
            for edge in (s["start"], s["end"]):
                if sils and not near_silence(edge):
                    print(f"  AVISO rank {p['rank']}: corte en {edge:.1f}s "
                          f"lejos de silencios verificados")
        keep[p["rank"]] = {"rank": p["rank"], "item": it, "spans": out, "total": total}
        print(f"OK rank {p['rank']}: total={total:.1f}s spans={len(out)}")

    items_by_range = {(round(i["start"], 1), round(i["end"], 1)) for i in items}
    for p in picks:
        key = (round(p["item"]["start"], 1), round(p["item"]["end"], 1))
        if key not in items_by_range:
            print(f"  AVISO rank {p['rank']}: item fuera de items.json, agregalo")

    mon = {"montages": [keep[r] for r in sorted(keep)]}
    Path(args.montages).write_text(json.dumps(mon, indent=2, ensure_ascii=False),
                                   encoding="utf-8")
    print(f"OK {args.montages}")


if __name__ == "__main__":
    main()
