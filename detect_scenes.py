"""Detecta escenas de layout en un rango del vivo, sin mirar el video.

Clases:
  REEL  - modal de reel: video al centro + comentarios a la derecha.
          Pivot: barra inferior "Agrega un comentario... / Publicar".
  FULL  - video vertical centrado a pantalla completa (bandas grises).
  GRID  - resto (perfil, grilla, navegador): contenido a lo ancho.

Metodo: 1 fps en 960x540 + template matching (TM_CCOEFF_NORMED) del pivot
en ROI inferior-derecha + histeresis de 2s. GRID vs FULL por saturacion
de la franja lateral (bandas grises = sin saturacion).

Uso:
  python detect_scenes.py --video downloads/EP2_relatando.mp4 \
      --start 693.6 --end 808.6 --out output/ep2/relatando/scenes_01.json
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile

import cv2
import numpy as np

H = 540  # altura normalizada: template y frames siempre a la misma escala
FPS = 1
HYST = 2  # segundos consecutivos para confirmar cambio de escena
MIN_SEG = 2.0  # segmentos mas cortos se fusionan con el vecino mayor
THRESH = 0.40  # REEL reales ~0.55, resto <=0.26 (CCOEFF multiescala)
SCALES = (0.7, 0.75, 0.8, 0.85, 0.9, 0.95, 1.0, 1.05, 1.1, 1.15, 1.25)
SAT_THRESH = 20.0  # FULL ~3, GRID ~35 (banda x 0.02-0.25)

# Pivot en fracciones del frame 960x540: la BARRA ENTERA de comentario
# (carita + "Agrega un comentario..." + "Publicar"), con textura de texto.
# Solo la franja oscura plana NO sirve: correlacion ~1 en cualquier fondo
# oscuro (TM_CCOEFF_NORMED falla en zonas planas).
PIVOT_FRAC = (520 / 960, 484 / 540, 790 / 960, 506 / 540)
# ROI donde buscar el pivot (panel comentarios, abajo-derecha).
ROI_FRAC = (0.45, 0.90, 1.0, 1.0)
# Banda lateral para GRID vs FULL (izquierda, mitad vertical, ancha para
# cruzar el margen gris: FULL todo gris, GRID con contenido colorido).
SIDE_FRAC = (0.02, 0.25, 0.25, 0.75)


def norm_frame(img):
    h, w = img.shape[:2]
    return cv2.resize(img, (int(w * H / h), H))


def build_template(video, t_ref):
    """Recorta el pivot de un frame de referencia (debe ser escena REEL)."""
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "ref.png")
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
             "-ss", str(t_ref), "-i", video, "-frames:v", "1", p],
            check=True)
        img = norm_frame(cv2.imread(p))
    h, w = img.shape[:2]
    x0, y0, x1, y1 = PIVOT_FRAC
    return cv2.cvtColor(
        img[int(y0 * h):int(y1 * h), int(x0 * w):int(x1 * w)],
        cv2.COLOR_BGR2GRAY)


def extract_thumbs(video, start, end, outdir):
    os.makedirs(outdir, exist_ok=True)
    pat = os.path.join(outdir, "t%04d.png")
    # Fuente CFR: select por conteo (cada 30 frames = 1.000s exacto).
    # El filtro fps= tiene buckets float y puede correr +-1s segun el run;
    # con select el thumb i <-> start+i es deterministico entre runs.
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
         "-i", video, "-ss", str(start),
         "-t", str(end - start),
         "-vf", "select='not(mod(n,30))',scale=-1:540",
         "-fps_mode", "passthrough", pat], check=True)
    files = sorted(f for f in os.listdir(outdir) if f.startswith("t"))
    return [os.path.join(outdir, f) for f in files]


def side_saturation(img):
    h, w = img.shape[:2]
    x0, y0, x1, y1 = SIDE_FRAC
    side = img[int(y0 * h):int(y1 * h), int(x0 * w):int(x1 * w)]
    hsv = cv2.cvtColor(side, cv2.COLOR_BGR2HSV)
    return float(hsv[:, :, 1].mean())


def classify(img, templ):
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    h, w = g.shape[:2]
    x0, y0, x1, y1 = ROI_FRAC
    roi = g[int(y0 * h):int(y1 * h), int(x0 * w):int(x1 * w)]
    score = 0.0
    for s in SCALES:
        t = cv2.resize(templ, None, fx=s, fy=s)
        if t.shape[0] > roi.shape[0] or t.shape[1] > roi.shape[1]:
            continue
        res = cv2.matchTemplate(roi, t, cv2.TM_CCOEFF_NORMED)
        score = max(score, float(res.max()))
    if score >= THRESH:
        return "REEL", score
    label = "FULL" if side_saturation(img) < SAT_THRESH else "GRID"
    return label, score


def smooth(labels):
    """Histeresis: el cambio rige solo con HYST segundos consecutivos."""
    out = [labels[0]]
    pending = None
    count = 0
    for lab in labels[1:]:
        cur = out[-1]
        if lab == cur:
            pending, count = None, 0
            out.append(cur)
        elif lab == pending:
            count += 1
            out.append(cur if count < HYST else lab)
            if count >= HYST:
                pending, count = None, 0
                # reescribir los pendientes ya emitidos
                for i in range(1, HYST):
                    out[-1 - i] = lab
        else:
            pending, count = lab, 1
            out.append(cur)
    return out


def to_segments(labels, start):
    segs, s, cur = [], start, labels[0]
    for i, lab in enumerate(labels[1:], 1):
        if lab != cur:
            segs.append({"start": round(s, 1), "end": round(start + i, 1),
                         "label": cur})
            s, cur = start + i, lab
    segs.append({"start": round(s, 1), "end": round(start + len(labels), 1),
                 "label": cur})
    # fusionar segmentos < MIN_SEG con el vecino mas largo
    merged = [segs[0]]
    for sg in segs[1:]:
        if sg["end"] - sg["start"] < MIN_SEG and merged:
            prev = merged[-1]
            if prev["end"] - prev["start"] >= sg["end"] - sg["start"]:
                prev["end"] = sg["end"]
            else:
                merged[-1] = {"start": prev["start"], "end": sg["end"],
                              "label": sg["label"]}
        else:
            merged.append(sg)
    return merged


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--start", type=float, required=True)
    ap.add_argument("--end", type=float, required=True)
    ap.add_argument("--t-ref", type=float, required=True,
                    help="segundo con barra de comentarios visible (escena REEL)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--thumbs", default=None,
                    help="dir para guardar los thumbs de auditoria")
    ap.add_argument("--audit", action="store_true",
                    help="imprime score por segundo en vez de suavizar")
    a = ap.parse_args()

    templ = build_template(a.video, a.t_ref)
    keep = a.thumbs or tempfile.mkdtemp(prefix="scenes_")
    thumbs = extract_thumbs(a.video, a.start, a.end, keep)

    raw = []
    for i, p in enumerate(thumbs):
        img = cv2.imread(p)
        lab, score = classify(img, templ)
        raw.append((a.start + i, lab, round(score, 3)))

    if a.audit:
        for t, lab, score in raw:
            print(f"{t:8.1f} {lab:5s} {score:.3f}")
        return

    labels = smooth([r[1] for r in raw])
    segs = to_segments(labels, a.start)
    # tiempos relativos al inicio del rango (el clip) + absolutos
    for sg in segs:
        sg["rel_start"] = round(sg["start"] - a.start, 1)
        sg["rel_end"] = round(sg["end"] - a.start, 1)
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump({"video": a.video, "range": [a.start, a.end],
                   "scenes": segs}, f, indent=1, ensure_ascii=False)
    for sg in segs:
        print(f"{sg['label']:5s} {sg['start']:8.1f}-{sg['end']:8.1f} "
              f"(rel {sg['rel_start']}-{sg['rel_end']})")
    print("OK", a.out)


if __name__ == "__main__":
    sys.exit(main())
