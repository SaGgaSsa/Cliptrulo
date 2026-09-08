import json
import sys

words_path = sys.argv[1] if len(sys.argv) > 1 else "downloads/primera_mitad_words.json"
shorts_path = sys.argv[2] if len(sys.argv) > 2 else "output/openshorts_primera_mitad/shorts.json"
offset = float(sys.argv[3]) if len(sys.argv) > 3 else 0.0

words = json.load(open(words_path, encoding="utf-8"))
shorts = json.load(open(shorts_path, encoding="utf-8"))["shorts"]
for i, s in enumerate(shorts, 1):
    txt = " ".join(w["word"] for w in words if s["start"] - 1 <= w["start"] <= s["end"] + 1)
    a, b = s["start"] + offset, s["end"] + offset
    print("--- SHORT %d [file %d-%d | abs %d:%02d-%d:%02d] score=%s"
          % (i, s["start"], s["end"], a // 60, a % 60, b // 60, b % 60, s["predicted_score"]))
    print("HOOK:", s["viral_hook_text"])
    print("TITLE:", s["video_title_for_youtube_short"])
    print("DICE:", txt[:550])
    print()
