# Cliptrulo

Pipeline local para convertir lives en proyectos verticales editables, organizado en dos skills.

## 1. Preparar: `cortar-shorts`

Recibe un video local o URL y secciones del vivo. Prepara MP4 por sección, extrae WAV mono 16 kHz, transcribe con Chamu CLI (`small`) y adapta los resultados.

Entrega `sections.json` y, por sección, MP4, WAV, `*_chamu.json`, `*_words.json` y `*_silences.json`. Aquí termina este skill: no selecciona ni monta clips.

Los medios y JSONs de cada sección empiezan en 0. `sections.json` conserva el mapeo al vivo mediante `vivo_start` y `vivo_end`. Reusar la transcripción si no cambió el medio ni el rango.

## 2. Seleccionar y montar: `elegir-clips`

Recibe esa entrega. El agente lee la transcripción y selecciona momentos graciosos con contexto, reacción y cierre; produce `items.json` y `picks.json`. No hay selector automático alternativo.

`montage_from_picks.py` valida los picks y genera `montages.json`. Después de aprobar la selección, `openshorts_v2.py` corta crudos y subtítulos externos. La única fase disponible es `montage`, también predeterminada.

Luego el agente crea y revisa proyectos Shotcut `1080x1920`, con contenido y webcam encuadrados según el medio real. Entrega `clip_NN.mp4`, `clip_NN.srt`, `clip_NN_vertical.mlt` y previews. Exportación final solo por pedido explícito; no quemar subtítulos.

## Setup

Python 3.12, FFmpeg/FFprobe y Shotcut con MCP. Para descargar videos se necesita yt-dlp. Chamu CLI se prepara con `tools/ensure_chamu_cli.py`; su modelo `small` debe estar disponible antes de transcribir.

```powershell
.\.venv\Scripts\pip.exe install -r requirements.txt
.\.venv\Scripts\python.exe tools/ensure_chamu_cli.py
```

`faster-whisper` se conserva para la utilidad independiente `local_transcribe.py`; no es un fallback del pipeline. No se requieren credenciales de modelos.

`vendor/openshorts` es un submódulo de solo lectura: se reutiliza únicamente el helper puro `snap_clip_to_words`, no sus selectores ni servicios. En un clon nuevo ejecutar `git submodule update --init`.

## Comandos de la segunda etapa

Desde la raíz, con medios y JSONs preparados y la carpeta destino existente; ejemplo para una sección local de 600 segundos:

```powershell
$py = ".\.venv\Scripts\python.exe"
& $py dump_windows.py --words "downloads\SEC_words.json" --silences "downloads\SEC_silences.json" --section "0-600" --out "output\SEC\transcript.txt"
& $py montage_from_picks.py --words "downloads\SEC_words.json" --silences "downloads\SEC_silences.json" --items "output\SEC\items.json" --picks "output\SEC\picks.json" --montages "output\SEC\montages.json"
& $py openshorts_v2.py --video "downloads\SEC.mp4" --words "downloads\SEC_words.json" --section "00:00-10:00" --offset 0 --out "output\SEC" --phase montage
```

No usar los límites del vivo en estos comandos. El cortador solo admite offset 0. No sobrescribir resultados existentes sin autorización.

## Verificación

```powershell
.\.venv\Scripts\python.exe -B -m unittest test_pipeline_contract -v
```

Incluye imports y ayuda sin SDK/credenciales, ausencia del selector anterior y una integración sintética real picks → montages → MP4/SRT con FFmpeg/FFprobe. No transcribe ni exporta Shotcut. No hay lint, typecheck ni CI configurados.
