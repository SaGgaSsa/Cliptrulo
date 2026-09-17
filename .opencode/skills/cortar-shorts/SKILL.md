---
name: cortar-shorts
description: Use when a live video or URL and section list need audio transcription and Chamu JSON preparation before clip selection
---

# Preparar secciones y JSONs (cortar-shorts)

## Alcance
Skill 1: video + secciones → medios por sección → audio → Chamu → JSONs. Termina al entregar los medios y JSONs verificados; no selecciona momentos, no corta crudos de clips ni crea proyectos Shotcut. El skill 2, `elegir-clips`, recibe esa entrega.

Todo desde la raíz con `.\.venv\Scripts\python.exe`. Cada sección es su propia timeline (tiempos arrancan en 0); el mapeo al vivo vive en `sections.json`.

## Input
- `video` o `url`: archivo local del vivo completo o link para descargarlo. Si el archivo ya es una sección, confirmar su origen temporal antes de recortar.
- `nombre`: slug del episodio (`downloads/<nombre>.mp4`, `downloads/<nombre>_<ID>_*.json`, `output/v2/<ID_<slug>>/`).
- `secciones`: lista `[{vivo: "MM:SS-MM:SS", slug}]` en tiempo del vivo.
- Binario `chamu-cli`: lo asegura el paso 0 (versión de GitHub, solo descarga si hay run nuevo).
- Formatos chamu: `--format json --time-offset 0`.

## Preparación (todas las secciones)
Reusar medios y transcripciones existentes si corresponden al mismo video y rango; no retranscribir por cambiar el criterio de clips. Verificar con ffprobe resolución, duración y audio antes de cortar.
0. Asegurar binario: `python tools/ensure_chamu_cli.py` → imprime `CHAMU_CLI=<ruta>` (`UP-TO-DATE` / `DOWNLOADED` / `LOCAL-FALLBACK`; exit 2 = correr `gh auth login`). El exe vive en `tools/chamu-cli/` (commiteado junto a `VERSION.json`; el script solo actualiza si cambia el digest). Usar esa ruta en el paso 3.
1. Si se recibió un archivo local, usarlo sin descargar. Si se recibió URL, bajar vivo completo: `yt-dlp -f "bv*[height<=1080]+ba/b" --merge-output-format mp4 -o "downloads/<nombre>.mp4" <url>` (full + cortes: `--download-sections` igual descarga todo, no ahorra nada).
2. Cortar secciones con seek EXACTO (`-ss` después de `-i`, re-encode `preset fast` — `copy` + seek rápido desplaza tiempos y rompe el mapeo): `ffmpeg -n -v error -i <vivo> -ss {A} -t {D} -c:v libx264 -preset fast -crf 18 -c:a aac "downloads/<nombre>_<ID>.mp4"`. Registrar `sections.json`: `{id, vivo, vivo_start, vivo_end, file, chamu, words, silences, out}`.
3. Audio + transcribir por sección: wav 16kHz mono. Modelo fijo: `small` (`ggml-small.bin`, `--model-dir "%LOCALAPPDATA%\Chamu\models"` explícito; preflight: si falta, fallar). rinde ~1x tiempo real → partir el wav en cuartos de ~6 min, transcribir cada uno con su `--time-offset` absoluto (0, 345, 690, …) y unir con `chamu_merge.py out_chamu.json q1.json q2.json …` (recalcula `silences[]`). stdout a archivo con `cmd /c` (nunca redirect `>` de PowerShell: escribe UTF-16). Exit 0 = ok; 3 = sin voz; 30 min máximo por archivo chamu.
4. Adaptar: `chamu_to_words.py <ID>_chamu.json <ID>_words.json --silences <ID>_silences.json`.
5. Verificar que los JSONs se puedan leer, las palabras estén ordenadas y palabras/silencios estén dentro de la duración del MP4 de sección. Marcar explícitamente secciones sin voz; no inventar palabras.

## Entrega y fin del skill
Entregar `sections.json` y, por sección, MP4, WAV, `*_chamu.json`, `*_words.json` y `*_silences.json`, con rutas existentes y duración verificada. Guardar `sections.json` junto a los medios del episodio; las rutas de sus entradas son relativas a la raíz del repo o absolutas.

Cada entrada conserva `{id, vivo, vivo_start, vivo_end, file, chamu, words, silences, out}`. `chamu` apunta al JSON unido de la sección, nunca a un cuarto; `out` indica la carpeta destino de clips que usará el skill 2. Dividir el audio en partes contiguas sin huecos ni solapes; calcular cada offset desde su inicio real (los números anteriores son ejemplos). Si Chamu devuelve sin voz, verificar su salida y entregar words vacío con aviso; si falta un JSON válido, declarar la sección pendiente en vez de presentarla como lista. `file`, `words` y `silences` comparten tiempo LOCAL de sección, desde 0. Tiempo del vivo = `vivo_start` + tiempo local; los offsets usados al unir cuartos son locales a la sección, no al vivo.

Aquí termina `cortar-shorts`. Si el usuario pidió también los clips, continuar con el skill `elegir-clips` usando esta entrega. Si pidió solo preparar/transcribir, detenerse sin selección, crudos ni Shotcut.

## Common mistakes
- Invocar chamu-cli con redirect `>` de PowerShell 5.1 (escribe UTF-16 y rompe el JSON): llamar desde Python con `subprocess` (bytes → utf-8) o redirigir con `cmd /c`.
- Cortar secciones con `-c copy` o seek rápido (tiempos inexactos, todo lo demás se corre).
- Usar `--offset` distinto de 0 en el flujo nuevo (el offset vive en `sections.json`, no en los comandos).
- Asumir webcam visible sin mirar el rango del clip.
