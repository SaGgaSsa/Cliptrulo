# Spec: Shorts v2 por secciones con montaje de highlights

Fecha: 2026-09-08. Estado: diseño aprobado por secciones (1-5). Piloto: El Concesionario.

## Contexto

La v1 (`openshorts_run.py` + `openshorts_cut.py`) elige momentos por "gracia" con Gemini
y corta un span continuo por clip (15-60s, 9:16). Queda como primera versión, intacta.

La v2 trabaja por **sección del vivo** (ej. WTF Argentina, Relatando, Monotributistas,
El Concesionario). Cada sección muestra varios videos con presentación → visionado →
reacción → lectura de comentarios. Objetivo: 3-4 clips por sección, cada clip un
**montaje** de los mejores fragmentos de un item (video), no el clip completo.

## Sección 1 — Arquitectura y flujo

Script nuevo `openshorts_v2.py` con 3 fases: **segmentar → highlights → montar**.

- Entrada: `--video` (archivo de mitad correspondiente), `--words`, `--section
  "MM:SS-MM:SS"` en tiempo del vivo completo + `--offset` (segundos a restar para
  mapear a tiempo del archivo; 0 si la sección está en la primera mitad), o tiempos
  directos del archivo. Las secciones se pasan por CLI/config por run, nada hardcodeado
  (cada video trae secciones distintas).
- Salida en carpeta nueva `output\v2\<seccion>\`: `items.json` (segmentación),
  `montages.json` (fragmentos por clip), `clip_NN_9x16.mp4` + `.srt`.
- Reusa `vendor/openshorts/` (`build_transcript_windows`, `snap_clip_to_words`) y la
  cadena vertical de `openshorts_cut.py` (crop 9:16 + paneo/shift + PiP webcam + quemado
  de subtítulos) importando funciones, sin duplicar código. La v1 no se toca.

## Sección 2 — Segmentación (pasada 1 de Gemini)

Ventanas de transcript solo de la sección → Gemini devuelve items contiguos que la
cubren completa: `{id, t_start, t_end, tipo, resumen}`.

- Tipos: `presentacion`, `visionado`, `reaccion`, `comentarios`, `relleno`.
- `relleno` (silencios largos, vueltas, off-topic) se descarta y no llega al montaje.
- Tiempos ajustados a bordes de palabra con `snap_clip_to_words` (no partir frases).
- Items de más de ~3 min se subdividen (un video largo con varias reacciones → 2 clips).

## Sección 3 — Highlights (pasada 2 de Gemini)

Por sección se eligen 3-4 items por score de gracia; por item, spans con rol:

- `presentacion`: cómo introduce el video (~5-10s).
- `mejor_reaccion`: el pico (puede ser más de un span).
- `comentarios`: lectura de chat que aporte, no toda.

Reglas duras: total del clip entre 15s y 60s (límite Shorts). Silencios recortados
definiendo spans sobre palabras (gaps >0.8s entre palabras quedan fuera, sin filtro
de audio). Cada span pasa por `snap_clip_to_words`.

## Sección 4 — Montaje

Por clip: extracción de spans con FFmpeg y unión en **una sola pasada** con filtro
`concat` + re-encode a 1080x1920 con la cadena vertical actual (shift/pan calibrado
por sección como en v1: muestrear inicio/medio/fin). Cortes secos, sin transiciones.
Subtítulos: un `.srt` por clip (parciales concatenados con tiempos desplazados),
quemados como hoy. Sin dependencias nuevas: `concat` ya viene en FFmpeg.

## Sección 5 — Verificación y éxito del piloto

Frames inicio/medio/fin + medición de bordes por clip, revisión visual del usuario.
Éxito: 3-4 clips de El Concesionario (rango 58:31-1:10:40 del vivo = 798s-1527s de
`segunda_mitad`, offset 2713s) donde se entienda presentación → reacción sin haber
visto el vivo. Fallback: enfoque asistido manual (propuesta automática + selección
del usuario); `items.json` y el montaje se reusan igual.

## Fuera de alcance (piloto)

Transiciones/efectos entre spans, cambios a la v1, auto-detección de secciones
(las da el usuario), más de una sección a la vez.
