"""v2 pure helpers: pydantic schemas + Gemini prompt templates. No side effects."""
from typing import List, Literal
from pydantic import BaseModel, Field


class SegmentItem(BaseModel):
    start: float
    end: float
    kind: Literal["presentacion", "visionado", "reaccion", "comentarios", "relleno"]
    score: int = Field(ge=0, le=100)
    summary: str


class SegmentResponse(BaseModel):
    items: List[SegmentItem]


class HighlightSpan(BaseModel):
    start: float
    end: float
    role: Literal["presentacion", "mejor_reaccion", "comentarios"]


class HighlightResponse(BaseModel):
    spans: List[HighlightSpan]


SEGMENT_PROMPT_TEMPLATE = """
You are a senior short-form video editor for a Spanish-language reaction live stream.
Below is the transcript of ONE section of the stream, as JSON windows
[{{"id","start","end","text"}}]. Timestamps are ABSOLUTE SECONDS of the source file.

TIME CONTRACT — STRICT:
- {sec_a} <= start < end <= {sec_b}. Numbers with up to 3 decimals.
- Items must be CONTIGUOUS and cover the whole [{sec_a},{sec_b}] range with no gaps
  and no overlaps: item[i+1].start == item[i].end (up to 0.5s tolerance).
- Split items longer than ~180s into smaller ones.

Classify each item with kind:
- presentacion: host introduces a video about to be shown
- visionado: the video itself is playing, host mostly quiet
- reaccion: host reacts/laughs/comments on what was just shown
- comentarios: host reads or answers chat comments
- relleno: silences, rambling, off-topic — will be discarded

score 0-100 = how funny/viral the item is as short-form material.
If an item mixes two kinds, split it. Prefer more, shorter items over few long ones.

Windows:
{windows_json}
"""

HIGHLIGHT_PROMPT_TEMPLATE = """
You are a senior short-form video editor. Below is the transcript of ONE item
(a single video the host presents and reacts to), as JSON windows
[{{"id","start","end","text"}}]. Timestamps are ABSOLUTE SECONDS of the source file.

TIME CONTRACT — STRICT:
- {item_a} <= start < end <= {item_b}. Numbers with up to 3 decimals.
- Every span must be 3-25s long. Return 2-5 spans, total <= 60s.
- Order spans chronologically. Roles in narrative order when possible:
  presentacion first (how the host introduces the video, 5-10s),
  then mejor_reaccion (the peak moment(s)),
  then comentarios (chat reads that add something — not all of them).

Transcript:
{windows_json}
"""
