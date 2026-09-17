"""Local FFmpeg, frame-rate and subtitle helpers."""
import glob
import os
import shutil
from pathlib import Path


def find_ffmpeg() -> str:
    p = shutil.which("ffmpeg")
    if p:
        return p
    base = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft",
                        "WinGet", "Packages")
    for root in glob.glob(os.path.join(base, "Gyan.FFmpeg*")):
        for cand in Path(root).glob("ffmpeg-*-full_build/bin/ffmpeg.exe"):
            return str(cand)
    raise RuntimeError("ffmpeg not found (not on PATH, no Gyan WinGet package)")


FF = find_ffmpeg()
FPROBE = str(Path(FF).with_name("ffprobe.exe")) if Path(FF).name == "ffmpeg.exe" else "ffprobe"

# Formato standard de salida (todos los clips):
# 1080x1920 mp4, H.264 yuv420p + faststart, AAC 48kHz 128k.
# FPS: se conserva el de origen si está en [23, 60], si no se fuerza 30.
# Duración: 15s mínimo, 59s máximo. Subtítulos: .srt al lado, NUNCA quemados.
MIN_CLIP_S = 15.0
MAX_CLIP_S = 59.0
MIN_KEEP_FPS = 23.0
MAX_KEEP_FPS = 60.0
FORCE_FPS = 30.0
STD_CODEC_ARGS = ["-c:v", "libx264", "-pix_fmt", "yuv420p",
                  "-movflags", "+faststart",
                  "-c:a", "aac", "-ar", "48000", "-b:a", "128k"]


def probe_fps(video) -> float:
    """FPS promedio de la fuente (0.0 si no se puede leer -> se fuerza 30)."""
    import subprocess
    try:
        r = subprocess.run([FPROBE, "-v", "error", "-select_streams", "v:0",
                            "-show_entries", "stream=avg_frame_rate",
                            "-of", "csv=p=0", str(video)],
                           capture_output=True, text=True)
        num, den = r.stdout.strip().split("/")
        fps = float(num) / float(den) if float(den) else 0.0
        return fps
    except Exception:
        return 0.0


def fps_args(video) -> list:
    """[] si el FPS de origen está en [23,60]; si no, fuerza 30."""
    fps = probe_fps(video)
    if MIN_KEEP_FPS <= fps <= MAX_KEEP_FPS:
        return []
    return ["-r", str(int(FORCE_FPS))]


def to_srt(words, a, b):
    lines, i, cur = [], 1, []
    def fmt(t):
        ms = int(t * 1000)
        return f"{ms//3600000:02d}:{(ms//60000)%60:02d}:{(ms//1000)%60:02d},{ms%1000:03d}"
    for w in words:
        if w["end"] < a or w["start"] > b:
            continue
        cur.append(w)
        text = " ".join(x["word"] for x in cur)
        if len(text) >= 42 or w["end"] - cur[0]["start"] >= 2.5:
            lines.append(f"{i}\n{fmt(max(cur[0]['start'],a) - a)} --> {fmt(min(cur[-1]['end'],b) - a)}\n{text}\n")
            i += 1
            cur = []
    if cur:
        lines.append(f"{i}\n{fmt(max(cur[0]['start'],a) - a)} --> {fmt(min(cur[-1]['end'],b) - a)}\n{' '.join(x['word'] for x in cur)}\n")
    return "\n".join(lines)



def vertical_vf(shift0, shift1, pan_t0, pan_dur):
    """Cadena vertical 9:16 (sin subtítulos: el .srt va en archivo separado)."""
    sh0, sh1, t0, dur = shift0, shift1, pan_t0, pan_dur
    return (
        "[0:v]split=2[full1][full2];"
        f"[full1]crop=ih*9/16:ih:(iw-ow)/2+ow*({sh1}+({sh0}-{sh1})"
        f"*(1-min(max((t-{t0})/{dur}\\,0)\\,1))),scale=1080:1920[base];"
        "[full2]crop=iw*165/1280:ih*242/720:iw*1085/1280:ih*24/720,"
        "scale=248:364[cam];"
        "[base][cam]overlay=1080-248-20:20[vout]"
    )
