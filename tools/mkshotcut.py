"""Genera proyectos Shotcut verticales 1080x1920 para los clips wtf.

Replica la estructura verificada de relatando/clip_0*_shotcut.mlt:
V1 = crop px + affine full distort=0 (partido por escena), V2-cam = crop
caja + affine PiP 760 20 300 437 distort=0 (partido por geometria STD/BIG),
compositing qtblend default. Hash = MD5(primer+ultimo MB) como Shotcut.

Uso:
  python tools/mkshotcut.py   # genera output/ep2/wtf/clip_NN_shotcut.mlt
"""
import hashlib
import json
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "output" / "ep2" / "wtf"
FPS = 30

V1_FULL = {"rect": "0 0 1080 1920", "distort": "0"}
PIP = {"rect": "760 20 300 437", "distort": "0"}

# (clip, Nframes, nota, [V1 segs (f0,f1,crop)], [V2 segs (f0,f1,crop)|None])
C = {"central": (656, 0, 656, 0)}
STD = (1632, 48, 51, 687)
BIG = (1498, 308, 51, 304)
VID = {
    "c01": (555, 195, 585, 250),
    "c02": (400, 195, 690, 245),
    "c03a": (660, 60, 700, 80),
    "c03b": (780, 55, 540, 60),
    "c04": (750, 55, 600, 60),
    "c567": (510, 55, 855, 60),
}
CLIPS = [
    # (nn, dur_s, nota, v1, v2)
    ("01", 58.83, "Intendente IA (56s): V1 video + PiP STD->BIG",
     [(0, 1763, VID["c01"])],
     [(0, 1574, STD), (1575, 1763, BIG)]),
    ("02", 51.57, "Bardo Cacerta (51s): V1 video + PiP STD (alerta final)",
     [(0, 1545, VID["c02"])],
     [(0, 1484, STD)]),
    ("03", 53.77, "Hombre arana (54s): V1 video->video2 + PiP BIG->STD",
     [(0, 1484, VID["c03a"]), (1485, 1611, VID["c03b"])],
     [(0, 1484, BIG), (1485, 1611, STD)]),
    ("04", 58.70, "Percha ganadora (59s): V1 video + PiP STD->BIG",
     [(0, 1759, VID["c04"])],
     [(0, 1244, STD), (1245, 1759, BIG)]),
    ("05", 46.93, "Mujeres sonidos (47s): V1 central->video + PiP STD->BIG",
     [(0, 179, C["central"]), (180, 1406, VID["c567"])],
     [(0, 854, STD), (855, 1406, BIG)]),
    ("06", 58.87, "Nena tercer lugar (59s): V1 video->central + PiP BIG",
     [(0, 1529, VID["c567"]), (1530, 1764, C["central"])],
     [(0, 1764, BIG)]),
    ("07", 56.47, "Pato elemento (56s): V1 video->central + PiP BIG",
     [(0, 869, VID["c567"]), (870, 1692, C["central"])],
     [(0, 1692, BIG)]),
]


def file_hash(p: Path) -> str:
    size = p.stat().st_size
    d = hashlib.md5(usedforsecurity=False)
    with p.open("rb") as h:
        if size < 2 * 1024 * 1024:
            for ch in iter(lambda: h.read(1024 * 1024), b""):
                d.update(ch)
        else:
            d.update(h.read(1024 * 1024))
            h.seek(-1024 * 1024, 2)
            d.update(h.read(1024 * 1024))
    return d.hexdigest()


def prop(parent, name, value):
    e = ET.SubElement(parent, "property", name=name)
    e.text = str(value)
    return e


def uid(prefix):
    import secrets
    return f"{prefix}_{secrets.token_hex(6)}"


def producer(doc, pid, mp4, hsh, n, crop, affine, is_cam):
    p = ET.SubElement(doc, "producer", {"id": pid, "in": "0",
                                        "out": str(n - 1)})
    prop(p, "length", n)
    prop(p, "eof", "pause")
    prop(p, "resource", mp4)
    prop(p, "mlt_service", "avformat-novalidate")
    prop(p, "shotcut:caption", Path(mp4).name)
    prop(p, "shotcut:hash", hsh)
    prop(p, "seekable", 1)
    prop(p, "shotcut:skipConvert", 1)
    f = ET.SubElement(p, "filter", id=uid("filter"))
    prop(f, "mlt_service", "crop")
    for k, v in zip(("left", "top", "right", "bottom"),
                    (crop[0], crop[1], crop[2], crop[3])):
        prop(f, k, v)
    f = ET.SubElement(p, "filter", id=uid("filter"))
    prop(f, "mlt_service", "affine")
    if is_cam:
        prop(f, "shotcut:filter", "affineSizePosition")
    prop(f, "background", "colour:0")
    prop(f, "rect", affine["rect"])
    prop(f, "transition.distort", affine["distort"])
    prop(f, "transition.fill", "1")
    prop(f, "transition.rect", affine["rect"])
    return p


def build(nn, dur, nota, v1segs, v2segs):
    n = round(dur * FPS)
    mp4 = f"C:/Users/saggassa/Desktop/cliptrulo/output/ep2/wtf/clip_{nn}.mp4"
    hsh = file_hash(OUT / f"clip_{nn}.mp4")
    doc = ET.Element("mlt", LC_NUMERIC="C", version="7.40.0",
                     title="Shotcut version 26.6.25", producer="tractor0",
                     root="C:/Users/saggassa/Desktop/cliptrulo/output/ep2/wtf")
    ET.SubElement(doc, "profile", description="1080x1920 30.000 fps",
                  width="1080", height="1920", progressive="1",
                  sample_aspect_num="1", sample_aspect_den="1",
                  display_aspect_num="9", display_aspect_den="16",
                  frame_rate_num="30", frame_rate_den="1", colorspace="709")
    b = ET.SubElement(doc, "producer", {"id": "black", "in": "0",
                                           "out": str(n - 1)})
    prop(b, "length", n)
    prop(b, "eof", "pause")
    prop(b, "resource", "0")
    prop(b, "mlt_service", "color")
    prop(b, "mlt_image_format", "rgba")
    prop(b, "set.test_audio", "0")
    v1ids, v2ids = [], []
    for i, (f0, f1, crop) in enumerate(v1segs):
        pid = uid("producer")
        producer(doc, pid, mp4, hsh, n, crop, V1_FULL, False)
        v1ids.append((pid, f0, f1))
    for i, (f0, f1, crop) in enumerate(v2segs):
        pid = uid("producer")
        producer(doc, pid, mp4, hsh, n, crop, PIP, True)
        v2ids.append((pid, f0, f1))
    bg = ET.SubElement(doc, "playlist", id="background")
    ET.SubElement(bg, "entry", {"producer": "black", "in": "0",
                                "out": str(n - 1)})
    pl = ET.SubElement(doc, "playlist", id="playlist_v1")
    prop(pl, "shotcut:video", "1")
    prop(pl, "shotcut:name", "V1")
    for pid, f0, f1 in v1ids:
        ET.SubElement(pl, "entry", {"producer": pid, "in": str(f0),
                                    "out": str(f1)})
    ET.SubElement(pl, "blank", length=str(n - 1 - v1ids[-1][2]))
    pl2 = ET.SubElement(doc, "playlist", id=uid("playlist"))
    prop(pl2, "shotcut:video", "1")
    prop(pl2, "shotcut:name", "V2-cam")
    for pid, f0, f1 in v2ids:
        ET.SubElement(pl2, "entry", {"producer": pid, "in": str(f0),
                                     "out": str(f1)})
    ET.SubElement(pl2, "blank", length=str(n - 1 - v2ids[-1][2]))
    tr = ET.SubElement(doc, "tractor", {"id": "tractor0", "in": "0",
                                        "out": str(n - 1)})
    prop(tr, "shotcut", "1")
    prop(tr, "shotcut:projectAudioChannels", "2")
    prop(tr, "shotcut:processingMode", "Native8Cpu")
    prop(tr, "shotcut:projectNote", f"EP2 wtf clip_{nn} {nota}")
    for tprod in ("background", "playlist_v1", pl2.get("id")):
        ET.SubElement(tr, "track", producer=tprod)
    for a, bt, svc, dis in [("0", "1", "mix", None), ("0", "1", "qtblend", "1"),
                            ("0", "2", "mix", None), ("1", "2", "qtblend", "0")]:
        t = ET.SubElement(tr, "transition", id=uid("transition"))
        prop(t, "a_track", a)
        prop(t, "b_track", bt)
        if svc == "mix":
            prop(t, "always_active", "1")
            prop(t, "sum", "1")
        else:
            prop(t, "threads", "0")
        prop(t, "mlt_service", svc)
        if dis is not None:
            prop(t, "disable", dis)
        prop(t, "shotcut:mcpDefault", "1")
    return doc


def main():
    for nn, dur, nota, v1, v2 in CLIPS:
        doc = build(nn, dur, nota, v1, v2)
        out = OUT / f"clip_{nn}_shotcut.mlt"
        tree = ET.ElementTree(doc)
        ET.indent(tree)
        tree.write(out, encoding="utf-8", xml_declaration=True)
        print("OK", out)


main()
