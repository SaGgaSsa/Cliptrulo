"""Muestra HSV de puntos de una imagen. Uso: probecolor.py <img> x,y x,y ..."""
import sys

import cv2
import numpy as np

img = cv2.imread(sys.argv[1])
hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
h, w = img.shape[:2]
for pt in sys.argv[2:]:
    fx, fy = (float(v) for v in pt.split(","))
    x, y = int(fx * w), int(fy * h)
    x0, x1 = max(0, x - 2), min(w, x + 3)
    y0, y1 = max(0, y - 2), min(h, y + 3)
    m = hsv[y0:y1, x0:x1].reshape(-1, 3).mean(axis=0)
    print(pt, "->", tuple(round(float(v), 1) for v in m))
