#!/usr/bin/env python3
"""Signal radar starter: fetch objects (vacancies, news, tenders), keep state per object,
report only what changed since the last run.

Run:  python3 radar.py config.json
Test: python3 test_radar.py
Only the standard library. Apify token comes from the APIFY_TOKEN environment variable.
"""
import csv
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import date

STATE_COLS = ['object_id', 'domain', 'title', 'url', 'source_date', 'first_seen', 'last_seen', 'runs', 'gone_at', 'reappeared', 'quote']
SIGNAL_COLS = ['object_id', 'kind', 'domain', 'signal_type', 'signal_date', 'signal_age_days', 'signal_evidence_url', 'signal_summary', 'quote', 'found_on']


def fetch(source):
    """Return a list of raw items from the source in the config."""
    if source['type'] == 'file':
        return json.load(open(source['path'], encoding='utf-8'))
    if source['type'] == 'apify':
        token = os.environ['APIFY_TOKEN']
        actor = source['actor'].replace('/', '~')
        url = f'https://api.apify.com/v2/acts/{actor}/run-sync-get-dataset-items?token={urllib.parse.quote(token)}'
        req = urllib.request.Request(url, data=json.dumps(source.get('input', {})).encode(), headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=600) as r:
            return json.load(r)
    raise SystemExit(f"unknown source type: {source['type']}")


def domain_of(value):
    host = urllib.parse.urlparse(value if '//' in value else '//' + value).netloc.lower()
    return host[4:] if host.startswith('www.') else host


def pick(item, path):
    """Read a field by a dotted path, e.g. 'company.website'."""
    for key in path.split('.'):
        item = item.get(key, '') if isinstance(item, dict) else ''
    return str(item or '').strip()


def normalize(raw, cfg):
    f, out = cfg['fields'], []
    must = [w.lower() for w in cfg.get('must_words', [])]
    stop = [w.lower() for w in cfg.get('stop_words', [])]
    for it in raw:
        title, text = pick(it, f['title']), pick(it, f.get('text', f['title']))
        hay = f'{title} {text}'.lower()
        if must and not any(w in hay for w in must):
            continue
        if any(w in hay for w in stop):
            continue
        oid, dom = pick(it, f['object_id']), domain_of(pick(it, f['domain']))
        if not oid or not dom:
            continue
        quote = next((s.strip() for s in text.replace('\n', '. ').split('. ') if any(w in s.lower() for w in must)), title)[:200]
        out.append({'object_id': oid, 'domain': dom, 'title': title, 'url': pick(it, f.get('url', f['object_id'])),
                    'source_date': pick(it, f['date'])[:10] if f.get('date') else '', 'quote': quote})
    return out


def read_csv(path):
    return list(csv.DictReader(open(path, encoding='utf-8'))) if os.path.exists(path) else []


def write_csv(path, cols, rows, append=False):
    new = not os.path.exists(path) or not append
    with open(path, 'a' if append else 'w', newline='', encoding='utf-8') as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction='ignore')
        if new:
            w.writeheader()
        w.writerows(rows)


def age_days(row, today):
    start = row['source_date'] or row['first_seen']
    return (today - date.fromisoformat(start)).days


def run(cfg, raw, today, state_dir='state'):
    os.makedirs(state_dir, exist_ok=True)
    name = cfg['name']
    state_path, sig_path = f'{state_dir}/{name}_state.csv', f'{state_dir}/{name}_signals.csv'
    state = {r['object_id']: r for r in read_csv(state_path)}
    seen, events = set(), []
    for it in normalize(raw, cfg):
        oid, row = it['object_id'], state.get(it['object_id'])
        seen.add(oid)
        if row is None:
            row = state[oid] = {**it, 'first_seen': today.isoformat(), 'runs': '0', 'gone_at': '', 'reappeared': '0'}
            events.append((row, 'new'))
        elif row['gone_at']:
            row['gone_at'], row['reappeared'] = '', str(int(row['reappeared']) + 1)
            events.append((row, 'reappeared'))
        row['last_seen'], row['runs'] = today.isoformat(), str(int(row['runs']) + 1)
    gone = 0
    for oid, row in state.items():
        if oid not in seen and not row['gone_at']:
            row['gone_at'] = today.isoformat()
            gone += 1
    # each (object, kind) becomes a signal once: new / reappeared, or stale when it crosses min_age_days
    min_age, window = cfg.get('min_age_days', 0), cfg.get('window_days', 90)
    known = {(r['object_id'], r['kind']) for r in read_csv(sig_path)}
    kinds = {r['object_id']: k for r, k in events}
    signals = []
    for oid in sorted(seen):
        row = state[oid]
        age = age_days(row, today)
        if min_age:
            kind = 'stale' if min_age <= age <= min_age + window else None
        else:
            kind = kinds.get(oid) if age <= window else None
        if not kind or (oid, kind) in known:
            continue
        label = {'new': 'нове', 'reappeared': 'передрукували', 'stale': f'висить {age} днів'}[kind]
        signals.append({'object_id': oid, 'kind': kind, 'domain': row['domain'], 'signal_type': cfg['signal_type'],
                        'signal_date': row['source_date'] or row['first_seen'], 'signal_age_days': age,
                        'signal_evidence_url': row['url'], 'signal_summary': f"{row['title']} · {label}",
                        'quote': row['quote'], 'found_on': today.isoformat()})
    write_csv(state_path, STATE_COLS, list(state.values()))
    write_csv(sig_path, SIGNAL_COLS, signals, append=True)
    write_csv(f'{state_dir}/runs.csv', ['date', 'radar', 'found', 'new', 'gone', 'signals'],
              [{'date': today.isoformat(), 'radar': name, 'found': len(seen), 'new': sum(1 for _, r in events if r == 'new'), 'gone': gone, 'signals': len(signals)}], append=True)
    return signals


if __name__ == '__main__':
    if len(sys.argv) < 2:
        raise SystemExit('usage: python3 radar.py config.json')
    cfg = json.load(open(sys.argv[1], encoding='utf-8'))
    found = run(cfg, fetch(cfg['source']), date.today())
    print(f"{cfg['name']}: {len(found)} нових сигналів, деталі в state/{cfg['name']}_signals.csv")
