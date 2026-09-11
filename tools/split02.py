import json

p = 'output/ep2/relatando/picks.json'
d = json.load(open(p, encoding='utf-8'))
for c in d['clips']:
    if c['rank'] == 2:
        c['spans'] = [
            {'start': 529.8, 'end': 539.0, 'role': 'presentacion'},
            {'start': 539.0, 'end': 587.01, 'role': 'mejor_reaccion', 'hard': True},
        ]
        c['item']['summary'] = 'Diego: pase magico, muy realisimo, no estaria ocurriendo (cierra en lamentablemente)'
d['clips'].append({
    'rank': 5,
    'item': {'start': 529, 'end': 650, 'kind': 'visionado', 'score': 80,
             'summary': 'Borraron el video en vivo: caserta ponete la pila'},
    'spans': [{'start': 615.53, 'end': 633.0, 'role': 'mejor_reaccion'}],
})
json.dump(d, open(p, 'w', encoding='utf-8'), ensure_ascii=False)
print('ranks:', sorted(c['rank'] for c in d['clips']))
