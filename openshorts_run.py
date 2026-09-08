"""Run openshorts' REAL two-pass clip selection (Gemini 3.1 Flash-Lite) natively.

Reuses vendor/openshorts prompts, schemas, windowing and word-snapping:
  gemini_worker.SCORE_PROMPT_TEMPLATE / DETAIL_PROMPT_TEMPLATE / schemas
  clip_selection.build_transcript_windows / snap_clip_to_words /
    clip_count_targets / trim_to_best
Same batching/shortlist logic as main.get_viral_clips.

Usage:
  python openshorts_run.py --words downloads/segunda_mitad_words.json \
      --out output/openshorts_segunda_mitad/shorts.json \
      --duration 1836 --min-clips 6 --max-clips 10 --shortlist-cap 14
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "vendor" / "openshorts"))

from google import genai
from google.genai import types as genai_types

import gemini_worker
from clip_selection import (
    build_transcript_windows,
    snap_clip_to_words,
    trim_to_best,
)

MODEL = "gemini-3.1-flash-lite"
LANGUAGE = "Spanish"

key = [l.split("=", 1)[1].strip()
       for l in open(".env", encoding="utf-8") if l.startswith("GEMINI_API_KEY")][0]
client = genai.Client(api_key=key)


def build_segments(words, gap=0.8, max_len=30.0):
    segs, cur = [], []
    for w in words:
        if cur and (w["start"] - cur[-1]["end"] > gap
                    or w["end"] - cur[0]["start"] > max_len):
            segs.append(cur)
            cur = []
        cur.append(w)
    if cur:
        segs.append(cur)
    out = []
    for s in segs:
        out.append({
            "start": s[0]["start"], "end": s[-1]["end"],
            "text": " ".join(w["word"] for w in s),
            "words": [{"word": w["word"], "start": w["start"], "end": w["end"]} for w in s],
        })
    return out


def stage(prompt, schema, label):
    config = genai_types.GenerateContentConfig(
        response_mime_type="application/json", response_schema=schema)
    for attempt in range(1, 4):
        try:
            resp = client.models.generate_content(model=MODEL, contents=prompt, config=config)
            gemini_worker.raise_if_blocked(resp)
            parsed = getattr(resp, "parsed", None)
            if parsed is not None:
                return parsed.model_dump() if hasattr(parsed, "model_dump") else parsed
            return gemini_worker._parse_json_response_text(
                gemini_worker._get_response_text(resp))
        except gemini_worker.GeminiBlockedError:
            raise
        except Exception as e:
            print(f"  transient {label} attempt {attempt}/3: {str(e)[:150]}")
            if attempt == 3:
                raise
            time.sleep(5 * (2 ** (attempt - 1)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--words", default="downloads/primera_mitad_words.json")
    ap.add_argument("--out", default="output/openshorts_primera_mitad/shorts.json")
    ap.add_argument("--duration", type=float, default=2880.0)
    ap.add_argument("--min-clips", type=int, default=3)
    ap.add_argument("--max-clips", type=int, default=5)
    ap.add_argument("--shortlist-cap", type=int, default=10)
    ap.add_argument("--score-batch", type=int, default=8)
    args = ap.parse_args()

    words = json.loads(Path(args.words).read_text(encoding="utf-8"))
    segments = build_segments(words)
    transcript = {"language": LANGUAGE, "segments": segments,
                  "text": " ".join(w["word"] for w in words)}
    duration = args.duration
    print(f"words={len(words)} segments={len(segments)}")

    flat = [{"w": w["word"], "s": w["start"], "e": w["end"]} for w in words]
    windows = build_transcript_windows(transcript, duration, window_seconds=90,
                                       overlap_seconds=30)
    print(f"windows={len(windows)}")

    def payload(ws):
        return [{"id": w["id"], "start": w["start"], "end": w["end"], "text": w["text"]}
                for w in ws]

    scored = []
    for b in range(0, len(windows), args.score_batch):
        batch = windows[b:b + args.score_batch]
        prompt = gemini_worker.SCORE_PROMPT_TEMPLATE.format(
            video_duration=duration, language=LANGUAGE,
            windows_json=json.dumps(payload(batch), ensure_ascii=False))
        try:
            parsed = stage(prompt, gemini_worker.ScoreResponse, "score")
            scored.extend(parsed.get("windows") or [])
            print(f"  batch {b // args.score_batch + 1}: +{len(parsed.get('windows') or [])} scored")
        except gemini_worker.GeminiBlockedError as e:
            print(f"  batch blocked, skipping: {e}")

    scored.sort(key=lambda w: w.get("score", 0), reverse=True)
    target = max(3, min(args.shortlist_cap, int(duration // 90) + 2))
    by_id = {w["id"]: w for w in windows}
    shortlist = [by_id[w["id"]] for w in scored[:target] if w.get("id") in by_id]
    if not shortlist:
        shortlist = windows[:target]
    print(f"shortlist={len(shortlist)}")
    for w in scored[:16]:
        print(f"  score={w.get('score')} {w.get('id')} [{w.get('start'):.0f}-{w.get('end'):.0f}] {w.get('reason','')[:80]}")

    prompt = gemini_worker.DETAIL_PROMPT_TEMPLATE.format(
        video_duration=duration, language=LANGUAGE,
        min_clips=args.min_clips, max_clips=args.max_clips,
        min_secs=15, max_secs=60,
        windows_json=json.dumps(payload(shortlist), ensure_ascii=False))
    parsed = stage(prompt, gemini_worker.DetailResponse, "detail")
    shorts = list(parsed.get("shorts") or [])
    print(f"detail returned {len(shorts)}")
    if len(shorts) > args.max_clips:
        shorts = trim_to_best([(i, s) for i, s in enumerate(shorts)], args.max_clips)
    for s in shorts:
        ns, ne = snap_clip_to_words(s["start"], s["end"], flat, duration,
                                    min_duration=15.0, max_duration=60.0)
        s["start"], s["end"] = ns, ne

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"shorts": shorts, "scored": scored[:16],
                               "model": MODEL}, indent=2, ensure_ascii=False),
                   encoding="utf-8")
    for s in shorts:
        print(f"- [{s['start']:.0f}-{s['end']:.0f}] score={s['predicted_score']} "
              f"hook={s['viral_hook_text'][:70]} | title={s['video_title_for_youtube_short'][:70]}")


main()
