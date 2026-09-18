# PROMPT_SELECCIÓN v1 — crudos continuos (sin edición interna)

Criterio fijo para elegir clips. Si una sección sale mal de forma
sistemática, se corrige ESTE archivo (nueva versión abajo) en vez de
parchear JSONs a mano.

## Entrada
- `transcript.txt` (ventanas legibles con `[SILENCIO]` como punto de corte).
- `items.json` (índice de scoring, cobertura contigua de la sección).
- `words.json` / `silences.json` (tiempos locales al MP4 de sección, desde 0).

## Salida: qué es un crudo
- UN único tramo continuo `[start, end]`, con pausas, muletillas y silencios
  intactos. Cero cortes internos, cero spans, cero roles.
- Duración 60–180s (falla el validador fuera de rango; el agente ajusta).
- Mínimo 3 clips por sección, rankeados por score. Pueden cruzar items.
- Cada clip = arco COMPLETO standalone: contexto suficiente (qué mira o lee),
  reacción COMPLETA y remate si lo hay. Nunca frase aislada, remate sin
  contexto ni reacción cortada.
- Si lee comentarios/chat, incluir el comentario necesario para entender la
  respuesta. El browsing entre reels ("a ver", narración de UI,
  reformulaciones) queda DENTRO del crudo si está en medio; se recorta después
  en edición, no acá.

## Cómo elegir
1. Score 0-100 = qué tan gracioso/viral es como short (no prolijidad técnica).
2. Marcar inicio en comienzo natural (presentación del video o arranque del
   tema) y fin en cierre natural (remate, risa que decae, pase al siguiente
   video). Preferir 10s de más con cierre antes que 10s de menos sin cierre.
3. Bordes van en MITAD de silencio o pausa, nunca dentro de palabra. La última
   palabra entra entera (el validador la incluye y avisa si el corte cae lejos
   de silencios verificados).
4. Overlap entre clips: evitar salvo que cada parte tenga su propio remate.
5. `hook`: frase textual corta (lo que se oye) que vende el clip.

## Schema picks.json
```json
{"clips": [{"rank": 1, "start": 525.2, "end": 632.0, "score": 72,
  "hook": "cita textual breve",
  "summary": "qué pasa y por qué cierra solo"}]}
```

## Anti-patrones (rechazar)
- Resumir 2 payoffs lejanos en un clip >180s: elegir el mejor, no estirar.
- Cortar justo cuando la reacción sigue o el remate queda afuera.
- Mover bordes para "limpiar" silencios internos: prohibido en crudo.
- Inventar clips en secciones con words vacío.

## Changelog del criterio
- v1 (2026-09-18): crudo continuo 60–180s, 1 tramo, sin spans/roles/cola.
  Reemplaza montaje multi-span con silencios eliminados.
