"""Shared helpers for v1 (run/cut) and v2. Import-safe: no side effects."""
import glob
import json
import os
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "vendor" / "openshorts"))

from google import genai
from google.genai import types as genai_types

import gemini_worker

MODEL = "gemini-3.1-flash-lite"
LANGUAGE = "Spanish"

key = [l.split("=", 1)[1].strip()
       for l in open(".env", encoding="utf-8") if l.startswith("GEMINI_API_KEY")][0]
client = genai.Client(api_key=key)


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


def build_segments(words, gap=0.8, max_len=30.0):
    segs, cur = [], []
    for w in words:
        if cur and (w["start"] - cur[-1]["end"] > gap
                    or w["end"] - cur[0]["start"] > max_len):
            segs.append(cur)
            cur = []
        cur.append(w)
    if cur:
        segs.append(cur)
    out = []
    for s in segs:
        out.append({
            "start": s[0]["start"], "end": s[-1]["end"],
            "text": " ".join(w["word"] for w in s),
            "words": [{"word": w["word"], "start": w["start"], "end": w["end"]} for w in s],
        })
    return out


def stage(prompt, schema, label):
    config = genai_types.GenerateContentConfig(
        response_mime_type="application/json", response_schema=schema)
    for attempt in range(1, 4):
        try:
            resp = client.models.generate_content(model=MODEL, contents=prompt, config=config)
            gemini_worker.raise_if_blocked(resp)
            parsed = getattr(resp, "parsed", None)
            if parsed is not None:
                return parsed.model_dump() if hasattr(parsed, "model_dump") else parsed
            return gemini_worker._parse_json_response_text(
                gemini_worker._get_response_text(resp))
        except gemini_worker.GeminiBlockedError:
            raise
        except Exception as e:
            print(f"  transient {label} attempt {attempt}/3: {str(e)[:150]}")
            if attempt == 3:
                raise
            time.sleep(5 * (2 ** (attempt - 1)))


def vertical_vf(shift0, shift1, pan_t0, pan_dur, srt_name):
    """9:16 chain from openshorts_cut.py. srt_name = basename only (cwd=out)."""
    sh0, sh1, t0, dur = shift0, shift1, pan_t0, pan_dur
    return (
        "[0:v]split=2[full1][full2];"
        f"[full1]crop=ih*9/16:ih:(iw-ow)/2+ow*({sh1}+({sh0}-{sh1})"
        f"*(1-min(max((t-{t0})/{dur}\\,0)\\,1))),scale=1080:1920[base];"
        "[full2]crop=iw*165/1280:ih*242/720:iw*1085/1280:ih*24/720,"
        "scale=248:364[cam];"
        "[base][cam]overlay=1080-248-20:20,"
        f"subtitles={srt_name}"
    )
