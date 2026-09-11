# AGENTS.md — cliptrulo

Pipeline local (sin Docker) que convierte lives largos en shorts 9:16: transcribe → elige momentos con Gemini → corta con FFmpeg.

## Comandos (siempre desde la raíz)

```powershell
$py = ".\.venv\Scripts\python.exe"
& $py local_transcribe.py "downloads\VIDEO.mp4" "downloads\video_words.json"
& $py openshorts_run.py --words "downloads\video_words.json" --out "output\mitad\shorts.json" --duration 1836
& $py openshorts_cut.py --video "downloads\VIDEO.mp4" --words "downloads\video_words.json" --shorts "output\mitad\shorts.json" --out "output\mitad"
& $py show_shorts.py "downloads\video_words.json" "output\mitad\shorts.json" 0
& $py openshorts_v2.py --video "downloads\MITAD.mp4" --words "downloads\mitad_words.json" --section "MM:SS-MM:SS" --offset N --out "output\v2\seccion" --phase all
```

- Setup: Python 3.12 + `.\.venv\Scripts\pip.exe install -r requirements.txt` (`faster-whisper`, `google-genai`, `python-dotenv`). FFmpeg se autodetecta en PATH o paquete WinGet de Gyan (`find_ffmpeg()` en `openshorts_common.py`, usado por cut/transcribe).
- Orden obligatorio: transcribir (1 vez) → run (score → detail) → cut → show. `*_words.json` en `downloads/` es caché: no retranscribir salvo que cambie el video.
- No hay tests, lint, typecheck ni CI. No hay `opencode.json`.

## Reglas del pipeline

- Modelo: `gemini-3.1-flash-lite` hardcodeado en `openshorts_run.py:33`. No usar `gemini-2.5-*` (dado de baja) ni `3.6-flash` (503 por saturación).
- `openshorts_run.py` lee `GEMINI_API_KEY` parseando `.env` a mano (`:36-37`), no usa dotenv. No commitear `.env`.
- `--duration` debe ser la duración real del video pasado en `--video`. Defaults: `--min-clips 3 --max-clips 5` (normal), `6-10` + `--shortlist-cap 14` (filtro libre). Clips siempre 15–59s; `cut` extiende a 15s mínimo (`openshorts_cut.py:68-69`).
- Timestamps de `shorts.json` son relativos al `--video` dado. Si el video es un recorte, sumar offset manual (ej. segunda mitad offset 2713s). `show_shorts.py` acepta offset como 3er arg e imprime tiempo archivo vs absoluto.
- `vendor/openshorts/` es submódulo del upstream (fijado a un commit) y solo lectura: reutilizar prompts, schemas, `build_transcript_windows` / `snap_clip_to_words` / `trim_to_best`. No editarlo, no seguir su `CLAUDE.md` (habla de Docker/FastAPI/React: no aplica aquí). Clon fresco: `git clone --recurse-submodules` o `git submodule update --init`.
- Formato standard de salida (fijado en `openshorts_common.py: STD_CODEC_ARGS/fps_args`): `1080x1920` mp4, H.264 yuv420p + faststart, AAC 48kHz 128k. FPS de origen si está en 23–60, si no se fuerza 30. Subtítulos en `.srt` al lado del mp4, nunca quemados.
- `openshorts_v2.py` arma shorts por sección en 3 fases (`segment → highlight → montage`, `--phase all` o por fase). Salida `output\v2\<seccion>\`: `items.json`, `montages.json` (cada clip `total` ≤59s, spans con rol `presentacion`/`mejor_reaccion`/`comentarios`), `clip_NN.mp4` crudo 16:9 + `clip_NN.srt` (el vertical va en Shotcut, ver abajo).
- Criterio de spans v2 (vale para manual y para el prompt): bloques CONTINUOS de 2-3 spans por clip (presentación + reacción en un bloque + UN bloque de comentarios unificado al final; sin rol comentarios si no hay lectura real). Las pausas internas se conservan; se corta solo en pausas reales verificadas con word timestamps. No abrir spans en la costura entre items (el segmentado puede partir un visionado continuo: arrancar donde empieza el video propio). `total` ≤59s porque el snap a palabras suma ~1s. Si no entra en 60s, recortar presentación o cola de comentarios, nunca picar la reacción.
- La `--section` va en tiempo del vivo y `--offset` la convierte a tiempo de archivo.
- Si el streamer oculta la webcam en un tramo (PiP sale negro), ese clip se monta con `--no-cam` (verificar presencia de la cámara en frames del rango del clip, no asumir).
- Si Gemini bloquea una sección con `PROHIBITED_CONTENT`, partirla en 2 sub-secciones y segmentar cada una por separado (el bloqueo suele dispararlo el payload combinado, no un tramo puntual); reintentar idéntico no sirve.

## Gotchas FFmpeg (verificados)

- Filtro `subtitles` no acepta rutas Windows con `:` (letra de unidad). Pasar solo el basename del `.srt` y correr con `cwd=out` (`openshorts_cut.py:78-91`).
- `MarginV` del filtro `subtitles` va en unidades internas ASS (base 288px), no en píxeles de video: valores ≥350 sacan el texto de pantalla sin error. Fix pendiente: `original_size=1080x1920` + `force_style` chico.
- PiP webcam: el recorte se mide por live (título + caja de la cara con sus bordes) y se expresa en fracciones de `iw`/`ih` para que escale a cualquier resolución. Ojo: no asumir 1920x1080, la fuente puede ser 1280x720 (coords absolutas de un tamaño rompen el otro).
- El contenido vertical (TikTok/IG) se mueve si el streamer redimensiona el navegador mid-live: el crop base acepta `--shift0` → `--shift1` (fracciones del ancho de crop) con paneo en `[--pan-t0,--pan-t0+--pan-dur]` segundos del clip. Calibrar por clip: muestrear frames al inicio/medio/fin, medir bordes del contenido y derivar shift = (centro_contenido - centro_frame) / ancho_crop (negativo si va a la izquierda); si cambia mid-clip usar paneo (o inverso), si no fijo con `--shift0 == --shift1`. Flags: `--only N` (un short), `--only-9x16` (reusa .srt, saltea mp4 16:9 y frame).
- `to_srt()` agrupa palabras en líneas de ~42 chars o 2.5s (`openshorts_cut.py:33-49`). Transcripción local: `faster-whisper` modelo `base`, `language="es"`, `word_timestamps=True`, CPU int8 (`local_transcribe.py:43-46`).

## Shotcut MCP (segunda fase: vertical + PiP)
- El primer pipeline termina en crudo 16:9 + `.srt`. El vertical se arma en Shotcut: proyecto `1080x1920` 30fps, V1 = crop ventana + `affine`, V2 = crop caja cámara + `affine` a `260x292` en `(800,20)`, compositing por defecto (qtblend V1↔V2 ya cableado).
- Receta `affine` que funciona: SOLO props `transition.rect` + `transition.fill=1` + `transition.distort=0` (las `rect`/`fill` sin prefijo sobran; el rect de 5 tokens con `100%` rompe el filtro).
- Workarounds del harness (payloads de inspect/discovery no llegan legibles): leer schemas en `C:\Users\saggassa\Desktop\shotcut-mcp\shotcut_mcp\project_document.py`; `expected_revision` = sha256 del `.mlt` en disco (`Get-FileHash`); el servidor NO acepta `force`. `render_preview`/`render_contact_sheet` siempre con `output_path` explícito para poder verlos.
- No exportar sin pedido explícito (`start_render` solo con aprobación).
