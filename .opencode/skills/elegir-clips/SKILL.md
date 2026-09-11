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

Cada clip debe funcionar SOLO: suficiente contexto para entender qué mira o
lee, la reacción COMPLETA y el remate si lo hay. No cortar demasiado justo:
preferir un clip más largo pero completo antes que uno corto sin cierre.

- Priorizar: reacción clara/graciosa/inesperada; que se entienda qué la provocó;
  comienzo natural y final claro; no terminar mientras la reacción sigue; si lee
  comentarios, incluir el comentario necesario para entender la respuesta.
- Evitar: una frase aislada, un remate sin contexto, una reacción cortada.
- Arco típico (todo entra en UN clip): presentación del video + chiste/reacción +
  lectura de comentarios + pase al siguiente video (ese pase es el final natural).
- Spans = momentos con contenido (1-6 por clip, roles `presentacion` /
  `mejor_reaccion` / `comentarios`, orden libre). Los silencios y baches se
  saltean: el montaje los elimina y arma un solo video continuo.
- Criterio de tiempos (lo aplica el validador): los cortes van en MITAD de
  silencio, nunca en borde ni dentro de palabra; la última palabra entra
  siempre entera (si el corte cae en su borde, se incluye hasta la siguiente).
- Sin tope de 59s (el vertical va en Shotcut): tope blando 180s (Shorts admite
  3 min). El validador agrega ~2s de cola tras la última palabra (hasta la
  próxima o fin del item); si el final cae de golpe, agregar outro mínima en Shotcut.

`picks.json` = `{"clips": [{"rank": N, "item": {...}, "spans":
[{"start","end","role"}]}]}`. Validar y generar `montages.json`:

```powershell
& $py montage_from_picks.py --words "downloads\<SEC>_words.json" --silences "downloads\<SEC>_silences.json" --items "output\<SEC>\items.json" --picks "output\<SEC>\picks.json" --montages "output\<SEC>\montages.json"
```

El script hace snap a palabras, admite 1-6 spans y `total` ≤180s (falla si pasa:
recortar y reintentar), extiende a 15s si falta, agrega ~2s de cola final,
avisa si un corte cae lejos de silencios.

## Paso 4 — cortar crudo

```powershell
& $py openshorts_v2.py --video "downloads\<SEC>.mp4" --words "downloads\<SEC>_words.json" --section "<MM:SS-MM:SS vivo>" --offset 0 --out "output\<SEC>" --phase montage [--only N]
```

Verificar: ffprobe (`h264`, resolución fuente, ≤180s) + 1 frame inicio/fin.
Salida por clip: `clip_NN.mp4` crudo 16:9 + `clip_NN.srt`. El vertical va en Shotcut.
