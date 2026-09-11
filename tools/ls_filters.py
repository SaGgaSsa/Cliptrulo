import re, sys
src = open('output/ep2/relatando/clip_01_shotcut.mlt', encoding='utf-8').read()
pat = re.compile(r'<filter id="(filter_[^"]+)">(.*?)</filter>', re.S)
for m in pat.finditer(src):
    fid, body = m.groups()
    svc = re.search(r'mlt_service">(.*?)<', body)
    left = re.search(r'"left">(.*?)<', body)
    rect = re.search(r'"rect">(.*?)<', body)
    print(fid, svc.group(1) if svc else '?',
          ('left=' + left.group(1)) if left else '',
          (rect.group(1)) if rect else '')
