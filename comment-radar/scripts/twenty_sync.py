#!/usr/bin/env python3
"""Клієнти, пілоти й ліди з Twenty -> targets_clients.json.

Запускається щоранку перед збором дописів (daily.sh). Файл не правимо руками: він щоразу збирається наново,
тому клієнт, заведений у Twenty вчора, сьогодні вже в підказках.

Беруться компанії, у яких поле статусу (config.json -> twenty.company_status_field) має одне зі значень
twenty.statuses, і всі люди цих компаній із посиланням на LinkedIn. Людина без посилання в підказки
не потрапить, скрипт пише, скільки таких.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request

from common import TODAY, canon, config, secret, write_json


def api(base: str, key: str, obj: str, params: dict) -> dict:
    url = f"{base.rstrip('/')}/rest/{obj}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={'Authorization': f'Bearer {key}', 'User-Agent': 'curl/8.4.0'})
    for attempt in range(5):
        time.sleep(0.7)   # Twenty REST: 100 requests per minute
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(20)
                continue
            if e.code in (401, 403):
                raise SystemExit('Twenty 401/403: ключ у scripts/twenty.env не підходить або без доступу до даних')
            raise SystemExit(f'Twenty {obj}: HTTP {e.code} {e.read()[:200]!r}')
    raise SystemExit('Twenty: забагато запитів поспіль, спробуйте за хвилину')


def all_pages(base, key, obj, flt) -> list[dict]:
    out, cursor = [], None
    while True:
        p = {'filter': flt, 'limit': 60, 'depth': 0}
        if cursor:
            p['starting_after'] = cursor
        d = api(base, key, obj, p)
        out += (d.get('data') or {}).get(obj) or []
        info = d.get('pageInfo') or {}
        if not info.get('hasNextPage'):
            return out
        cursor = info.get('endCursor')


def main() -> int:
    cfg = config()['twenty']
    if '___' in json.dumps(cfg):
        raise SystemExit('Заповніть розділ twenty у config.json (адреса, поле статусу, значення)')
    key = secret('twenty.env', 'TWENTY_API_KEY')
    field = cfg['company_status_field']
    relation_of = {v: rel for rel, vals in cfg['statuses'].items() for v in vals}

    comps = all_pages(cfg['base_url'], key, 'companies', f'{field}[in]:{json.dumps(list(relation_of))}')
    by_id = {c['id']: c for c in comps}
    people = []
    ids = list(by_id)
    for i in range(0, len(ids), 40):
        people += all_pages(cfg['base_url'], key, 'people', f'companyId[in]:{json.dumps(ids[i:i + 40])}')

    rows, no_link = [], 0
    for p in people:
        url = canon(((p.get('linkedinLink') or {}).get('primaryLinkUrl')) or '')
        if not url:
            no_link += 1
            continue
        c = by_id.get(p.get('companyId')) or {}
        nm = p.get('name') or {}
        rows.append({'name': f"{nm.get('firstName', '')} {nm.get('lastName', '')}".strip() or '—',
                     'headline': f"{p.get('jobTitle') or ''} · {c.get('name') or ''}".strip(' ·'),
                     'company': c.get('name') or '', 'profile_url': url, 'bucket': 'clients',
                     'why': relation_of.get(c.get(field), ''), 'source': 'Twenty', 'added': TODAY})
    write_json('targets_clients.json', rows)
    print(f'Twenty: компаній {len(comps)} · людей {len(people)} · з посиланням на LinkedIn {len(rows)} · без посилання {no_link}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
