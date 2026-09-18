---
name: elegir-clips
description: Use when prepared Chamu words and silence JSONs are available and funny highlights, raw cuts, or editable vertical Shotcut clips are requested
---

# Elegir clips y montar en Shotcut

## Alcance y entrada
Skill 2: JSONs preparados → selección de momentos graciosos por el agente → crudos + SRT → proyectos verticales editables en Shotcut. La selección se hace exclusivamente con este criterio, sin selector automático alternativo. No descarga ni retranscribe: si faltan medios o JSONs, volver a `cortar-shorts` para preparar únicamente lo faltante.

Recibir `sections.json` del skill `cortar-shorts` y las entradas elegidas: `file` (MP4 de sección), `words`, `silences`, `chamu`, `vivo_start`, `vivo_end`, `out`. También se aceptan rutas explícitas a MP4/words/silences si se conoce su correspondencia temporal. Resolver rutas desde la raíz del repo; comprobar existencia, duración y que los JSONs correspondan al mismo archivo.

Los timestamps de words, silences, items, picks y montages son LOCALES al MP4 de sección (desde 0). `A=0`, `B=duración real de la sección`; tiempo del vivo = `vivo_start` + tiempo local. Secciones con words vacío no permiten selección desde texto: informar y pedir revisión del medio, no inventar clips.

Si no se pidió una cantidad, proponerla según el material (mínimo 3 clips por
sección). El criterio vive en `PROMPT_SELECCION.md` (misma carpeta del skill):
aplicarlo tal cual; si una sección falla de forma sistemática, corregir el
prompt y versionarlo, no parchear JSONs a mano. El cortador usa
`--phase crudo` sobre `clips.json`.

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

## Paso 3 — elegir crudos (→ `picks.json` → `clips.json`)

Aplicar `PROMPT_SELECCION.md`: cada clip es UN único tramo continuo
`[start, end]` de 60–180s, con pausas y silencios intactos. Cero cortes
internos, cero spans, cero roles. Arco completo standalone (contexto +
reacción completa + remate); si lee comentarios, incluir el necesario para
entender la respuesta. Bordes en mitad de silencio, última palabra entera.

`picks.json` = `{"clips": [{"rank": N, "start", "end", "score", "hook",
"summary"}]}`. Validar y generar `clips.json`:

```powershell
& $py crudo_from_picks.py --words "downloads\<SEC>_words.json" --silences "downloads\<SEC>_silences.json" --items "output\<SEC>\items.json" --picks "output\<SEC>\picks.json" --clips "output\<SEC>\clips.json"
```

El script hace snap a palabras, exige tramo único de 60–180s (falla si no:
ajustar y reintentar), avisa si un corte cae lejos de silencios y pide mínimo
3 clips por sección. Si el criterio falla sistemáticamente, versionar
`PROMPT_SELECCION.md` antes de seguir.

## Confirmación antes del corte
Presentar secciones candidatas, cantidad de clips, resumen y duración estimada. Si el pedido fue solo selección, entregar los JSONs y propuestas y detenerse aquí, antes del paso 4. Para continuar, confirmar qué propuestas cortar salvo que el usuario ya haya aprobado esos picks. Un pedido de clips no autoriza exportación final de Shotcut.

## Paso 4 — cortar crudo
Para el MP4 de sección y JSONs locales usar `--section "00:00-<duración MM:SS>" --offset 0`. Ejemplo: vivo 10:00-20:00 ya recortado a archivo de 600s → `--section "00:00-10:00" --offset 0`. Crear `out` antes de generar archivos; verificar destinos existentes antes de cortar porque el script usa sobrescritura (`-y`).

```powershell
& $py openshorts_v2.py --video "downloads\<SEC>.mp4" --words "downloads\<SEC>_words.json" --section "00:00-<duración MM:SS>" --offset 0 --out "output\<SEC>" --phase crudo [--only N]
```

Verificar: ffprobe (`h264`, resolución fuente, ≤180s) + 1 frame inicio/fin.
Salida intermedia por clip: `clip_NN.mp4` crudo 16:9 + `clip_NN.srt`. Continuar con Shotcut salvo que el usuario haya pedido solo selección o crudos.

## Paso 5 — montar vertical editable en Shotcut
1. Probar el crudo con `probe_media` y revisar frames de inicio, medio, fin y cambios de escena. Medir área de contenido y webcam sobre la resolución real; no copiar coordenadas de otro episodio sin verificar. Si no hay webcam, omitir V2 en ese tramo. Descartar en revisión los clips donde watermarks tapen contenido.
2. Crear `clip_NN_vertical.mlt` en `out` con `create_project`, perfil standard `1080x1920` 30fps. V1 contiene el crudo; V2 duplica únicamente los tramos con webcam y queda muteada para no duplicar audio. Los tiempos del proyecto parten de 0 en el crudo montado, no de los timestamps de picks.
3. Inspeccionar el proyecto guardado antes de editar; usar su `expected_revision`, `item_ref` y schemas de `shotcut_capabilities`. Aplicar crop en píxeles de fuente y `affine` con `rect` y `transition.rect` iguales (`x y w h`), `transition.fill=1`, `transition.distort=0`. V1 encuadra el contenido sin deformar; V2 encuadra la cámara como PiP. Medir y partir V1/V2 independientemente cuando cambie su geometría. Recetas y herramientas auxiliares: sección Shotcut MCP de `AGENTS.md`.
4. Validar proyectos si su estado es desconocido; cada edición MCP ya valida. Renderizar y mostrar contact sheet, más previews exactos alrededor de switches. Corregir encuadre, sincronía y ausencia de cámara antes de entregar. No abrir GUI ni sobrescribir proyectos sin autorización; si hay cambios GUI pendientes, pedir guardar antes de editar.

## Entrega y fin del skill
Para el flujo completo, entregar por sección `items.json`, `picks.json`, `clips.json`, crudos `clip_NN.mp4`, subtítulos externos `clip_NN.srt`, proyectos `clip_NN_vertical.mlt` y previews. Si el pedido fue solo selección o solo crudos, entregar únicamente los artefactos de esas etapas. Los subtítulos nunca se queman.

Terminar con los proyectos editables revisados. Exportar video final solo ante pedido explícito: `start_render` con revisión, destino y preset, sin sobrescribir sin permiso; monitorear hasta estado terminal y entregar tanto el render como su snapshot editable.

## Errores frecuentes
- Repetir Chamu pese a que los JSONs del mismo medio ya existen.
- Usar límites del vivo con `--offset 0` sobre una sección recortada.
- Intentar delegar la selección en el cortador: solo procesa los montages ya elegidos por el agente.
- Dar por terminado el skill en los crudos cuando se pidieron clips verticales.
- Confundir creación del proyecto o preview con aprobación para exportar.
