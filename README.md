# Cliptrulo

Pipeline propio para convertir lives largos de Chitrulo (reacciones a TikToks/reels)
en shorts verticales 9:16 listos para TikTok / Reels / Shorts.

Usa el detector de momentos de [OpenShorts](https://github.com/mutonby/openshorts)
(`vendor/openshorts`, MIT) con Gemini 3.1 Flash-Lite, más empaquetado propio con FFmpeg
(recorte vertical + webcam en picture-in-picture + subtítulos quemados).

## Estructura

```text
cliptrulo/
├── vendor/openshorts/      # cerebro: prompts, schemas, windowing, word-snapping (solo lectura)
├── openshorts_run.py       # selección de momentos en 2 pasadas (score → detail) con Gemini
├── openshorts_cut.py       # corte 16:9 + 9:16 (PiP webcam + subtítulos) + frame de control
├── local_transcribe.py     # transcripción local con faster-whisper → words JSON
├── show_shorts.py          # muestra hook/título/transcripción de cada short
├── downloads/              # videos fuente + transcripts cacheados (*_words.json)
├── output/                 # clips generados (16:9, 9:16, .srt, manifest/shorts.json)
├── .env                    # GEMINI_API_KEY (no commitear)
└── requirements.txt
```

## Setup (Windows)

Requiere Python 3.12 y FFmpeg (se autodetecta en PATH o en el paquete WinGet de Gyan).

```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -m venv .venv
.\.venv\Scripts\pip.exe install -r requirements.txt
# .env ya trae GEMINI_API_KEY configurada
```

> Clon fresco: `git clone --recurse-submodules <url>` (o `git submodule update --init`
> si ya clonaste). `vendor/openshorts` es un submódulo del upstream: no editarlo.

## Uso (siempre desde la raíz del proyecto)

```powershell
$py = ".\.venv\Scripts\python.exe"

# 1. Transcribir (una sola vez por video)
& $py local_transcribe.py "downloads\VIDEO.mp4" "downloads\video_words.json"

# 2. Elegir momentos (filtro normal: 3-5 clips; libre: 6-10)
& $py openshorts_run.py --words "downloads\video_words.json" `
    --out "output\mitad\shorts.json" --duration 1836

# 3. Cortar y empaquetar
& $py openshorts_cut.py --video "downloads\VIDEO.mp4" `
    --words "downloads\video_words.json" `
    --shorts "output\mitad\shorts.json" --out "output\mitad"

# 4. Revisar qué dice cada clip
& $py show_shorts.py "downloads\video_words.json" "output\mitad\shorts.json" 0
# (el 3er arg es el offset en segundos si el video es un recorte del original)
```

## Notas

- Modelo de análisis: `gemini-3.1-flash-lite` (el `gemini-2.5-*` fue dado de baja; el
  `3.6-flash` suele dar 503 por saturación).
- Timestamps de `shorts.json` son relativos al video pasado en `--video`. Si es un
  recorte, sumar el offset (ej. segunda mitad empieza en 2713s = 45:13 del original).
- Subtítulos: el filtro `subtitles` de FFmpeg interpreta `MarginV` en unidades de la
  resolución interna del ASS (288px), no en píxeles del video. Valores ≥350 los sacan
  de pantalla sin error. Fix pendiente: `original_size=1080x1920` + `force_style` chico.
- PiP de la webcam: recorte fijo `235x250+1670+8` del 1920x1080 (estable en este live;
  verificar si cambia el layout).
- Transcripts `*_words.json` son caché: no retranscribir salvo que cambie el video.
