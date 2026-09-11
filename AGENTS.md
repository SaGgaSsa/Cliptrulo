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

- Selección de clips SIN Gemini: la hace el agente con el skill `elegir-clips` (mismos criterios: items contiguos + score; cada clip es un arco COMPLETO standalone — contexto + reacción + remate, 1-6 spans, sin tope 59s salvo 180s de Shorts; silencios/baches se saltean, cola ~2s tras la última palabra). `montage_from_picks.py` valida picks y arma `montages.json`; `openshorts_v2.py --phase montage` corta crudo. (`openshorts_run.py` v1 y las fases `segment`/`highlight` con Gemini quedan fuera del flujo.)
- `openshorts_run.py` lee `GEMINI_API_KEY` parseando `.env` a mano (`:36-37`), no usa dotenv. No commitear `.env`.
- `--duration` debe ser la duración real del video pasado en `--video`. Defaults: `--min-clips 3 --max-clips 5` (normal), `6-10` + `--shortlist-cap 14` (filtro libre). Clips siempre 15–59s; `cut` extiende a 15s mínimo (`openshorts_cut.py:68-69`).
- Timestamps de `shorts.json` son relativos al `--video` dado. Si el video es un recorte, sumar offset manual (ej. segunda mitad offset 2713s). `show_shorts.py` acepta offset como 3er arg e imprime tiempo archivo vs absoluto.
- `vendor/openshorts/` es submódulo del upstream (fijado a un commit) y solo lectura: reutilizar prompts, schemas, `build_transcript_windows` / `snap_clip_to_words` / `trim_to_best`. No editarlo, no seguir su `CLAUDE.md` (habla de Docker/FastAPI/React: no aplica aquí). Clon fresco: `git clone --recurse-submodules` o `git submodule update --init`.
- Formato standard de salida (fijado en `openshorts_common.py: STD_CODEC_ARGS/fps_args`): `1080x1920` mp4, H.264 yuv420p + faststart, AAC 48kHz 128k. FPS de origen si está en 23–60, si no se fuerza 30. Subtítulos en `.srt` al lado del mp4, nunca quemados.
- `openshorts_v2.py` arma shorts por sección: `items.json` (agente, skill `elegir-clips`), `montages.json` (valida `montage_from_picks.py`), `clip_NN.mp4` crudo 16:9 + `clip_NN.srt` (`--phase montage`; el vertical va en Shotcut, ver abajo). Sin tope 59s: cada clip es un arco completo (tope blando 180s de Shorts).
- Criterio de clips (skill `elegir-clips`): cada clip es un arco COMPLETO standalone — contexto + reacción + remate, 1-6 spans con los momentos que dicen algo (silencios/baches se saltean, el montaje los elimina); si lee comentarios, incluir el necesario para entender la respuesta; cola ~2s tras la última palabra (o outro mínima en Shotcut). Cortes en mitad de silencio, última palabra siempre entera (hasta la siguiente si cae en borde: el `.srt` incluye palabras con `start <= fin`). Sin tope 59s salvo 180s de Shorts.
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
- Receta `affine` que funciona: props `rect` + `transition.rect` EN SYNC (`"x y w h"`) + `transition.fill=1` + `transition.distort=0` (el filtro lee `rect`; Shotcut lo agrega al abrir: si difieren gana el viejo. El rect de 5 tokens con `100%` rompe el filtro). `crop` va en PÍXELES del fuente, no fracciones.
- Posición STANDARD EP2 = reacción a video en pantalla completa + cámara normal (layout fijo; recalcular por video si cambia): V1 crop a mano `left=386 top=87 right=386 bottom=99` + affine `0 0 1080 1920` con `distort=1` (llena todo el 9:16 aunque estire ~2.3x vertical); V2-cam crop `left=1632 top=48 right=51 bottom=687` (título CHITRULO + caja al borde cyan, sin gris) + affine `760 20 300 437` con `distort=0` (PiP arriba-derecha).
- Workarounds del harness (payloads de inspect/discovery no llegan legibles): leer schemas en `C:\Users\saggassa\Desktop\shotcut-mcp\shotcut_mcp\project_document.py`; `expected_revision` = sha256 del `.mlt` en disco (`Get-FileHash`); el servidor NO acepta `force`. `render_preview`/`render_contact_sheet` siempre con `output_path` explícito para poder verlos.
- No exportar sin pedido explícito (`start_render` solo con aprobación).
