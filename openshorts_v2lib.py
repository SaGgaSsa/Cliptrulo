"""Pure timestamp, subtitle and FFmpeg montage helpers."""


def parse_ts(ts: str) -> float:
    """'MM:SS' o 'H:MM:SS' -> segundos. Acepta '4:20' y '1:10:40'."""
    parts = [float(p) for p in ts.strip().split(":")]
    total = 0.0
    for p in parts:
        total = total * 60 + p
    return total


def resolve_section(section: str, offset: float) -> tuple:
    """'58:31-70:40' + offset 2713 -> (798.0, 1527.0) tiempo de archivo."""
    a, b = section.split("-")
    return (parse_ts(a) - offset, parse_ts(b) - offset)


def _parse_srt_ts(ts: str) -> float:
    h, m, rest = ts.split(":")
    s, ms = rest.split(",")
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0


def _fmt_srt_ts(t: float) -> str:
    ms = int(round(t * 1000))
    return f"{ms//3600000:02d}:{(ms//60000)%60:02d}:{(ms//1000)%60:02d},{ms%1000:03d}"


def shift_srt(srt_text: str, delta: float) -> str:
    """Desplaza todos los timestamps de un bloque SRT en delta segundos."""
    out = []
    for line in srt_text.splitlines():
        if "-->" in line:
            a, b = line.split("-->")
            out.append(f"{_fmt_srt_ts(_parse_srt_ts(a.strip()) + delta)} --> {_fmt_srt_ts(_parse_srt_ts(b.strip()) + delta)}")
        else:
            out.append(line)
    return "\n".join(out)


def montage_srt(to_srt_fn, words, spans) -> str:
    """Une to_srt() por span en un SRT continuo desde 00:00. Renumera bloques."""
    chunks, cursor = [], 0.0
    for sp in spans:
        chunk = to_srt_fn(words, sp["start"], sp["end"]).strip()
        if chunk:
            chunks.append(shift_srt(chunk, cursor))
            cursor += sp["end"] - sp["start"]
    lines, n = [], 1
    for chunk in chunks:
        parts = chunk.split("\n\n")
        for block in parts:
            bl = block.strip().splitlines()
            if len(bl) >= 3:
                lines.append(f"{n}\n{bl[1]}\n" + "\n".join(bl[2:]) + "\n")
                n += 1
    return "\n".join(lines)


def crudo_filter(n_spans):
    """concat de N spans (video+audio) sin crop ni PiP: crudo 16:9.
    El vertical se arma después en Shotcut."""
    v_ins = "".join(f"[{i}:v]" for i in range(n_spans))
    a_ins = "".join(f"[{i}:a]" for i in range(n_spans))
    return (f"{v_ins}concat=n={n_spans}:v=1:a=0[vout];"
            f"{a_ins}concat=n={n_spans}:v=0:a=1[acat]")


def montage_filter(n_spans, shift0, shift1, pan_t0, pan_dur, no_cam=False):
    """concat de N spans (video+audio) + cadena vertical 9:16 sobre el resultado.
    Sin subtítulos quemados: el .srt se escribe en archivo separado.
    no_cam: sin PiP webcam (para tramos donde el streamer la oculta)."""
    v_ins = "".join(f"[{i}:v]" for i in range(n_spans))
    a_ins = "".join(f"[{i}:a]" for i in range(n_spans))
    sh0, sh1, t0, dur = shift0, shift1, pan_t0, pan_dur
    crop = (f"crop=ih*9/16:ih:(iw-ow)/2+ow*({sh1}+({sh0}-{sh1})"
            f"*(1-min(max((t-{t0})/{dur}\\,0)\\,1))),scale=1080:1920")
    if no_cam:
        base = f"[vcat]{crop}[vout]"
    else:
        base = (
            f"[vcat]split=2[full1][full2];"
            f"[full1]{crop}[base];"
            "[full2]crop=iw*165/1280:ih*242/720:iw*1085/1280:ih*24/720,"
            "scale=248:364[cam];"
            "[base][cam]overlay=1080-248-20:20[vout]"
        )
    return f"{v_ins}concat=n={n_spans}:v=1:a=0[vcat];{a_ins}concat=n={n_spans}:v=0:a=1[acat];{base}"
