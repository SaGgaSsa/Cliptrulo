"""Genera proyectos Shotcut verticales 1080x1920 desde un spec JSON.

Estructura verificada (igual que relatando/clip_0*_shotcut.mlt):
V1 = crop px + affine full distort=0 (partido por escena), V2-cam = crop
caja + affine PiP 760 20 300 437 distort=0 (partido por geometria de cam),
MUTEADA (hide=2 en la playlist: el audio sale solo de V1), compositing
qtblend default. Si V2 arranca tarde (t0>0) se antepone <blank> para
conservar el sync (los entry in/out son frames del productor, no timeline).
Hash = MD5(primer+ultimo MB) como Shotcut.

El spec lo arma el agente: v1 = crop al area de video medido por clip,
v2 = `camspec.py` (detecta caja + switches, sin valores a mano).
La caja chica se expande a la receta con titulo (TITLE_TOP/TITLE_PAD_X);
la grande va exacta. Ver specs/ep2_wtf.json.

Uso:
  python tools/mkshotcut.py [--spec specs/ep2_wtf.json]
  python tools/mkshotcut.py --spec specs/ep2_monotributistas.json \
      --outdir output/ep2/monotributistas --section monotributistas
"""
import argparse
import hashlib
import json
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "output" / "ep2" / "wtf"
FPS = 30

V1_FULL = {"rect": "0 0 1080 1920", "distort": "0"}
PIP = {"rect": "760 20 300 437", "distort": "0"}

# Receta PiP con titulo (standard EP2): la caja detectada es el borde azul;
# el crop incluye el titulo CHITRULO de arriba (y0 106->48) + 10px izquierda.
# Solo para geometria chica (la grande ya ocupa su caja exacta).
TITLE_TOP = 48
TITLE_PAD_X = 10
SMALL_CAM_MAX_AREA = 100000


def v2_crop(box):
    """Caja detectada [x0,y0,x1,y1] -> margenes de crop (receta con titulo)."""
    x0, y0, x1, y1 = box
    if (x1 - x0) * (y1 - y0) < SMALL_CAM_MAX_AREA:
        return (x0 - TITLE_PAD_X, TITLE_TOP, 1920 - x1, 1080 - (y1 + 1))
    return (x0, y0, 1920 - x1, 1080 - y1)


def seg_frames(t0, t1, n):
    f0 = round(t0 * FPS)
    f1 = min(round(t1 * FPS) - 1, n - 2)
    return f0, f1


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


def build(nn, dur, nota, v1segs, v2segs, outdir, section):
    n = round(dur * FPS)
    mp4 = f"C:/Users/saggassa/Desktop/cliptrulo/{outdir}/clip_{nn}.mp4"
    hsh = file_hash(ROOT / outdir / f"clip_{nn}.mp4")
    doc = ET.Element("mlt", LC_NUMERIC="C", version="7.40.0",
                     title="Shotcut version 26.6.25", producer="tractor0",
                     root=f"C:/Users/saggassa/Desktop/cliptrulo/{outdir}")
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
    if v1ids[0][1] > 0:
        ET.SubElement(pl, "blank", length=str(v1ids[0][1]))
    for pid, f0, f1 in v1ids:
        ET.SubElement(pl, "entry", {"producer": pid, "in": str(f0),
                                    "out": str(f1)})
    ET.SubElement(pl, "blank", length=str(n - 1 - v1ids[-1][2]))
    pl2 = ET.SubElement(doc, "playlist", id=uid("playlist"))
    prop(pl2, "hide", 2)  # V2-cam muteada: el audio sale solo de V1
    prop(pl2, "shotcut:video", "1")
    prop(pl2, "shotcut:name", "V2-cam")
    if v2ids[0][1] > 0:
        ET.SubElement(pl2, "blank", length=str(v2ids[0][1]))
    for pid, f0, f1 in v2ids:
        ET.SubElement(pl2, "entry", {"producer": pid, "in": str(f0),
                                     "out": str(f1)})
    ET.SubElement(pl2, "blank", length=str(n - 1 - v2ids[-1][2]))
    tr = ET.SubElement(doc, "tractor", {"id": "tractor0", "in": "0",
                                        "out": str(n - 1)})
    prop(tr, "shotcut", "1")
    prop(tr, "shotcut:projectAudioChannels", "2")
    prop(tr, "shotcut:processingMode", "Native8Cpu")
    prop(tr, "shotcut:projectNote", f"EP2 {section} clip_{nn} {nota}")
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
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", default=str(ROOT / "specs" / "ep2_wtf.json"))
    ap.add_argument("--outdir", default="output/ep2/wtf")
    ap.add_argument("--section", default="wtf")
    ap.add_argument("--only", default=None)
    a = ap.parse_args()
    out = ROOT / a.outdir
    spec = json.loads(Path(a.spec).read_text(encoding="utf-8"))
    for c in spec["clips"]:
        if a.only and c["nn"] != a.only:
            continue
        n = round(c["dur"] * FPS)
        v1 = [(seg_frames(s["t0"], s["t1"], n)[0],
               seg_frames(s["t0"], s["t1"], n)[1],
               tuple(s["crop"])) for s in c["v1"]]
        v2 = [(seg_frames(s["t0"], s["t1"], n)[0],
               seg_frames(s["t0"], s["t1"], n)[1],
               v2_crop(s["box"])) for s in c["v2"] if s["box"]]
        doc = build(c["nn"], c["dur"], c["note"], v1, v2, a.outdir, a.section)
        dest = out / f"clip_{c['nn']}_shotcut.mlt"
        tree = ET.ElementTree(doc)
        ET.indent(tree)
        tree.write(dest, encoding="utf-8", xml_declaration=True)
        print("OK", dest)


main()
