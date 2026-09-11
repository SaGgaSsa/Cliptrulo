# Elegir clips (sin Gemini, mismos criterios)

La selección de items y spans la hace el agente leyendo la transcripción.
Mismos criterios que usaban los prompts de Gemini (`openshorts_v2lib.py`, referencia).

## Paso 1 — volcar transcripción legible

```powershell
$py = ".\.venv\Scripts\python.exe"
& $py dump_windows.py --words "downloads\<SEC>_words.json" --silences "downloads\<SEC>_silences.json" --section A-B --out "output\<SEC>\transcript.txt"
```

`A-B` en segundos de archivo (= tiempo del vivo si offset 0). Leer el `.txt` y marcar
pausas reales: solo `[SILENCIO]` vale como punto de corte.

## Paso 2 — clasificar items (→ `items.json`)

Cubrir TODA la sección con items contiguos sin huecos ni solapes
(`item[i+1].start == item[i].end`, tolerancia 0.5s). Partir items de >180s.
Schema por item: `{"start","end","kind","score","summary"}`.

- `kind`: `presentacion` (presenta video) / `visionado` (corre el video, host callado)
  / `reaccion` (reacciona/comenta lo visto) / `comentarios` (lee chat)
  / `relleno` ( DESCARTAR: silencios, divague, off-topic).
- `score` 0-100 = qué tan gracioso/viral es como short. Si mezcla dos kinds, partir.
  Preferir más items cortos que pocos largos.
- `items.json` = `{"sec_a","sec_b","items":[...]}`.

## Paso 3 — elegir clips (→ `picks.json` → `montages.json`)

Por cada item elegido (top por score, nunca `relleno`):

- 2-3 spans CONTINUOS, `total` ≤59s (el snap suma ~1s; tope duro 60s).
- Orden narrativo: `presentacion` (5-10s) + `mejor_reaccion` (UN bloque continuo
  con el pico) + `comentarios` (UN bloque unificado al final; omitir si no hay
  lectura real de chat).
- Las pausas internas se conservan; cortar SOLO en pausas reales `[SILENCIO]`.
- No abrir spans en la costura entre items (si el item arranca mid-video,
  arrancar donde empieza el video propio).
- Si no entra en 60s: recortar presentación o cola de comentarios, NUNCA la reacción.

`picks.json` = `{"clips": [{"rank": N, "item": {...}, "spans":
[{"start","end","role"}]}]}`. Validar y generar `montages.json`:

```powershell
& $py montage_from_picks.py --words "downloads\<SEC>_words.json" --silences "downloads\<SEC>_silences.json" --items "output\<SEC>\items.json" --picks "output\<SEC>\picks.json" --montages "output\<SEC>\montages.json"
```

El script hace snap a palabras, exige 2-3 spans y `total` ≤59 (falla si pasa:
recortar y reintentar), extiende a 15s si falta, avisa si un corte cae lejos
de silencios, y CONSERVA ranks no mencionados (clip ya validado queda intacto).

## Paso 4 — cortar crudo

```powershell
& $py openshorts_v2.py --video "downloads\<SEC>.mp4" --words "downloads\<SEC>_words.json" --section "<MM:SS-MM:SS vivo>" --offset 0 --out "output\<SEC>" --phase montage [--only N]
```

Verificar: ffprobe (`h264`, resolución fuente, ≤59s) + 1 frame inicio/fin.
Salida por clip: `clip_NN.mp4` crudo 16:9 + `clip_NN.srt`. El vertical va en Shotcut.
