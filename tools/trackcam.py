"""Rastrea la caja de la webcam por borde azul (seeks accurate) cada N segundos.

Uso:
  python tools/trackcam.py <video> [--step 5] [--out dbg.png]
Imprime: t + caja (x0 y0 x1 y1 en 1920x1080) o NONE. Guarda tira debug.
Tambien importable: grab(video, t, d), find_cyan_boxes(img), scan(video, ts).
"""
import argparse
import os
import subprocess
import sys
import tempfile

import cv2
import numpy as np

W, H = 1920, 1080


def grab(video, t, d):
    p = os.path.join(d, f"f{int(t * 10):06d}.png")
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                    "-i", video, "-ss", str(t), "-frames:v", "1", p],
                   check=True)
    img = cv2.imread(p)
    if img is None:
        raise SystemExit(f"no salio frame t={t}")
    if (img.shape[1], img.shape[0]) != (W, H):
        img = cv2.resize(img, (W, H))
    return img


def find_cyan_boxes(img):
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array([85, 100, 80]),
                       np.array([112, 255, 255]))
    mask = cv2.dilate(mask, np.ones((5, 5), np.uint8), iterations=2)
    cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL,
                               cv2.CHAIN_APPROX_SIMPLE)
    boxes = []
    for c in cnts:
        x, y, w, h = cv2.boundingRect(c)
        if w > 120 and h > 120 and w < 900 and h < 900:
            boxes.append((x, y, x + w, y + h))
    # solo mitad derecha (la cam vive a la derecha)
    boxes = [b for b in boxes if b[0] > W // 3]
    boxes.sort(key=lambda b: (b[2] - b[0]) * (b[3] - b[1]), reverse=True)
    return boxes


def scan(video, ts, debug=False):
    """Barrido compartiendo tempdir: [(t, boxes, img|None)]."""
    out = []
    with tempfile.TemporaryDirectory() as d:
        for t in ts:
            img = grab(video, t, d)
            out.append((t, find_cyan_boxes(img), img if debug else None))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--step", type=float, default=5.0)
    ap.add_argument("--t0", type=float, default=1.0)
    ap.add_argument("--t1", type=float, default=0.0)
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", a.video], capture_output=True, text=True)
    dur = float(probe.stdout.strip())
    t1 = a.t1 or (dur - 0.5)
    ts = [round(x, 1) for x in np.arange(a.t0, t1, a.step)]
    thumbs = []
    for t, boxes, img in scan(video=a.video, ts=ts, debug=bool(a.out)):
        tag = "NONE" if not boxes else " ".join(
            f"({x0},{y0},{x1},{y1})" for x0, y0, x1, y1 in boxes[:2])
        print(f"t={t:6.1f} {tag}", flush=True)
        if a.out:
            dbg = img.copy()
            for x0, y0, x1, y1 in boxes[:2]:
                cv2.rectangle(dbg, (x0, y0), (x1, y1), (0, 255, 0), 4)
            thumbs.append(cv2.resize(dbg, (480, 270)))
    if a.out and thumbs:
        rows = [np.hstack(thumbs[i:i + 4])
                for i in range(0, len(thumbs), 4)]
        wmax = max(r.shape[1] for r in rows)
        pad = [cv2.copyMakeBorder(r, 0, 0, 0, wmax - r.shape[1],
                                  cv2.BORDER_CONSTANT) for r in rows]
        cv2.imwrite(a.out, np.vstack(pad))
        print("OK", a.out)


if __name__ == "__main__":
    main()
