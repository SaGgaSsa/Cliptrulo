---
name: cortar-shorts
description: Use when turning a streamed live into vertical shorts from a video link and section list, or when asked for clips, sections, highlights or montages from a live
---

# Cortar Shorts

## Overview
Pipeline por sección: bajar vivo → cortar secciones → transcribir con chamu-cli → agente elige clips → montaje. Todo desde la raíz con `.\.venv\Scripts\python.exe`. Cada sección es su propia timeline (tiempos arrancan en 0); el mapeo al vivo vive en `sections.json`.

## Input
- `url`: link del vivo.
- `nombre`: slug del episodio (`downloads/<nombre>.mp4`, `downloads/<nombre>_<ID>_*.json`, `output/v2/<ID_<slug>>/`).
- `secciones`: lista `[{vivo: "MM:SS-MM:SS", slug}]` en tiempo del vivo.
- `clips`: cantidad por sección (mínimo 3).
- Binario `chamu-cli`: lo asegura el paso 0 (versión de GitHub, solo descarga si hay run nuevo).
- Formatos chamu: `--format json --time-offset 0`.

## Fase barata (todas las secciones)
0. Asegurar binario: `python tools/ensure_chamu_cli.py` → imprime `CHAMU_CLI=<ruta>` (`UP-TO-DATE` / `DOWNLOADED` / `LOCAL-FALLBACK`; exit 2 = correr `gh auth login`). El exe vive en `tools/chamu-cli/` (commiteado junto a `VERSION.json`; el script solo actualiza si cambia el digest). Usar esa ruta en el paso 3.
1. Bajar vivo completo: `yt-dlp -f "bv*[height<=1080]+ba/b" --merge-output-format mp4 -o "downloads/<nombre>.mp4" <url>` (full + cortes: `--download-sections` igual descarga todo, no ahorra nada).
2. Cortar secciones con seek EXACTO (`-ss` después de `-i`, re-encode `preset fast` — `copy` + seek rápido desplaza tiempos y rompe el mapeo): `ffmpeg -y -v error -ss {A} -i <vivo> -t {D} -c:v libx264 -preset fast -crf 18 -c:a aac "downloads/<nombre>_<ID>.mp4"`. Registrar `sections.json`: `{id, vivo, vivo_start, vivo_end, file, chamu, words, silences, out}`.
3. Audio + transcribir por sección: wav 16kHz mono, luego `<CHAMU_CLI> --model large-v3-turbo-q5_0 --model-dir "%LOCALAPPDATA%\Chamu\models" --language es --format json --time-offset 0 <ID>.wav` con stdout a `<ID>_chamu.json` (exit 0 = ok; 3 = sin voz; 30 min máximo por archivo). Modelo fijo: `ggml-large-v3-turbo-q5_0.bin` ya descargado ahí; preflight: si falta, fallar (lo provee la app Chamu). Fallback rápido → `small` (`ggml-small.bin`, misma carpeta).
4. Adaptar: `chamu_to_words.py <ID>_chamu.json <ID>_words.json --silences <ID>_silences.json`.
5. `openshorts_v2.py --video <ID>.mp4 --words <ID>_words.json --section "0:00-<D>" --offset 0 --out <out> --phase segment` → `items.json`.

## Split (decisión, parte cara)
El agente propone qué secciones (y cuántos clips) valen la pena desde los `items.json`; el usuario confirma. Solo las elegidas siguen.

## Fase cara (solo elegidas)
1. `--phase highlight --clips N`. Exigir spans CONTINUOS (2-3 por clip, pausas adentro, corte solo en pausas reales = `silences[]` del chamu JSON, UN bloque comentarios al final u omitirlo, `total` ≤59s, no abrir en costuras entre items).
2. Calibrar crop con frames inicio/medio/fin: shift = (centro_contenido − centro_frame) / ancho_crop; verificar webcam en cada rango (`--no-cam` si está oculta).
3. `--phase montage --shift0 X --shift1 Y [--no-cam]`. Verificar: ffprobe (1080x1920, h264, aac 48kHz, ≤59s) + frame apertura/mid.

## Standard de salida
`clip_01_9x16.mp4` + `clip_01.srt` al lado (nunca quemados) + `items.json`/`montages.json` por carpeta de sección. Watermarks de plataforma vienen en la fuente: descartar en revisión los clips donde tapen contenido.

## Common mistakes
- Invocar chamu-cli con redirect `>` de PowerShell 5.1 (escribe UTF-16 y rompe el JSON): llamar desde Python con `subprocess` (bytes → utf-8) o redirigir con `cmd /c`.
- Cortar secciones con `-c copy` o seek rápido (tiempos inexactos, todo lo demás se corre).
- Usar `--offset` distinto de 0 en el flujo nuevo (el offset vive en `sections.json`, no en los comandos).
- Montar (`all` o `montage`) antes de calibrar shift con frames.
- Asumir webcam visible sin mirar el rango del clip.
