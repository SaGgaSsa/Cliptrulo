"""Tira de verificacion por clip: 3 full frames (arriba) + 5 crops cam (abajo).

Uso:
  python tools/camstrip.py <video> <out.png> --full 2,30,57 --cam 2,15,30,45,57
Cam standard EP2: left=1632 top=48 right=51 bottom=687 (fuente 1920x1080).
"""
import argparse
import os
import subprocess
import sys
import tempfile

import cv2
import numpy as np

CAM = (1632, 48, 1920 - 51, 1080 - 687)  # x0,y0,x1,y1
FH = 360  # altura de fila


def grab(video, t, d):
    p = os.path.join(d, f"f{t}.png")
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                    "-ss", str(t), "-i", video, "-frames:v", "1", p],
                   check=True)
    img = cv2.imread(p)
    if img is None:
        raise SystemExit(f"no salio frame t={t} de {video}")
    return img


def scale_h(img, h):
    w = int(img.shape[1] * h / img.shape[0])
    return cv2.resize(img, (w, h))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("out")
    ap.add_argument("--full", default="2,30,57")
    ap.add_argument("--cam", default="2,15,30,45,57")
    a = ap.parse_args()
    tf = [float(x) for x in a.full.split(",")]
    tc = [float(x) for x in a.cam.split(",")]
    with tempfile.TemporaryDirectory() as d:
        row1 = np.hstack([scale_h(grab(a.video, t, d), FH) for t in tf])
        x0, y0, x1, y1 = CAM
        row2 = np.hstack([scale_h(grab(a.video, t, d)[y0:y1, x0:x1], FH)
                          for t in tc])
    W = max(row1.shape[1], row2.shape[1])
    pad = lambda r: cv2.copyMakeBorder(r, 0, 0, 0, W - r.shape[1],
                                       cv2.BORDER_CONSTANT, value=(0, 0, 0))
    cv2.imwrite(a.out, np.vstack([pad(row1), pad(row2)]))
    print("OK", a.out)


main()
