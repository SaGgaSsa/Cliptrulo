"""Detecta geometria y switches de la webcam y emite segmentos V2 (sin valores a mano).

Metodo: barrido grueso (borde azul, ver trackcam.py) + clasificacion
automatica de tamanos (1 o 2 clusters por corte del mayor gap de areas;
NONE si no hay caja) + bisect de cada borde a --prec segundos. La caja de
cada geometria = mediana de sus observaciones (robusta a falsos positivos).

Uso:
  python tools/camspec.py <video> [--step 3] [--prec 0.5]
  python tools/camspec.py <video> --update specs/ep2_wtf.json --clip 03
Imprime el JSON de v2 y, con --update, lo guarda en el spec del clip.
"""
import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from trackcam import find_cyan_boxes, grab  # noqa: E402

AREA_RATIO_MIN = 1.5  # bajo esto, un solo cluster (ruido, no 2 geometrias)


def duration(video):
    p = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", video], capture_output=True, text=True)
    return float(p.stdout.strip())


def area(b):
    return (b[2] - b[0]) * (b[3] - b[1])


def split_clusters(areas):
    """Devuelve mediana de area por cluster (1 o 2). Sin constantes de tamano:
    dos clusters solo si el mayor gap relativo supera AREA_RATIO_MIN."""
    if not areas:
        return []
    s = sorted(areas)
    if len(s) < 2:
        return [float(s[0])]
    gaps = [(s[i + 1] / s[i] if s[i] else 0.0, i) for i in range(len(s) - 1)]
    ratio, idx = max(gaps)
    if ratio < AREA_RATIO_MIN:
        return [float(sum(s) / len(s))]
    a = s[:idx + 1]
    b = s[idx + 1:]
    med = lambda v: float(sorted(v)[len(v) // 2])
    return [med(a), med(b)]


def label_of(box, medians):
    if box is None:
        return "none"
    if len(medians) == 1:
        return "cam"  # una sola geometria: el ruido de +-2px no es un switch
    i = min(range(len(medians)), key=lambda k: abs(area(box) - medians[k]))
    return ("small", "large")[i]


def median_box(boxes):
    xs = sorted(b[0] for b in boxes)
    ys = sorted(b[1] for b in boxes)
    x1 = sorted(b[2] for b in boxes)
    y1 = sorted(b[3] for b in boxes)
    m = len(boxes) // 2
    return [xs[m], ys[m], x1[m], y1[m]]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--step", type=float, default=3.0)
    ap.add_argument("--prec", type=float, default=0.5)
    ap.add_argument("--update", default=None)
    ap.add_argument("--clip", default=None)
    a = ap.parse_args()

    dur = duration(a.video)
    coarse = []
    ts = [round(1.0 + i * a.step, 1)
          for i in range(int((dur - 1.5) / a.step) + 1)]
    # muestra final obligatoria: si no, un estado distinto al cierre
    # (alerta que tapa la cam) queda extendido hasta dur
    if not ts or dur - 0.5 - ts[-1] > a.prec:
        ts.append(round(dur - 0.5, 1))
    with tempfile.TemporaryDirectory() as d:
        for t in ts:
            boxes = find_cyan_boxes(grab(a.video, t, d))
            coarse.append((t, boxes[0] if boxes else None))

        medians = split_clusters([area(b) for _, b in coarse if b])
        print(f"clusters areas={sorted(round(m) for m in medians)}",
              flush=True)
        labs = [(t, label_of(b, medians), b) for t, b in coarse]
        for t, lab, b in labs:
            print(f"t={t:6.1f} {lab:6s} {b}", flush=True)

        # bordes entre labels distintos -> bisect a --prec
        bounds = []  # (tiempo, nuevo_label)
        for (t0, l0, _), (t1, l1, _) in zip(labs, labs[1:]):
            if l0 == l1:
                continue

            def lab_at(t):
                bx = find_cyan_boxes(grab(a.video, t, d))
                return label_of(bx[0] if bx else None, medians)

            lo, hi = t0, t1
            while hi - lo > a.prec:
                mid = round((lo + hi) / 2, 1)
                if lab_at(mid) == l0:
                    lo = mid
                else:
                    hi = mid
            bounds.append((round(hi / a.prec) * a.prec, l1))
            print(f"switch {l0}->{l1} t={bounds[-1][0]}", flush=True)

    # segmentos: [0..b1) label0, [b1..b2), ..., [bn..dur)
    runs = []
    start, cur = 0.0, labs[0][1]
    for bt, nl in bounds:
        runs.append((start, bt, cur))
        start, cur = bt, nl
    runs.append((start, round(dur, 1), cur))

    by_label = {}
    for _, lab, b in labs:
        if b:
            by_label.setdefault(lab, []).append(b)
    boxes = {lab: median_box(v) for lab, v in by_label.items()}
    v2 = [{"t0": t0, "t1": t1, "geom": lab,
           "box": boxes.get(lab)} for t0, t1, lab in runs]
    print(json.dumps(v2, indent=1))
    if a.update:
        if not a.clip:
            raise SystemExit("--update requiere --clip NN")
        spec = json.loads(Path(a.update).read_text(encoding="utf-8"))
        for c in spec["clips"]:
            if c["nn"] == a.clip:
                c["v2"] = v2
                break
        else:
            raise SystemExit(f"clip {a.clip} no esta en {a.update}")
        Path(a.update).write_text(json.dumps(spec, indent=1,
                                             ensure_ascii=False),
                                  encoding="utf-8")
        print(f"OK {a.update} clip {a.clip}")


main()
