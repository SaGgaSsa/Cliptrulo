import json

w = json.load(open('downloads/EP2_relatando_words.json', encoding='utf-8'))
ws = [x for x in w if 693.0 <= x['start'] <= 809.0]
print('--- gaps > 1.2s entre palabras (rel al crudo) ---')
for a, b in zip(ws, ws[1:]):
    g = b['start'] - a['end']
    if g > 1.2:
        r0, r1 = a['end'] - 693.6, b['start'] - 693.6
        print(f'rel {r0:5.1f}-{r1:5.1f} ({g:.1f}s) [{a["word"]}] -> [{b["word"]}]')
