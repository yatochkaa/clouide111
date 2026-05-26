import os
import re
import time
import argparse
from pathlib import Path
from urllib.parse import urlencode

from dotenv import load_dotenv
import requests

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / '.env', override=True)

API_URL = 'https://api.partsapi.ru/'
API_DELAY = float(os.getenv('API_DELAY', '0.8'))
TIMEOUT = int(os.getenv('API_TIMEOUT', '10'))

CURATED_DEBUG_CATS = [
    (7, 'Масляный фильтр'),
    (8, 'Воздушный фильтр'),
    (9, 'Салонный фильтр'),
    (424, 'Топливный фильтр'),
    (281, 'Тормозные колодки передние'),
    (282, 'Тормозные колодки задние'),
    (82, 'Тормозной диск передний'),
    (84, 'Тормозной диск задний'),
    (1041, 'Амортизатор передний'),
    (1042, 'Амортизатор задний'),
    (188, 'Рычаг передний'),
    (189, 'Рычаг задний'),
    (273, 'Стойка стабилизатора передняя'),
    (274, 'Стойка стабилизатора задняя'),
    (1037, 'Ступица'),
    (686, 'Свеча зажигания'),
    (689, 'Свеча накала'),
    (306, 'Ремень ГРМ'),
    (307, 'Цепь ГРМ'),
    (470, 'Помпа'),
    (655, 'Радиатор охлаждения'),
    (5, 'Аккумулятор'),
]

OEM_FALLBACK_ARTICLES = {
    'MITSUBISHI': {7:['MD360935'],8:['1500A023'],82:['4615A117'],84:['4615A118'],281:['4605A730'],282:['4605A487'],306:['1145A019'],424:['1770A106'],686:['1822A069'],1041:['MR992330'],1042:['4162A050']},
    'PEUGEOT': {7:['1109AY'],8:['1444XG'],82:['4249J6'],84:['4249J7'],281:['4254A8'],282:['4254A7'],306:['0816H6'],424:['1906E6'],686:['5960G4'],1041:['5202ZH'],1042:['5206W8']},
    'TOYOTA': {7:['90915YZZE1'],8:['1780131110'],82:['4351233150'],84:['4243133170'],281:['0446533471'],282:['0446633170'],306:['1356839065'],424:['233900L041'],686:['9091901247'],1041:['4852039735'],1042:['4853039705']},
}

OEM_PREFIXES = {
    'MITSUBISHI': [7,8,82,84,281,282,686],
    'PEUGEOT': [7,8,82,84,281,282,424,686],
    'TOYOTA': [2,4,5,7,8,9,13,48,51,78,82,83,84,123,124,188,189,198,262,273,274,277,281,282,284,286,304,305,306,307,308,316,331,424,470,479,653,655,686,689,1037,1041,1042,1046],
}

_last_call = 0.0


def mask(v):
    if not v:
        return 'NONE'
    return v[:4] + '...' + v[-4:]


def norm_article(s):
    return re.sub(r'[^A-Z0-9]', '', str(s or '').upper())


def api_call(method, key, **params):
    global _last_call
    delta = time.time() - _last_call
    if delta < API_DELAY:
        time.sleep(API_DELAY - delta)

    q = {'method': method, 'key': key, **params}
    try:
        r = requests.get(API_URL, params=q, timeout=TIMEOUT)
        _last_call = time.time()
        text = r.text
        try:
            data = r.json()
        except Exception:
            data = None
        return r.status_code, text, data, r.url
    except requests.exceptions.ReadTimeout:
        _last_call = time.time()
        return 0, 'READ_TIMEOUT', None, f'{API_URL}?{urlencode(q)}'
    except requests.exceptions.RequestException as e:
        _last_call = time.time()
        return 0, f'REQUEST_ERROR: {e}', None, f'{API_URL}?{urlencode(q)}'


def api_vindecode(vin):
    return api_call(
        'VINdecodeOE',
        os.getenv('PARTSAPI_KEY_VINDECODE', 'PASTE_YOUR_KEY'),
        vin=vin,
        lang='ru'
    )


def api_parts(vin, cat):
    return api_call(
        'getPartsByVin',
        os.getenv('PARTSAPI_KEY_VIN', 'PASTE_YOUR_KEY'),
        vin=vin,
        cat=cat,
        lang='ru',
        type='oem'
    )


def api_crosses(article):
    return api_call(
        'tecdocCrosses',
        os.getenv('PARTSAPI_KEY_CROSSES', 'PASTE_YOUR_KEY'),
        number=article,
        lang='ru'
    )


def parse_vindecode_row(data):
    if not isinstance(data, dict):
        return {}

    res = data.get('result')
    if isinstance(res, dict):
        row = res.get('0')
        if isinstance(row, dict):
            return row

    arr = data.get('data', {}).get('array')
    if isinstance(arr, dict):
        return arr

    return {}


def extract_result(data):
    if isinstance(data, list):
        return data

    if not isinstance(data, dict):
        return []

    res = data.get('result')
    if isinstance(res, dict):
        return list(res.values())
    if isinstance(res, list):
        return res

    arr = data.get('data', {}).get('array')
    if isinstance(arr, list):
        return arr
    if isinstance(arr, dict):
        return [arr]

    return []


def summarize_parts_items(items, limit=5):
    seen = set()
    out = []

    for x in items:
        if not isinstance(x, dict):
            continue

        if x.get('parts'):
            raw_parts = str(x.get('parts') or '')
            part_name = str(x.get('name') or x.get('shortname') or '—').strip()

            for token in raw_parts.split(','):
                token = token.strip()
                if '|' not in token:
                    continue

                brand, art = token.split('|', 1)
                brand = brand.strip().upper()
                art = art.strip()

                key = (brand, norm_article(art))
                if not art or key in seen:
                    continue

                seen.add(key)
                out.append({
                    'brand': brand or '—',
                    'article': art,
                    'name': part_name
                })

                if len(out) >= limit:
                    return len(seen), out
        else:
            brand = str(x.get('brand') or x.get('manuName') or x.get('manufacturer') or '').strip().upper()
            art = str(x.get('article') or x.get('number') or x.get('oem') or '').strip()
            name = str(x.get('name') or x.get('partName') or x.get('description') or '').strip()

            key = (brand, norm_article(art))
            if not art or key in seen:
                continue

            seen.add(key)
            out.append({
                'brand': brand or '—',
                'article': art,
                'name': name or '—'
            })

            if len(out) >= limit:
                return len(seen), out

    return len(seen), out


def fetch_parts_items(vin, cat):
    status, text, data, url = api_parts(vin, cat)

    api_error = False
    api_error_msg = ''

    if status != 200:
        api_error = True
        api_error_msg = text

    if isinstance(data, dict) and data.get('error_code'):
        api_error = True
        api_error_msg = f"{data.get('error_code')}: {data.get('message', '')}"

    if api_error:
        return {
            'status': status,
            'text': api_error_msg or text,
            'url': url,
            'items': [],
            'count': 0,
            'total': 0,
            'samples': [],
            'data': data,
            'is_error': True,
        }

    items = extract_result(data)
    total, samples = summarize_parts_items(items, limit=10)

    return {
        'status': status,
        'text': text,
        'url': url,
        'items': items,
        'count': len(items),
        'total': total,
        'samples': samples,
        'data': data,
        'is_error': False,
    }


def cmd_vin(vin, raw=False):
    status, text, data, url = api_vindecode(vin)
    print(f'VIN KEY = {mask(os.getenv("PARTSAPI_KEY_VIN"))}')
    print(f'VINDECODE KEY = {mask(os.getenv("PARTSAPI_KEY_VINDECODE"))}')
    print(f'CROSSES KEY = {mask(os.getenv("PARTSAPI_KEY_CROSSES"))}')
    print(f'HTTP {status}')
    print(f'URL: {url}')

    if raw or not data:
        print(text)
        return

    row = parse_vindecode_row(data)
    if not row:
        print(f'VINdecodeOE не вернул данные для {vin}')
        return

    brand = row.get('manuName') or row.get('brend') or '—'
    model = row.get('modelName') or row.get('naimenovanie') or '—'
    modif = row.get('modifName') or row.get('modifikaciya') or row.get('modifikacii') or '—'
    katalog = row.get('katalog') or '—'
    modely = row.get('modely') or '—'
    market = row.get('market') or row.get('rynok') or '—'
    market_code = row.get('market_abbr') or row.get('rynok_abbr') or '—'

    print(f'Марка: {brand}')
    print(f'Модель: {model}')
    print(f'Модификация: {modif}')
    print(f'Каталог: {katalog}')
    print(f'TecDoc модель: {modely}')
    print(f'Рынок: {market} ({market_code})')


def cmd_parts(vin, cat):
    r = fetch_parts_items(vin, cat)
    print(f'HTTP {r["status"]}')
    print(f'URL: {r["url"]}')

    if r['status'] == 0:
        print(r['text'])
        return

    if not r['items']:
        print('API вернул пустой набор []')
        if r['text']:
            print(r['text'][:2000])
        return

    print(f'Найдено позиций: {r["total"]}')
    for i, x in enumerate(r['samples'], 1):
        print(f"{i}. {x['brand']} | {x['article']} | {x['name']}")


def build_coverage(vin):
    checked = []

    for cat, label in CURATED_DEBUG_CATS:
        r = fetch_parts_items(vin, cat)
        checked.append({
            'cat': cat,
            'label': label,
            'ok': r['status'] != 0 and r['count'] > 0,
            'count': r['total'],
            'sample': r['samples'][0] if r['samples'] else None,
            'status': r['status'],
            'error': r['text'] if r['status'] == 0 else ''
        })

    working = [x for x in checked if x['ok']]
    empty = [x for x in checked if x['status'] != 0 and not x['ok']]
    errors = [x for x in checked if x['status'] == 0]

    pct = round(len(working) * 100 / len(checked)) if checked else 0
    level = 'ok' if pct >= 50 else 'partial' if pct >= 20 else 'weak'

    return checked, working, empty, errors, pct, level


def cmd_coverage(vin):
    checked = []
    working = []
    empty = []
    errors = []

    for cat, label in CURATED_DEBUG_CATS:
        r = fetch_parts_items(vin, cat)
        row = {
            'cat': cat,
            'label': label,
            'status': r['status'],
            'count': r['total'],
        }
        checked.append(row)

        if r['is_error']:
            errors.append(row)
        elif r['count'] > 0:
            working.append(row)
        else:
            empty.append(row)

    total = len(CURATED_DEBUG_CATS)
    pct = round(len(working) * 100 / total) if total else 0

    if pct >= 50:
        level = 'good'
    elif pct >= 20:
        level = 'medium'
    else:
        level = 'weak'

    print(f'Coverage: {len(working)}/{total} ({pct}%) -> {level}')
    print('Работают:', ', '.join(str(x['cat']) for x in working) or '—')
    print('Пусто:', ', '.join(str(x['cat']) for x in empty) or '—')
    print('Timeout/ошибки:', ', '.join(str(x['cat']) for x in errors) or '—')


def cmd_cats(vin):
    for cat, label in CURATED_DEBUG_CATS:
        r = fetch_parts_items(vin, cat)

        if r['is_error']:
            print(f'ERR cat={cat:<4} {label:<28} status={r["status"]} {r["text"]}')
            continue

        if r['count'] > 0:
            print(f'OK  cat={cat:<4} {label:<28} count={r["total"]}')
        else:
            print(f'NO  cat={cat:<4} {label:<28} count=0')

        if cat in (8, 281):
            print('DEBUG CAT', cat, 'status=', r['status'], 'count=', r['total'])
            print('DEBUG ITEMS', r['items'][:1])


def cmd_matrix(vin):
    print('DEBUG MATRIX START')
    status, text, data, url = api_vindecode(vin)

    print('DEBUG status =', status)
    print('DEBUG data =', data)

    row = parse_vindecode_row(data)
    print('DEBUG row =', row)

    brand = str(row.get('manuName') or row.get('brend') or '—').upper()
    model = row.get('modelName') or row.get('naimenovanie') or '—'
    katalog = row.get('katalog') or '—'

    checked, working, empty, errors, pct, level = build_coverage(vin)

    fb = len(OEM_FALLBACK_ARTICLES.get(brand, {})) if brand in OEM_FALLBACK_ARTICLES else 0
    pfx = len(OEM_PREFIXES.get(brand, [])) if brand in OEM_PREFIXES else 0

    print(f'Бренд / модель: {brand} / {model}')
    print(f'Каталог: {katalog}')

    tags = []
    if fb:
        tags.append(f'FB({fb})')
    if pfx:
        tags.append(f'PFX({pfx})')

    print('Локально:', ' '.join(tags) if tags else '—')
    print(f'Coverage: {len(working)}/{len(checked)} ({pct}%) -> {level}')
    print('Работают:', ', '.join(str(x['cat']) for x in working) or '—')
    print('Пусто:', ', '.join(str(x['cat']) for x in empty) or '—')
    print('Timeout/ошибки:', ', '.join(str(x['cat']) for x in errors) or '—')


def cmd_brand(brand):
    b = brand.upper()
    print(f'Бренд: {b}')
    print('OEM_FALLBACK_ARTICLES:', 'YES' if b in OEM_FALLBACK_ARTICLES else 'NO')

    if b in OEM_FALLBACK_ARTICLES:
        mp = OEM_FALLBACK_ARTICLES[b]
        print('Fallback cat-ы:', ', '.join(str(k) for k in sorted(mp)))
        print('Всего артикулов:', sum(len(v) for v in mp.values()))

    print('OEM_PREFIXES:', 'YES' if b in OEM_PREFIXES else 'NO')
    if b in OEM_PREFIXES:
        print('Prefix cat-ы:', ', '.join(str(k) for k in OEM_PREFIXES[b]))


def cmd_crosses(article):
    status, text, data, url = api_crosses(article)
    print(f'HTTP {status}')
    print(f'URL: {url}')
    print(text[:4000])


def main():
    p = argparse.ArgumentParser(description='Standalone partsapi debug tool')
    sub = p.add_subparsers(dest='cmd', required=True)

    a = sub.add_parser('vin')
    a.add_argument('vin')

    b = sub.add_parser('vinraw')
    b.add_argument('vin')

    c = sub.add_parser('parts')
    c.add_argument('vin')
    c.add_argument('cat', type=int)

    d = sub.add_parser('cats')
    d.add_argument('vin')

    e = sub.add_parser('coverage')
    e.add_argument('vin')

    f = sub.add_parser('matrix')
    f.add_argument('vin')

    g = sub.add_parser('brand')
    g.add_argument('brand')

    h = sub.add_parser('crosses')
    h.add_argument('article')

    args = p.parse_args()

    if args.cmd == 'vin':
        cmd_vin(args.vin)
    elif args.cmd == 'vinraw':
        cmd_vin(args.vin, raw=True)
    elif args.cmd == 'parts':
        cmd_parts(args.vin, args.cat)
    elif args.cmd == 'cats':
        cmd_cats(args.vin)
    elif args.cmd == 'coverage':
        cmd_coverage(args.vin)
    elif args.cmd == 'matrix':
        cmd_matrix(args.vin)
    elif args.cmd == 'brand':
        cmd_brand(args.brand)
    elif args.cmd == 'crosses':
        cmd_crosses(args.article)


if __name__ == '__main__':
    main()