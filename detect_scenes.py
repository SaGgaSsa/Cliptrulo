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
SCALES = (0.5, 0.55, 0.6, 0.65, 0.7, 0.75, 0.8, 0.85, 0.9, 0.95, 1.0,
          1.05, 1.1, 1.15, 1.25)
SAT_THRESH = 25.0  # mediana de saturacion por bloques: FULL ~3-15, GRID ~45+
VAL_LO, VAL_HI = 60.0, 200.0  # las bandas grises son grises medios (~128)
BLOCKS = 6

# Pivot en fracciones del frame 960x540: la BARRA ENTERA de comentario
# (carita + "Agrega un comentario..." + "Publicar"), con textura de texto.
# Solo la franja oscura plana NO sirve: correlacion ~1 en cualquier fondo
# oscuro (TM_CCOEFF_NORMED falla en zonas planas).
PIVOT_FRAC = (520 / 960, 484 / 540, 790 / 960, 506 / 540)
# ROI donde buscar el pivot (panel comentarios, abajo-derecha).
ROI_FRAC = (0.45, 0.90, 1.0, 1.0)
# Banda lateral para GRID vs FULL (izquierda, mitad SUPERIOR: abajo puede
# haber overlays saturados como el badge WTF). Se divide en bloques y se
# usa la MEDIANA: overlays chicos (burbujas de chat, badges) ensucian 1-2
# bloques sin mover la mediana.
SIDE_FRAC = (0.02, 0.05, 0.25, 0.50)


def norm_frame(img):
    h, w = img.shape[:2]
    return cv2.resize(img, (int(w * H / h), H))


def build_template(video, t_ref, pivot_frac=None):
    """Recorta el pivot de un frame de referencia (debe ser escena REEL)."""
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "ref.png")
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
             "-ss", str(t_ref), "-i", video, "-frames:v", "1", p],
            check=True)
        img = norm_frame(cv2.imread(p))
    h, w = img.shape[:2]
    x0, y0, x1, y1 = pivot_frac or PIVOT_FRAC
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


def side_profile(img):
    """(mediana saturacion, mediana valor) por bloques de la banda lateral."""
    h, w = img.shape[:2]
    x0, y0, x1, y1 = SIDE_FRAC
    band = img[int(y0 * h):int(y1 * h), int(x0 * w):int(x1 * w)]
    hsv = cv2.cvtColor(band, cv2.COLOR_BGR2HSV)
    rows = np.array_split(hsv, BLOCKS, axis=0)
    sats = sorted(float(b[:, :, 1].mean()) for b in rows)
    vals = sorted(float(b[:, :, 2].mean()) for b in rows)
    m = BLOCKS // 2
    med = lambda a: (a[m - 1] + a[m]) / 2 if BLOCKS % 2 == 0 else a[m]
    return med(sats), med(vals)


def is_full(img):
    med_sat, med_val = side_profile(img)
    return med_sat < SAT_THRESH and VAL_LO <= med_val <= VAL_HI


def classify(img, templ, roi_frac=None, thresh=None, templ2=None):
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    h, w = g.shape[:2]
    x0, y0, x1, y1 = roi_frac or ROI_FRAC
    roi = g[int(y0 * h):int(y1 * h), int(x0 * w):int(x1 * w)]
    score = 0.0
    for t0 in [templ] + ([templ2] if templ2 is not None else []):
        for s in SCALES:
            t = cv2.resize(t0, None, fx=s, fy=s)
            if t.shape[0] > roi.shape[0] or t.shape[1] > roi.shape[1]:
                continue
            res = cv2.matchTemplate(roi, t, cv2.TM_CCOEFF_NORMED)
            score = max(score, float(res.max()))
    if score >= (thresh if thresh is not None else THRESH):
        return "REEL", score
    label = "FULL" if is_full(img) else "GRID"
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
    ap.add_argument("--start", type=float, default=0.0)
    ap.add_argument("--end", type=float, default=0.0)
    ap.add_argument("--t-ref", type=float, default=None,
                    help="segundo con barra de comentarios visible (escena REEL); "
                         "ignorado si se pasa --template")
    ap.add_argument("--template", default=None,
                    help="PNG del pivot (grises, escala H=540) reutilizable; "
                         "se genera una vez con --save-template")
    ap.add_argument("--save-template", default=None,
                    help="guarda el pivot recortado de --t-ref y sale")
    ap.add_argument("--out", default=None)
    ap.add_argument("--thumbs", default=None,
                    help="dir para guardar los thumbs de auditoria")
    ap.add_argument("--audit", action="store_true",
                    help="imprime score por segundo en vez de suavizar")
    ap.add_argument("--pivot", default=None,
                    help="fracs x0,y0,x1,y1 del pivot para --save-template "
                         "(default: PIVOT_FRAC del vivo)")
    ap.add_argument("--roi", default=None,
                    help="fracs x0,y0,x1,y1 donde buscar el pivot "
                         "(default: ROI_FRAC)")
    ap.add_argument("--thresh", type=float, default=None,
                    help="umbral de match del pivot (default: THRESH; "
                         "pivot chico y estable admite 0.8, el grande ~0.4)")
    ap.add_argument("--template2", default=None,
                    help="segundo PNG de pivot (otro tamano de modal); "
                         "REEL si alguno matchea")
    a = ap.parse_args()

    def parse_frac(s):
        return tuple(float(v) for v in s.split(","))

    pivot_frac = parse_frac(a.pivot) if a.pivot else None
    roi_frac = parse_frac(a.roi) if a.roi else None
    thresh = a.thresh if a.thresh is not None else THRESH

    if a.save_template:
        if a.t_ref is None:
            raise SystemExit("--save-template requiere --t-ref")
        templ = build_template(a.video, a.t_ref, pivot_frac)
        cv2.imwrite(a.save_template, templ)
        print("OK template", a.save_template, templ.shape)
        return

    if a.template:
        templ = cv2.imread(a.template, cv2.IMREAD_GRAYSCALE)
        if templ is None:
            raise SystemExit(f"no se pudo leer template: {a.template}")
    else:
        if a.t_ref is None:
            raise SystemExit("se requiere --t-ref o --template")
        templ = build_template(a.video, a.t_ref, pivot_frac)
    templ2 = None
    if a.template2:
        templ2 = cv2.imread(a.template2, cv2.IMREAD_GRAYSCALE)
        if templ2 is None:
            raise SystemExit(f"no se pudo leer template2: {a.template2}")
    keep = a.thumbs or tempfile.mkdtemp(prefix="scenes_")
    thumbs = extract_thumbs(a.video, a.start, a.end, keep)

    raw = []
    for i, p in enumerate(thumbs):
        img = cv2.imread(p)
        lab, score = classify(img, templ, roi_frac, thresh, templ2)
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
