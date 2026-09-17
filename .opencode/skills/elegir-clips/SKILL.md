---
name: elegir-clips
description: Use when prepared Chamu words and silence JSONs are available and funny highlights, raw cuts, or editable vertical Shotcut clips are requested
---

# Elegir clips y montar en Shotcut

## Alcance y entrada
Skill 2: JSONs preparados → selección de momentos graciosos por el agente → crudos + SRT → proyectos verticales editables en Shotcut. La selección se hace exclusivamente con este criterio, sin selector automático alternativo. No descarga ni retranscribe: si faltan medios o JSONs, volver a `cortar-shorts` para preparar únicamente lo faltante.

Recibir `sections.json` del skill `cortar-shorts` y las entradas elegidas: `file` (MP4 de sección), `words`, `silences`, `chamu`, `vivo_start`, `vivo_end`, `out`. También se aceptan rutas explícitas a MP4/words/silences si se conoce su correspondencia temporal. Resolver rutas desde la raíz del repo; comprobar existencia, duración y que los JSONs correspondan al mismo archivo.

Los timestamps de words, silences, items, picks y montages son LOCALES al MP4 de sección (desde 0). `A=0`, `B=duración real de la sección`; tiempo del vivo = `vivo_start` + tiempo local. Secciones con words vacío no permiten selección desde texto: informar y pedir revisión del medio, no inventar clips.

Si no se pidió una cantidad, proponerla según el material. Conservar los criterios editoriales siguientes; el cortador solo admite `--phase montage` (también es el valor por defecto).

## Paso 1 — volcar transcripción legible

```powershell
$py = ".\.venv\Scripts\python.exe"
& $py dump_windows.py --words "downloads\<SEC>_words.json" --silences "downloads\<SEC>_silences.json" --section A-B --out "output\<SEC>\transcript.txt"
```

`A-B` en segundos LOCALES del archivo de sección; no usar aquí los límites del vivo. Leer el `.txt` y marcar
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
  Corte de split (no cola final): span con `"hard": true` — el fin queda exacto
  en fin de palabra, sin cola ni palabra siguiente (si cae de golpe, outro en
  Shotcut).
- Acortamiento a <60s (standard redes; el crudo ya sale sin silencios, así que
  el acorte es estructural): si el clip trae 2+ payoffs → split por payoff
  (cada parte con presentación mínima y su remate); el browsing entre reels
  (narración de UI, "a ver", reformulaciones) se descarta, no se reparte. Si una
  parte sigue >60s, recortar relleno interno, nunca presentación ni remate.
- Sin tope de 59s (el vertical va en Shotcut): tope blando 180s (Shorts admite
  3 min). El validador agrega ~2s de cola tras la última palabra (hasta la
  próxima o fin del item), salvo span `hard`; si el final cae de golpe, agregar outro mínima en Shotcut.

`picks.json` = `{"clips": [{"rank": N, "item": {...}, "spans":
[{"start","end","role"}]}]}`. Validar y generar `montages.json`:

```powershell
& $py montage_from_picks.py --words "downloads\<SEC>_words.json" --silences "downloads\<SEC>_silences.json" --items "output\<SEC>\items.json" --picks "output\<SEC>\picks.json" --montages "output\<SEC>\montages.json"
```

El script hace snap a palabras, admite 1-6 spans y `total` ≤180s (falla si pasa:
recortar y reintentar), extiende a 15s si falta, agrega ~2s de cola final,
avisa si un corte cae lejos de silencios.

## Confirmación antes del corte
Presentar secciones candidatas, cantidad de clips, resumen y duración estimada. Si el pedido fue solo selección, entregar los JSONs y propuestas y detenerse aquí, antes del paso 4. Para continuar, confirmar qué propuestas cortar salvo que el usuario ya haya aprobado esos picks. Un pedido de clips no autoriza exportación final de Shotcut.

## Paso 4 — cortar crudo
Para el MP4 de sección y JSONs locales usar `--section "00:00-<duración MM:SS>" --offset 0`. Ejemplo: vivo 10:00-20:00 ya recortado a archivo de 600s → `--section "00:00-10:00" --offset 0`. Crear `out` antes de generar archivos; verificar destinos existentes antes de cortar porque el script usa sobrescritura (`-y`).

```powershell
& $py openshorts_v2.py --video "downloads\<SEC>.mp4" --words "downloads\<SEC>_words.json" --section "00:00-<duración MM:SS>" --offset 0 --out "output\<SEC>" --phase montage [--only N]
```

Verificar: ffprobe (`h264`, resolución fuente, ≤180s) + 1 frame inicio/fin.
Salida intermedia por clip: `clip_NN.mp4` crudo 16:9 + `clip_NN.srt`. Continuar con Shotcut salvo que el usuario haya pedido solo selección o crudos.

## Paso 5 — montar vertical editable en Shotcut
1. Probar el crudo con `probe_media` y revisar frames de inicio, medio, fin y cambios de escena. Medir área de contenido y webcam sobre la resolución real; no copiar coordenadas de otro episodio sin verificar. Si no hay webcam, omitir V2 en ese tramo. Descartar en revisión los clips donde watermarks tapen contenido.
2. Crear `clip_NN_vertical.mlt` en `out` con `create_project`, perfil standard `1080x1920` 30fps. V1 contiene el crudo; V2 duplica únicamente los tramos con webcam y queda muteada para no duplicar audio. Los tiempos del proyecto parten de 0 en el crudo montado, no de los timestamps de picks.
3. Inspeccionar el proyecto guardado antes de editar; usar su `expected_revision`, `item_ref` y schemas de `shotcut_capabilities`. Aplicar crop en píxeles de fuente y `affine` con `rect` y `transition.rect` iguales (`x y w h`), `transition.fill=1`, `transition.distort=0`. V1 encuadra el contenido sin deformar; V2 encuadra la cámara como PiP. Medir y partir V1/V2 independientemente cuando cambie su geometría. Recetas y herramientas auxiliares: sección Shotcut MCP de `AGENTS.md`.
4. Validar proyectos si su estado es desconocido; cada edición MCP ya valida. Renderizar y mostrar contact sheet, más previews exactos alrededor de switches. Corregir encuadre, sincronía y ausencia de cámara antes de entregar. No abrir GUI ni sobrescribir proyectos sin autorización; si hay cambios GUI pendientes, pedir guardar antes de editar.

## Entrega y fin del skill
Para el flujo completo, entregar por sección `items.json`, `picks.json`, `montages.json`, crudos `clip_NN.mp4`, subtítulos externos `clip_NN.srt`, proyectos `clip_NN_vertical.mlt` y previews. Si el pedido fue solo selección o solo crudos, entregar únicamente los artefactos de esas etapas. Los subtítulos nunca se queman.

Terminar con los proyectos editables revisados. Exportar video final solo ante pedido explícito: `start_render` con revisión, destino y preset, sin sobrescribir sin permiso; monitorear hasta estado terminal y entregar tanto el render como su snapshot editable.

## Errores frecuentes
- Repetir Chamu pese a que los JSONs del mismo medio ya existen.
- Usar límites del vivo con `--offset 0` sobre una sección recortada.
- Intentar delegar la selección en el cortador: solo procesa los montages ya elegidos por el agente.
- Dar por terminado el skill en los crudos cuando se pidieron clips verticales.
- Confundir creación del proyecto o preview con aprobación para exportar.
