import json

p = 'output/ep2/relatando/picks.json'
d = json.load(open(p, encoding='utf-8'))
for c in d['clips']:
    if c['rank'] == 5:
        c['spans'] = [{'start': 615.53, 'end': 632.28,
                       'role': 'mejor_reaccion', 'hard': True}]
json.dump(d, open(p, 'w', encoding='utf-8'), ensure_ascii=False)
print('ok')
