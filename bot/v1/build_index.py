# -*- coding: utf-8 -*-
"""Побудова покажчика пошуку для телеграм-бота НБР (варіант А).
Джерело: 100 шардів рейтингу (ukrnbr.github.io/nbr-rating-data).
Вихід: bot/v1/*  — покажчик за назвою (2 рівні) + покажчик КВЕД.
"""
import json, glob, re, os, collections, unicodedata

SRC   = '/home/claude/nbr/shards'
OUT   = '/home/claude/nbr/build/bot/v1'
NBUCK = 128

APOS = "'’`´ʼ‘"
SPLIT = re.compile(r'[^0-9A-Za-zА-Яа-яЁёЄєІіЇїҐґ]+')

# токени, які нічого не звужують (юридичні форми) — у покажчик не йдуть
STOP = set("""ТОВАРИСТВО ОБМЕЖЕНОЮ ВІДПОВІДАЛЬНІСТЮ З ПРИВАТНЕ АКЦІОНЕРНЕ ПУБЛІЧНЕ
ПІДПРИЄМСТВО ДЕРЖАВНЕ КОМУНАЛЬНЕ НЕКОМЕРЦІЙНЕ ФЕРМЕРСЬКЕ ГОСПОДАРСТВО СЕЛЯНСЬКЕ
ТОВ ПРАТ ПАТ ТДВ ФОП ДП КП КНП ФГ ПП ЛТД LTD LLC
ТА ІМ ІМЕНІ ВІД""".split())

# скорочення юридичної форми для короткої назви
FORMS = [
 ('ТОВАРИСТВО З ОБМЕЖЕНОЮ ВІДПОВІДАЛЬНІСТЮ', 'ТОВ'),
 ('ТОВАРИСТВО З ДОДАТКОВОЮ ВІДПОВІДАЛЬНІСТЮ', 'ТДВ'),
 ('ПРИВАТНЕ АКЦІОНЕРНЕ ТОВАРИСТВО', 'ПрАТ'),
 ('ПУБЛІЧНЕ АКЦІОНЕРНЕ ТОВАРИСТВО', 'ПАТ'),
 ('АКЦІОНЕРНЕ ТОВАРИСТВО', 'АТ'),
 ('КОМУНАЛЬНЕ НЕКОМЕРЦІЙНЕ ПІДПРИЄМСТВО', 'КНП'),
 ('КОМУНАЛЬНЕ ПІДПРИЄМСТВО', 'КП'),
 ('ДЕРЖАВНЕ ПІДПРИЄМСТВО', 'ДП'),
 ('ПРИВАТНЕ ПІДПРИЄМСТВО', 'ПП'),
 ('ФЕРМЕРСЬКЕ ГОСПОДАРСТВО', 'ФГ'),
 ('СЕЛЯНСЬКЕ (ФЕРМЕРСЬКЕ) ГОСПОДАРСТВО', 'СФГ'),
 ('ДОЧІРНЄ ПІДПРИЄМСТВО', 'ДП'),
 ('СІЛЬСЬКОГОСПОДАРСЬКЕ ТОВАРИСТВО З ОБМЕЖЕНОЮ ВІДПОВІДАЛЬНІСТЮ', 'СТОВ'),
 ('ОБСЛУГОВУЮЧИЙ КООПЕРАТИВ', 'ОК'),
 ('ВИРОБНИЧИЙ КООПЕРАТИВ', 'ВК'),
]
FORMS.sort(key=lambda x: -len(x[0]))

MEDAL = {'золото': 'z', 'срібло': 's', 'бронза': 'b'}

def norm(s):
    s = unicodedata.normalize('NFC', s).upper()
    for a in APOS:
        s = s.replace(a, '')
    return s

def tokens(name):
    out = []
    for t in SPLIT.split(norm(name)):
        if len(t) >= 2 and t not in STOP:
            out.append(t)
    return out

def short(name):
    n = re.sub(r'\s+', ' ', name.strip())
    up = n.upper()
    for full, ab in FORMS:
        if up.startswith(full):
            rest = n[len(full):].strip(' -–—')
            if rest:
                return ab + ' ' + rest
    return n

def bucket_of(pfx):
    h = 0
    for ch in pfx:
        h = (h * 131 + ord(ch)) % 1000000007
    return h % NBUCK

# ---------- читання ----------
recs = {}
for f in glob.glob(os.path.join(SRC, '*.json')):
    for k, v in json.load(open(f, encoding='utf-8')).items():
        e = v['edrpou'].zfill(8)
        recs[e] = v
print('записів:', len(recs))

# ---------- покажчик за назвою (одиниці = префікс 3, великі -> 4) ----------
import math
rows_by_tok = collections.defaultdict(list)
ids_by_tok  = collections.defaultdict(list)
BROAD = 100000   # id-only режим вимкнено: назви зберігаємо для всіх токенів
for e, v in recs.items():
    sh  = short(v['name'])
    med = MEDAL.get(v['medal'], '')
    row = [e, sh, med, v['place'], v['top'].replace('ТОП-', '')]
    seen = set()
    for t in tokens(v['name']):
        if len(t) < 3 or t in seen:
            continue
        seen.add(t)
        rows_by_tok[t].append(row)

# широкі токени (понад BROAD компаній) зберігаємо лише списком ЄДРПОУ — без назв
for t in list(rows_by_tok):
    if len(rows_by_tok[t]) > BROAD:
        ids_by_tok[t] = ','.join(r[0] for r in rows_by_tok[t])
        del rows_by_tok[t]
print('токенів вузьких:', len(rows_by_tok), ' широких:', len(ids_by_tok))

entries = {}
for t, rows in rows_by_tok.items():
    entries[t] = {'n': rows}
for t, ids in ids_by_tok.items():
    entries[t] = {'i': ids}

def jsize(obj):
    return len(json.dumps(obj, ensure_ascii=False, separators=(',', ':')).encode('utf-8'))

# 1) базові одиниці за префіксом 3
p3 = collections.defaultdict(dict)
for t, ent in entries.items():
    p3[t[:3]][t] = ent

MAXUNIT = 120 * 1024
MAXPFX  = 7
units = {}                      # ключ одиниці -> {токен: рядки}

def rozklasty(key, d):
    """Кладе одиницю; якщо завелика — ділить на довші префікси.
    Токени, довжина яких дорівнює довжині ключа, лишаються під самим ключем."""
    if jsize(d) <= MAXUNIT or len(key) >= MAXPFX:
        units[key] = d
        return
    n = len(key)
    exact = {t: r for t, r in d.items() if len(t) == n}
    if exact:
        units[key] = exact
    sub = collections.defaultdict(dict)
    for t, r in d.items():
        if len(t) > n:
            sub[t[:n + 1]][t] = r
    for k2, d2 in sub.items():
        rozklasty(k2, d2)

for k, d in p3.items():
    rozklasty(k, d)

# 2) розкладаємо одиниці по кошиках (жадібно, найбільші першими)
TARGET = 180 * 1024
sizes = sorted(((jsize(d), k) for k, d in units.items()), reverse=True)
buckets = []          # список dict
bsize   = []
pfx_map = {}
for sz, k in sizes:
    idx = None
    for i, s in enumerate(bsize):
        if s + sz <= TARGET:
            idx = i
            break
    if idx is None:
        buckets.append({})
        bsize.append(0)
        idx = len(buckets) - 1
    buckets[idx].update(units[k])
    bsize[idx] += sz
    pfx_map[k] = idx

os.makedirs(os.path.join(OUT, 'b'), exist_ok=True)
tot = 0
for i, b in enumerate(buckets):
    path = os.path.join(OUT, 'b', '%d.json' % i)
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump(b, fh, ensure_ascii=False, separators=(',', ':'))
    tot += os.path.getsize(path)
json.dump(pfx_map, open(os.path.join(OUT, 'pfx.json'), 'w', encoding='utf-8'),
          ensure_ascii=False, separators=(',', ':'))
NBUCK = len(buckets)
print('кошиків:', NBUCK, 'макс КБ:', max(bsize) // 1024, 'сума МБ: %.1f' % (tot / 1048576))

# ---------- покажчик КВЕД ----------
kv = collections.defaultdict(list)
for e, v in recs.items():
    code, _, kname = v['kved'].partition(' — ')
    kv[(code.strip(), kname.strip())].append((e, v))

def place_key(v):
    try:    return int(v['place'])
    except: return 10**9

kved_list = []
os.makedirs(os.path.join(OUT, 'kv'), exist_ok=True)
for (code, kname), items in sorted(kv.items()):
    kved_list.append([code, kname, len(items)])
    items.sort(key=lambda x: place_key(x[1]))
    top = [[e, short(v['name']), MEDAL.get(v['medal'], ''), v['place'],
            v['top'].replace('ТОП-', '')] for e, v in items[:50]]
    slug = code.replace('.', '')
    json.dump(top, open(os.path.join(OUT, 'kv', slug + '.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, separators=(',', ':'))
json.dump(kved_list, open(os.path.join(OUT, 'kved.json'), 'w', encoding='utf-8'),
          ensure_ascii=False, separators=(',', ':'))

# ---------- швидка картка за ЄДРПОУ (100 файлів) ----------
os.makedirs(os.path.join(OUT, 'e'), exist_ok=True)
eshard = collections.defaultdict(dict)
nom_idx = {}
for e, v in recs.items():
    code, _, kname = v['kved'].partition(' — ')
    eshard[int(e) % 100][e] = [short(v['name']), MEDAL.get(v['medal'], ''),
                               v['place'], v['top'].replace('ТОП-', ''),
                               code.strip(), nom_idx.setdefault(v['nom'], len(nom_idx))]
for i, d in eshard.items():
    json.dump(d, open(os.path.join(OUT, 'e', '%d.json' % i), 'w', encoding='utf-8'),
              ensure_ascii=False, separators=(',', ':'))

json.dump([k for k, _ in sorted(nom_idx.items(), key=lambda x: x[1])],
          open(os.path.join(OUT, 'nom.json'), 'w', encoding='utf-8'),
          ensure_ascii=False, separators=(',', ':'))

json.dump({'version': 'v1', 'source': 'rating-2024 (шарди nbr-rating-data)',
           'companies': len(recs), 'buckets': NBUCK, 'kved': len(kved_list)},
          open(os.path.join(OUT, 'meta.json'), 'w', encoding='utf-8'),
          ensure_ascii=False)

print('префіксів:', len(pfx_map), ' КВЕД:', len(kved_list))
