# Shorts v2 (montaje por secciones) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Construir `openshorts_v2.py` que, dada una sección del vivo, la segmenta en items con Gemini, elige 3-4 items y monta cada clip uniendo spans (presentación + reacción + comentarios) con la cadena vertical actual.

**Architecture:** Nuevo módulo import-safe `openshorts_common.py` con los helpers de v1; `openshorts_v2.py` con 3 fases (segmentar → highlights → montar) que reusa `vendor/openshorts` (`build_transcript_windows`, `snap_clip_to_words`) y un solo pase FFmpeg con filtro `concat` + la cadena vertical existente.

**Tech Stack:** Python 3.12 (`.\.venv`), `google-genai` (`gemini-3.1-flash-lite`), `pydantic` 2.13.5 (para `response_schema`), FFmpeg (Gyan WinGet vía `find_ffmpeg()`).

**Spec:** `docs/superpowers/specs/2026-09-08-shorts-v2-sections-design.md`

## Global Constraints

- Modelo SIEMPRE `gemini-3.1-flash-lite` (constante `MODEL` en el módulo común). No `gemini-2.5-*`, no `3.6-flash`.
- `GEMINI_API_KEY` se lee parseando `.env` a mano (`[l.split("=",1)[1].strip() for l in open(".env") if l.startswith("GEMINI_API_KEY")][0]`). No dotenv, no commitear `.env`.
- `openshorts_run.py` y `openshorts_cut.py` ejecutan `main()` al importarse: el código nuevo NUNCA los importa; solo importa `openshorts_common` y `vendor/openshorts`.
- `vendor/openshorts/` es solo lectura. No editarlo.
- Timestamps internos SIEMPRE en segundos absolutos del archivo de video (`--video`); `--section` viene en tiempo del vivo y `--offset` lo mapea una sola vez en el CLI.
- Clips finales entre 15s y 60s. Sin dependencias nuevas (no pytest en el repo: la verificación es `python -c "assert ..."` + corridas reales + frames).
- Comandos siempre desde la raíz, PowerShell: `& ".\.venv\Scripts\python.exe" ...`.

---

### Task 1: Extraer `openshorts_common.py` y reconectar v1

**Files:**
- Create: `openshorts_common.py`
- Modify: `openshorts_run.py` (usa el módulo común; comportamiento idéntico)
- Modify: `openshorts_cut.py` (usa el módulo común; `vf` idéntico con defaults)

**Interfaces:**
- Consumes: nada nuevo.
- Produces (usado por Tasks 4-7): `MODEL: str`, `LANGUAGE: str`, `find_ffmpeg() -> str`, `to_srt(words, a, b) -> str`, `build_segments(words, gap=0.8, max_len=30.0) -> list[dict]`, `stage(prompt, schema, label) -> dict`, `vertical_vf(shift0, shift1, pan_t0, pan_dur, srt_name) -> str`.

- [ ] **Step 1: Crear `openshorts_common.py` con helpers copiados verbatim**

```python
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
```

- [ ] **Step 2: Reescribir `openshorts_run.py` para importar del común**

Borrar de `openshorts_run.py`: líneas 14-18 (`os`, `sys`, `time`, `sys.path.insert`), 23-24 (`genai`, `genai_types`), 26 (`import gemini_worker`), 33-38 (`MODEL`/`LANGUAGE`/`key`/`client`), y las funciones `build_segments` (41-58) y `stage` (61-79). Agregar arriba:

```python
from openshorts_common import LANGUAGE, MODEL, build_segments, stage
import gemini_worker
```

Mantener el `sys.path.insert` del vendor ANTES de `import gemini_worker` (copiar líneas 16 y 21-22 tal cual). Todo lo demás de `main()` queda igual.

- [ ] **Step 3: Reescribir `openshorts_cut.py` para importar del común**

Borrar `find_ffmpeg` (18-30), `FF = find_ffmpeg()` (30), `to_srt` (33-49). Agregar:

```python
from openshorts_common import FF, to_srt, vertical_vf
```

Reemplazar el bloque `vf = (...)` (líneas 99-108) por:

```python
vf = vertical_vf(args.shift0, args.shift1, args.pan_t0, args.pan_dur, srt.name)
```

Borrar los imports ya no usados (`glob`, `os`, `shutil`).

- [ ] **Step 4: Verificar que v1 sigue intacta**

Run: `& ".\.venv\Scripts\python.exe" openshorts_run.py --help` → Expected: muestra args sin error.
Run: `& ".\.venv\Scripts\python.exe" openshorts_cut.py --help` → Expected: muestra args con `--shift0/--only-9x16` sin error.
Run: `& ".\.venv\Scripts\python.exe" -c "from openshorts_common import vertical_vf; vf = vertical_vf(0.2, 0.0, 12.0, 3.5, 'x.srt'); assert 'crop=ih*9/16' in vf and 'subtitles=x.srt' in vf; print('VF-OK')"` → Expected: `VF-OK`.

- [ ] **Step 5: Commit**

```bash
git add openshorts_common.py openshorts_run.py openshorts_cut.py
git commit -m "refactor: extract openshorts_common (v1 behavior unchanged)"
```

---

### Task 2: Schemas + prompts de segmentación y highlights

**Files:**
- Create: `openshorts_v2lib.py` (puro, sin side effects: schemas pydantic + templates + validadores)

**Interfaces:**
- Consumes: `pydantic.BaseModel` (igual que `vendor/openshorts/gemini_worker.py:10`).
- Produces: `SegmentItem`, `SegmentResponse`, `HighlightSpan`, `HighlightResponse`, `SEGMENT_PROMPT_TEMPLATE`, `HIGHLIGHT_PROMPT_TEMPLATE`.

- [ ] **Step 1: Crear `openshorts_v2lib.py`**

```python
"""v2 pure helpers: pydantic schemas + Gemini prompt templates. No side effects."""
from typing import List, Literal
from pydantic import BaseModel, Field


class SegmentItem(BaseModel):
    start: float
    end: float
    kind: Literal["presentacion", "visionado", "reaccion", "comentarios", "relleno"]
    score: int = Field(ge=0, le=100)
    summary: str


class SegmentResponse(BaseModel):
    items: List[SegmentItem]


class HighlightSpan(BaseModel):
    start: float
    end: float
    role: Literal["presentacion", "mejor_reaccion", "comentarios"]


class HighlightResponse(BaseModel):
    spans: List[HighlightSpan]


SEGMENT_PROMPT_TEMPLATE = """
You are a senior short-form video editor for a Spanish-language reaction live stream.
Below is the transcript of ONE section of the stream, as JSON windows
[{{"id","start","end","text"}}]. Timestamps are ABSOLUTE SECONDS of the source file.

TIME CONTRACT — STRICT:
- {sec_a} <= start < end <= {sec_b}. Numbers with up to 3 decimals.
- Items must be CONTIGUOUS and cover the whole [{sec_a},{sec_b}] range with no gaps
  and no overlaps: item[i+1].start == item[i].end (up to 0.5s tolerance).
- Split items longer than ~180s into smaller ones.

Classify each item with kind:
- presentacion: host introduces a video about to be shown
- visionado: the video itself is playing, host mostly quiet
- reaccion: host reacts/laughs/comments on what was just shown
- comentarios: host reads or answers chat comments
- relleno: silences, rambling, off-topic — will be discarded

score 0-100 = how funny/viral the item is as short-form material.
If an item mixes two kinds, split it. Prefer more, shorter items over few long ones.

Windows:
{windows_json}
"""

HIGHLIGHT_PROMPT_TEMPLATE = """
You are a senior short-form video editor. Below is the transcript of ONE item
(a single video the host presents and reacts to), as JSON windows
[{{"id","start","end","text"}}]. Timestamps are ABSOLUTE SECONDS of the source file.

TIME CONTRACT — STRICT:
- {item_a} <= start < end <= {item_b}. Numbers with up to 3 decimals.
- Every span must be 3-25s long. Return 2-5 spans, total <= 60s.
- Order spans chronologically. Roles in narrative order when possible:
  presentacion first (how the host introduces the video, 5-10s),
  then mejor_reaccion (the peak moment(s)),
  then comentarios (chat reads that add something — not all of them).

Transcript:
{windows_json}
"""
```

- [ ] **Step 2: Validar schemas con JSON enlatado (sin gastar API)**

Run:
```bash
& ".\.venv\Scripts\python.exe" -c "from openshorts_v2lib import SegmentResponse, HighlightResponse; s = SegmentResponse.model_validate({'items': [{'start': 798.0, 'end': 830.5, 'kind': 'presentacion', 'score': 82, 'summary': 'presenta el video del auto'}]}); h = HighlightResponse.model_validate({'spans': [{'start': 798.0, 'end': 806.0, 'role': 'presentacion'}]}); print('SCHEMAS-OK', s.items[0].kind, h.spans[0].role)"
```
Expected: `SCHEMAS-OK presentacion presentacion`. Además probar que `kind='foobar'` lanza `ValidationError` (agregar `try/except` al comando o segunda corrida).

- [ ] **Step 3: Commit**

```bash
git add openshorts_v2lib.py
git commit -m "feat(v2): segment/highlight schemas and prompts"
```

---

### Task 3: Utilidades de tiempo y SRT para montaje

**Files:**
- Modify: `openshorts_v2lib.py` (agregar funciones puras)

**Interfaces:**
- Consumes: nada nuevo.
- Produces: `parse_ts(ts: str) -> float`, `resolve_section(section: str, offset: float) -> tuple[float, float]`, `shift_srt(srt_text: str, delta: float) -> str`, `montage_srt(words, spans) -> str` donde `spans = [{"start","end"}...]` en segundos absolutos de archivo y el SRT resultante es continuo desde 00:00.

- [ ] **Step 1: Agregar funciones puras a `openshorts_v2lib.py`**

```python
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
```

`montage_srt` recibe `to_srt_fn` como parámetro para no importar `openshorts_common` desde la lib pura (el llamador pasa `openshorts_common.to_srt`).

- [ ] **Step 2: Verificar con asserts (sin API, sin ffmpeg)**

Run:
```bash
& ".\.venv\Scripts\python.exe" -c "from openshorts_v2lib import parse_ts, resolve_section, shift_srt, montage_srt; assert parse_ts('4:20') == 260.0; assert parse_ts('1:10:40') == 4240.0; assert resolve_section('58:31-70:40', 2713) == (798.0, 1527.0); assert '00:00:05,000 --> 00:00:07,000' in shift_srt('1\n00:00:00,000 --> 00:00:02,000\nHola\n', 5.0); words=[{'word':'hola','start':10.0,'end':10.4},{'word':'mundo','start':10.5,'end':10.9}]; from openshorts_common import to_srt; s=montage_srt(to_srt, words, [{'start':10.0,'end':10.9},{'start':10.4,'end':10.9}]); assert s.startswith('1\n00:00:00'), s[:60]; print('TIME-OK')"
```
Expected: `TIME-OK`.

- [ ] **Step 3: Commit**

```bash
git add openshorts_v2lib.py
git commit -m "feat(v2): time utils and montage SRT builder"
```

---

### Task 4: Fase segmentar (pasada 1 con datos reales)

**Files:**
- Create: `openshorts_v2.py` (CLI + `phase_segment`)

**Interfaces:**
- Consumes: `openshorts_common` (`build_segments`, `stage`, `LANGUAGE`), `openshorts_v2lib` (`SEGMENT_PROMPT_TEMPLATE`, `SegmentResponse`, `resolve_section`), `vendor` (`build_transcript_windows`, `snap_clip_to_words`).
- Produces: `phase_segment(words, sec_a, sec_b, duration) -> dict` (guarda `items.json`); CLI `--video --words --section --offset --out --phase`.

- [ ] **Step 1: Crear `openshorts_v2.py` con CLI y `phase_segment`**

```python
"""Shorts v2: segment -> highlight -> montage per live section (pilot: El Concesionario).

Usage:
  python openshorts_v2.py --video downloads/EPISODIO3_segunda_mitad_45-13_fin.mp4 \
      --words downloads/segunda_mitad_words.json \
      --section "58:31-1:10:40" --offset 2713 --out output/v2/concesionario --phase segment
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "vendor" / "openshorts"))

from openshorts_common import LANGUAGE, build_segments, stage
from openshorts_v2lib import SEGMENT_PROMPT_TEMPLATE, SegmentResponse, resolve_section
from clip_selection import build_transcript_windows, snap_clip_to_words


def section_words(words, a, b):
    return [w for w in words if w["end"] >= a and w["start"] <= b]


def phase_segment(words, sec_a, sec_b):
    segments = build_segments(section_words(words, sec_a, sec_b))
    transcript = {"language": LANGUAGE, "segments": segments,
                  "text": " ".join(w["word"] for w in section_words(words, sec_a, sec_b))}
    windows = build_transcript_windows(transcript, sec_b - sec_a,
                                       window_seconds=90, overlap_seconds=30)
    print(f"segment: words-in-section, windows={len(windows)}")
    payload = [{"id": w["id"], "start": w["start"] + sec_a, "end": w["end"] + sec_a,
                "text": w["text"]} for w in windows]
```

ATENCIÓN: `build_transcript_windows` devuelve tiempos relativos a los segmentos que recibe. Como los segmentos ya vienen en tiempo absoluto de archivo, `w["start"]` YA es absoluto: NO sumar `sec_a`. El payload correcto es:

```python
    payload = [{"id": w["id"], "start": w["start"], "end": w["end"], "text": w["text"]}
               for w in windows]
```

(continúa)

```python
    prompt = SEGMENT_PROMPT_TEMPLATE.format(
        sec_a=round(sec_a, 3), sec_b=round(sec_b, 3),
        windows_json=json.dumps(payload, ensure_ascii=False))
    parsed = stage(prompt, SegmentResponse, "v2-segment")
    flat = [{"w": w["word"], "s": w["start"], "e": w["end"]} for w in words]
    items = []
    for it in parsed.get("items") or []:
        ns, ne = snap_clip_to_words(it["start"], it["end"], flat, sec_b,
                                    min_duration=3.0, max_duration=600.0)
        items.append({"start": ns, "end": ne, "kind": it["kind"],
                      "score": it["score"], "summary": it.get("summary", "")})
    return {"sec_a": sec_a, "sec_b": sec_b, "items": items}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--words", required=True)
    ap.add_argument("--section", required=True, help="'MM:SS-MM:SS' en tiempo del vivo")
    ap.add_argument("--offset", type=float, default=0.0)
    ap.add_argument("--out", required=True)
    ap.add_argument("--phase", default="all",
                    choices=["segment", "highlight", "montage", "all"])
    args = ap.parse_args()

    words = json.loads(Path(args.words).read_text(encoding="utf-8"))
    sec_a, sec_b = resolve_section(args.section, args.offset)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    if args.phase in ("segment", "all"):
        seg = phase_segment(words, sec_a, sec_b)
        (out / "items.json").write_text(json.dumps(seg, indent=2, ensure_ascii=False),
                                        encoding="utf-8")
        for it in seg["items"]:
            print(f"- [{it['start']:.0f}-{it['end']:.0f}] {it['kind']} score={it['score']} {it['summary'][:80]}")


main()
```

- [ ] **Step 2: Correr segmentación real del piloto**

Run:
```bash
& ".\.venv\Scripts\python.exe" openshorts_v2.py --video "downloads\EPISODIO3_segunda_mitad_45-13_fin.mp4" --words "downloads\segunda_mitad_words.json" --section "58:31-1:10:40" --offset 2713 --out "output\v2\concesionario" --phase segment
```
Expected: `items.json` existe; items contiguos cubren ~[798,1527]; hay `presentacion`/`reaccion`/`comentarios` y algún `relleno`. Verificar a mano:
```bash
& ".\.venv\Scripts\python.exe" -c "import json; d=json.load(open('output/v2/concesionario/items.json')); it=d['items']; assert it[0]['start']<=d['sec_a']+1 and it[-1]['end']>=d['sec_b']-1, 'no cubre'; kinds={x['kind'] for x in it}; assert {'presentacion','reaccion'}<=kinds, kinds; print('SEG-OK', len(it), sorted(kinds))"
```
Expected: `SEG-OK <n> [...]`. Si falla, ajustar el prompt (no el código) y re-correr.

- [ ] **Step 3: Commit**

```bash
git add openshorts_v2.py
git commit -m "feat(v2): phase segment on pilot section"
```

---

### Task 5: Fase highlights (pasada 2 con datos reales)

**Files:**
- Modify: `openshorts_v2.py` (agregar `phase_highlight` + CLI `--clips`)

**Interfaces:**
- Consumes: `output/v2/<seccion>/items.json`, `HIGHLIGHT_PROMPT_TEMPLATE`, `HighlightResponse`.
- Produces: `phase_highlight(words, items, n_clips=4) -> dict` (guarda `montages.json` con `spans` en tiempo absoluto + `total` ≤ 60 verificado).

- [ ] **Step 1: Agregar `phase_highlight`**

```python
from openshorts_v2lib import HIGHLIGHT_PROMPT_TEMPLATE, HighlightResponse  # sumar al import


def phase_highlight(words, items, n_clips=4):
    scored = sorted([it for it in items if it["kind"] != "relleno"],
                    key=lambda x: x.get("score", 0), reverse=True)[:n_clips]
    flat = [{"w": w["word"], "s": w["start"], "e": w["end"]} for w in words]
    montages = []
    for rank, it in enumerate(scored, 1):
        segments = build_segments(section_words(words, it["start"], it["end"]))
        transcript = {"language": LANGUAGE, "segments": segments,
                      "text": " ".join(w["word"] for w in section_words(words, it["start"], it["end"]))}
        windows = build_transcript_windows(transcript, it["end"] - it["start"],
                                           window_seconds=90, overlap_seconds=30)
        payload = [{"id": w["id"], "start": w["start"], "end": w["end"], "text": w["text"]}
                   for w in windows]
        prompt = HIGHLIGHT_PROMPT_TEMPLATE.format(
            item_a=round(it["start"], 3), item_b=round(it["end"], 3),
            windows_json=json.dumps(payload, ensure_ascii=False))
        parsed = stage(prompt, HighlightResponse, f"v2-highlight-{rank}")
        spans = []
        for sp in parsed.get("spans") or []:
            ns, ne = snap_clip_to_words(sp["start"], sp["end"], flat, it["end"],
                                        min_duration=2.0, max_duration=30.0)
            spans.append({"start": ns, "end": ne, "role": sp["role"]})
        spans.sort(key=lambda s: s["start"])
        # Regla dura: total <= 60s. Recortar rol 'comentarios' primero (del final).
        total = sum(s["end"] - s["start"] for s in spans)
        while total > 60.0:
            droppable = [s for s in reversed(spans) if s["role"] == "comentarios"]
            pool = droppable or list(reversed(spans))
            if len(spans) <= 1:
                raise RuntimeError(f"clip {rank}: un solo span de {total:.1f}s > 60s")
            spans.remove(pool[0])
            total = sum(s["end"] - s["start"] for s in spans)
        total = round(total, 3)
        if total < 15.0:
            print(f"  WARN clip {rank}: total {total:.1f}s < 15s, se extiende en montaje")
        montages.append({"rank": rank, "item": it, "spans": spans, "total": total})
    return {"montages": montages}
```

Y en `main()`: `ap.add_argument("--clips", type=int, default=4)` + bloque:

```python
    if args.phase in ("highlight", "all"):
        seg = json.loads((out / "items.json").read_text(encoding="utf-8"))
        mon = phase_highlight(words, seg["items"], args.clips)
        (out / "montages.json").write_text(json.dumps(mon, indent=2, ensure_ascii=False),
                                           encoding="utf-8")
        for m in mon["montages"]:
            print(f"- clip {m['rank']}: total={m['total']:.1f}s spans={len(m['spans'])}")
```

- [ ] **Step 2: Correr highlights del piloto**

Run:
```bash
& ".\.venv\Scripts\python.exe" openshorts_v2.py --video "downloads\EPISODIO3_segunda_mitad_45-13_fin.mp4" --words "downloads\segunda_mitad_words.json" --section "58:31-1:10:40" --offset 2713 --out "output\v2\concesionario" --phase highlight
```
Expected: `montages.json` con 4 montages, cada `total` entre 15 y 60 (o WARN + ≥algún valor si un item es corto). Verificar:
```bash
& ".\.venv\Scripts\python.exe" -c "import json; m=json.load(open('output/v2/concesionario/montages.json'))['montages']; assert len(m)==4; [print(x['rank'], x['total'], [(round(s['start']),s['role']) for s in x['spans']]) for x in m]; assert all(x['total']<=60 for x in m); print('HL-OK')"
```
Expected: `HL-OK`.

- [ ] **Step 3: Commit**

```bash
git add openshorts_v2.py
git commit -m "feat(v2): phase highlight with 60s hard cap"
```

---

### Task 6: Fase montaje (un pase FFmpeg con `concat`)

**Files:**
- Modify: `openshorts_v2.py` (agregar `phase_montage`), `openshorts_v2lib.py` (agregar `montage_filter`)

**Interfaces:**
- Consumes: `montages.json`, `openshorts_common` (`FF`, `to_srt`, `vertical_vf`), `montage_srt`.
- Produces: `montage_filter(n_spans, shift0, shift1, pan_t0, pan_dur, srt_name) -> str` (filtergraph con `concat` de N spans + cadena vertical); `phase_montage(...)` escribe `clip_0N_9x16.mp4` + `.srt` por clip.

- [ ] **Step 1: Agregar `montage_filter` a `openshorts_v2lib.py`**

```python
def montage_filter(n_spans, shift0, shift1, pan_t0, pan_dur, srt_name):
    """concat de N spans (video+audio) + cadena vertical 9:16 sobre el resultado."""
    v_ins = "".join(f"[{i}:v]" for i in range(n_spans))
    a_ins = "".join(f"[{i}:a]" for i in range(n_spans))
    sh0, sh1, t0, dur = shift0, shift1, pan_t0, pan_dur
    base = (
        f"[vcat]split=2[full1][full2];"
        f"[full1]crop=ih*9/16:ih:(iw-ow)/2+ow*({sh1}+({sh0}-{sh1})"
        f"*(1-min(max((t-{t0})/{dur}\\,0)\\,1))),scale=1080:1920[base];"
        "[full2]crop=iw*165/1280:ih*242/720:iw*1085/1280:ih*24/720,"
        "scale=248:364[cam];"
        "[base][cam]overlay=1080-248-20:20,"
        f"subtitles={srt_name}[vout]"
    )
    return f"{v_ins}concat=n={n_spans}:v=1:a=0[vcat];{a_ins}concat=n={n_spans}:v=0:a=1[acat];{base}"
```

- [ ] **Step 2: Agregar `phase_montage` a `openshorts_v2.py`**

```python
import subprocess  # arriba
from openshorts_common import FF, to_srt, vertical_vf  # sumar al import (vertical_vf no se usa acá, no importar)
from openshorts_v2lib import montage_filter, montage_srt  # sumar al import


def phase_montage(video, words, montages, out, shift0=0.0, shift1=0.0,
                  pan_t0=0.0, pan_dur=1.0):
    for m in montages["montages"]:
        spans = m["spans"]
        if m["total"] < 15.0:
            # Extender el ÚLTIMO span (conserva narrativa) hasta 15s.
            need = 15.0 - m["total"]
            spans[-1] = dict(spans[-1], end=spans[-1]["end"] + need)
            m["total"] = 15.0
        srt_text = montage_srt(to_srt, words, spans)
        base = out / f"clip_{m['rank']:02d}"
        srt = base.with_suffix(".srt")
        vert = Path(str(base) + "_9x16.mp4")
        srt.write_text(srt_text, encoding="utf-8")
        cmd = [FF, "-y", "-v", "error"]
        for sp in spans:
            cmd += ["-ss", str(sp["start"]), "-t", str(round(sp["end"] - sp["start"], 3)),
                    "-i", str(Path(video).resolve())]
        # NOTA: -ss y -t van ANTES de cada -i (opciones de input): limitan ese input.
        cmd += ["-filter_complex",
                montage_filter(len(spans), shift0, shift1, pan_t0, pan_dur, srt.name),
                "-map", "[vout]", "-map", "[acat]", "-c:a", "aac", vert.name]
        r = subprocess.run(cmd, cwd=str(out))
        print(("OK " if r.returncode == 0 else "MONTAGE-FAIL ") + vert.name)
```

OJO: el `-t` después de cada `-i` limita duración de ESE input (correcto así). En `main()` agregar args `--shift0/--shift1/--pan-t0/--pan-dur/--only` (mismos defaults y semántica que v1: `--shift0 0.20 --shift1 0.0 --pan-t0 12 --pan-dur 3.5`) + bloque:

```python
    if args.phase in ("montage", "all"):
        mon = json.loads((out / "montages.json").read_text(encoding="utf-8"))
        if args.only:
            mon = {"montages": [x for x in mon["montages"] if x["rank"] == args.only]}
        phase_montage(args.video, words, mon, out, args.shift0, args.shift1,
                      args.pan_t0, args.pan_dur)
```

- [ ] **Step 3: Probar filtro con 1 clip antes del lote (`--only 1`)**

Run:
```bash
& ".\.venv\Scripts\python.exe" openshorts_v2.py --video "downloads\EPISODIO3_segunda_mitad_45-13_fin.mp4" --words "downloads\segunda_mitad_words.json" --section "58:31-1:10:40" --offset 2713 --out "output\v2\concesionario" --phase montage --only 1 --shift0 0.22 --shift1 0.22
```
Expected: `OK clip_01_9x16.mp4`. Verificar duración ≈ total y que tiene audio:
```bash
& "C:\Users\saggassa\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.0.1-full_build\bin\ffprobe.exe" -v error -show_entries format=duration -show_entries stream=codec_type -of csv "output\v2\concesionario\clip_01_9x16.mp4"
```
(Si `ffprobe` no está en esa ruta, usar el mismo `find_ffmpeg()` y reemplazar `ffmpeg.exe` por `ffprobe.exe` en el mismo `bin/`.) Expected: 1 stream video + 1 audio, duración ≈ `total` de montages.json ±0.5s.

- [ ] **Step 4: Commit**

```bash
git add openshorts_v2.py openshorts_v2lib.py
git commit -m "feat(v2): phase montage with concat filter"
```

---

### Task 7: Piloto completo + verificación visual + docs

**Files:**
- Modify: `AGENTS.md` (uso genérico de v2), nada más código salvo fixes del piloto.

- [ ] **Step 1: Correr los 4 clips del piloto**

Run:
```bash
& ".\.venv\Scripts\python.exe" openshorts_v2.py --video "downloads\EPISODIO3_segunda_mitad_45-13_fin.mp4" --words "downloads\segunda_mitad_words.json" --section "58:31-1:10:40" --offset 2713 --out "output\v2\concesionario" --phase montage --shift0 0.22 --shift1 0.22
```
Expected: `OK clip_01..04_9x16.mp4` (si el paneo estático 0.22 no centra, calibrar con frames como en v1 y re-correr con `--only N`).

- [ ] **Step 2: Frames inicio/medio/fin + medición de bordes por clip**

Reusar el método v1: extraer 3 frames por clip con `FF -ss <t> -i clip -frames:v 1`, medir bordes del contenido (negra_izq/gris_der sobre fila media) y ajustar shift/paneo por clip si hace falta. Criterio: contenido sin barras laterales reales (ignorar transitorios del propio video: flashes, placas, pantallas de carga).

- [ ] **Step 3: Revisión del usuario y fixes**

Mostrar qué trae cada clip (roles + tiempos). Si la segmentación mete ruido sistemático (items mal partidos, reacciones flojas), NO reescribir: documentar el fallback asistido (elegir items de `items.json` a mano y correr `--phase highlight` con lista fija — implementar solo si el piloto lo exige, como task extra aprobada).

- [ ] **Step 4: Actualizar AGENTS.md (genérico, sin datos del video)**

Agregar bajo "Comandos": la línea del run v2 con placeholders (`--section "MM:SS-MM:SS" --offset N`). En "Reglas del pipeline": 1-2 bullets (fases, `output\v2\<seccion>\`, `montages.json` con `total` ≤60, extends a 15s). Sin layouts medidos ni timestamps del EP3.

- [ ] **Step 5: Commit final**

```bash
git add AGENTS.md
git commit -m "docs: v2 usage"
```

---

## Self-Review

1. **Spec coverage:** §1 → Tasks 1/4 (CLI, offset, carpeta v2, reuso vendor y cadena vertical); §2 → Task 4 (tipos, contigüidad, snap, subdivisión ~180s en prompt); §3 → Task 5 (roles, ≤60s hard cap, gaps>0.8s vía `build_segments` gap default 0.8, snap); §4 → Task 6 (un pase concat, cortes secos, srt continuo, sin deps nuevas); §5 → Task 7 (frames, criterio, fallback documentado, piloto Concesionario 798-1527s).
2. **Placeholder scan:** sin TBD/TODO; cada step trae código o comando exacto; `phase_segment` incluye la corrección del doble-offset como código, no como nota.
3. **Type consistency:** `spans` siempre `{"start","end","role"}` (Task 5) y `montage_srt`/`phase_montage` leen `sp["start"]/sp["end"]` (Tasks 3/6); `montages.json` = `{"montages": [{"rank","item","spans","total"}]}` en Task 5 y consumido igual en Task 6; `vertical_vf` (1 span, `[0:v]`) vs `montage_filter` (N spans, `[vcat]`) no se mezclan.
