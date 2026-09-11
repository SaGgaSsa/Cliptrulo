import json, sys

a, b = float(sys.argv[1]), float(sys.argv[2])
w = json.load(open('downloads/EP2_relatando_words.json', encoding='utf-8'))
ws = [x for x in w if a <= x['start'] <= b]
for x in ws:
    print(f"{x['word']}({x['start']:.2f}-{x['end']:.2f})", end=' ')
print()
