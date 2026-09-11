"""Valida picks manuales del agente y arma montages.json (sin IA).

picks.json: {"clips": [{"rank": 1,
  "item": {"start": 649.0, "end": 740.0, "kind": "visionado",
           "score": 85, "summary": "..."},
  "spans": [{"start": 649.8, "end": 678.8, "role": "presentacion"}, ...]}]}
Roles validos: presentacion | mejor_reaccion | comentarios.

Valida: snap a palabras, spans monotonos, 2-3 spans, total<=59 (si pasa,
falla y el agente recorta), total<15 (extiende ultimo span), cortes cerca
de silencios reales (aviso). Conserva ranks no mencionados del montages
existente (ej. clip_02 intacto).

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

from openshorts_common import MAX_CLIP_S, MIN_CLIP_S  # noqa: E402

ROLES = ("presentacion", "mejor_reaccion", "comentarios")


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
        assert 2 <= len(spans) <= 3, f"rank {p['rank']}: {len(spans)} spans (2-3)"
        assert all(s["role"] in ROLES for s in spans), spans
        out = []
        for sp in spans:
            ns, ne = snap_clip_to_words(sp["start"], sp["end"], flat, it["end"],
                                        min_duration=2.0, max_duration=30.0)
            out.append({"start": ns, "end": ne, "role": sp["role"]})
        out.sort(key=lambda s: s["start"])
        for i in range(1, len(out)):
            out[i]["start"] = max(out[i]["start"], out[i - 1]["end"])
        out = [s for s in out if s["end"] > s["start"]]
        total = round(sum(s["end"] - s["start"] for s in out), 3)
        if total > MAX_CLIP_S:
            raise SystemExit(f"FAIL rank {p['rank']}: total {total:.1f}s > 59s, "
                             f"recorta presentacion o comentarios y reintenta")
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
