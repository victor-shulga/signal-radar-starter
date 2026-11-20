#!/usr/bin/env python3
"""Хто реагує: ваші дописи й дописи конкурентів -> оцінка -> сторінка «Хто реагує» і списки для коментарів.

    python3 scripts/engagers.py            # раз на тиждень (daily.sh запускає його щопонеділка)

engagers.json        : усі люди для вкладки «Хто реагує»: група, скільки реакцій, під чиїми дописами.
targets_engagers.json: ті, хто реагував на ВАШІ дописи. Щоденні підказки беруть звідси топ-15.
targets_warm.json    : 60+ балів зі 100 (роль 20 + активність 30 + збіг із групою 50), плюс покупці під дописами конкурентів.

Під дописами конкурентів профіль дозбирається лише для тих, у кого заголовок схожий на вашу групу або хто є
клієнтом чи лідом: там сотні людей, платити за кожного немає сенсу. Співробітники конкурента відкидаються.
"""
from __future__ import annotations

import datetime
import re

from common import (Budget, TODAY, age_h, canon, config, fan_out, group_of, in_markets, paged, profile,
                    profile_posts, read_json, slug, write_json)

SENIOR = re.compile(r'\b(head|director|vp|vice president|chief|ceo|coo|cmo|cto|cpo|founder|owner|partner|lead)\b', re.I)
MANAGER = re.compile(r'\b(manager|owner)\b', re.I)
URL_KEYS = ('linkedinurl', 'profileurl', 'url')
HEAD_KEYS = ('position', 'headline', 'info', 'occupation', 'title')
COMP_DAYS = 14


def person(el: dict) -> dict | None:
    """Reaction / comment element -> {key, url, name, headline}. Field names differ between endpoints.
    key = actor.id when present: the same person has different links in reactions and in comments."""
    for c in [v for k, v in el.items() if k in ('actor', 'author') and isinstance(v, dict)] + [el]:
        url = next((c[k] for k in c if k.lower() in URL_KEYS and isinstance(c[k], str) and '/in/' in c[k]), '')
        if url:
            head = next((c[k] for k in c if k.lower() in HEAD_KEYS and isinstance(c[k], str)), '')
            return {'key': str(c.get('id') or slug(url)), 'url': canon(url), 'name': c.get('name') or '', 'headline': head}
    return None


def norm_name(s: str) -> str:
    return ' '.join(re.sub(r'[^\w\s]', ' ', (s or '').lower()).split())


def position(prof: dict) -> dict:
    pos = prof.get('currentPosition') or [{}]
    return pos[0] if isinstance(pos, list) and pos else {}


def score(row: dict, prof: dict, cfg: dict) -> tuple[int, str | None]:
    pos = position(prof)
    text = f"{prof.get('headline') or row['headline']} | {pos.get('position') or ''} | {pos.get('companyName') or ''}"
    role = 20 if SENIOR.search(text) else 10 if MANAGER.search(text) else 0
    activity = min(30, 3 * row['reactions'] + 8 * row['comments'])
    g = group_of(text, cfg)
    fit = 0
    if g == 'tl':
        fit = 50                                      # opinion leaders are read from anywhere
    elif g:
        fit = 50 if (not prof or in_markets(prof, cfg)) else 25
    return role + activity + fit, g


def level(posts: int) -> str:
    return '🔥' if posts >= 3 else '🟡' if posts == 2 else '⚪'


def collect(authors: list[dict], budget: Budget) -> tuple[dict, dict]:
    """-> (people by key, stats per author). A person who reacted on several posts is one row."""
    people: dict[str, dict] = {}
    stats = {}
    for a in authors:
        url = canon(a['profile_url'])
        posts = [p for p in (profile_posts(url, 'month', budget) or []) if age_h(p) <= a['days'] * 24]
        by_url = {p.get('linkedinUrl'): p for p in posts if p.get('linkedinUrl')}
        stats[a['name']] = {'posts': len(by_url), 'reactions': 0, 'comments': 0}
        for kind, path in (('reactions', '/linkedin/post-reactions'), ('comments', '/linkedin/post-comments')):
            urls = list(by_url)
            for u, els in zip(urls, fan_out(lambda u: paged(path, {'post': u}, kind, budget, 300), urls)):
                when = age_h(by_url[u])
                for el in els:
                    p = person(el)
                    if not p or not p['url'] or slug(p['url']) == slug(url):
                        continue
                    stats[a['name']][kind] += 1
                    r = people.setdefault(p['key'], {'name': p['name'], 'headline': p['headline'], 'profile_url': p['url'],
                                                     'reactions': 0, 'comments': 0, 'own': 0, 'post_set': set(),
                                                     'competitors': set(), 'age_h': 9e9})
                    r[kind] += 1
                    r['post_set'].add(u)
                    r['age_h'] = min(r['age_h'], when)
                    r['headline'] = r['headline'] or p['headline']
                    if a['competitor']:
                        r['competitors'].add(a['name'])
                    else:
                        r['own'] += 1
    return people, stats


def main() -> int:
    cfg = config()
    me = cfg['author']
    if not canon(me['profile_url']):
        raise SystemExit('Заповніть author.profile_url у config.json')
    comps = [c for c in cfg.get('competitors', []) if canon(c.get('profile_url', ''))]
    authors = [{'name': me['name'], 'profile_url': me['profile_url'], 'days': cfg['once']['engagers_days'], 'competitor': False}]
    authors += [{'name': c.get('company') or c['name'], 'profile_url': c['profile_url'], 'days': COMP_DAYS, 'competitor': True}
                for c in comps]
    stop_names = [re.escape(c['company'].lower()) for c in comps if c.get('company')]
    budget = Budget(cfg['once']['engagers_max_usd'])

    people, stats = collect(authors, budget)
    clients = read_json('targets_clients.json', [])
    by_slug = {slug(c['profile_url']): c for c in clients}
    by_name = {norm_name(c.get('name', '')): c for c in clients if len(norm_name(c.get('name', '')).split()) >= 2}

    def client_of(r, prof=None):
        real = canon((prof or {}).get('linkedinUrl') or (prof or {}).get('publicIdentifier') or '')
        return by_slug.get(slug(real or r['profile_url'])) or by_name.get(norm_name(r['name']))

    def wanted(k):
        r = people[k]
        return r['own'] or client_of(r) or group_of(r['headline'], cfg)

    cache = read_json('engagers_profiles.json', {})
    todo = [k for k in people if k not in cache and wanted(k)]
    for k, prof in zip(todo, fan_out(lambda k: profile(people[k]['profile_url'], budget), todo)):
        if prof:
            cache[k] = {x: prof.get(x) for x in ('headline', 'currentPosition', 'location', 'linkedinUrl', 'publicIdentifier')}
    write_json('engagers_profiles.json', cache)

    rows, warm, dropped = [], [], 0
    for k, r in people.items():
        prof = cache.get(k) or {}
        pos = position(prof)
        text = f"{r['headline']} {prof.get('headline') or ''} {pos.get('companyName') or ''}".lower()
        if r['competitors'] and not r['own'] and any(re.search(s, text) for s in stop_names):
            dropped += 1                              # a competitor's own staff under their boss's posts
            continue
        s, g = score(r, prof, cfg)
        cl = client_of(r, prof)
        posts = len(r['post_set'])
        last = (datetime.date.today() - datetime.timedelta(hours=r['age_h'])).isoformat()
        row = {'name': r['name'], 'headline': prof.get('headline') or r['headline'], 'company': pos.get('companyName') or '',
               'profile_url': canon(prof.get('linkedinUrl') or '') or r['profile_url'],
               'reactions': r['reactions'], 'comments': r['comments'], 'posts': posts, 'own': r['own'],
               'competitors': sorted(r['competitors']), 'group': 'clients' if cl else g, 'status': (cl or {}).get('why', ''),
               'attention': 3 * r['comments'] + r['reactions'], 'score': s, 'level': level(posts), 'last': last,
               'bucket': 'engagers', 'updated': TODAY}
        rows.append(row)
        buyer_at_comp = r['competitors'] and g == 'icp' and (not prof or in_markets(prof, cfg))
        if not cl and g and (s >= 60 or buyer_at_comp):
            why = f"під дописами {', '.join(sorted(r['competitors']))}" if r['competitors'] else f"реакцій {r['reactions']} · коментарів {r['comments']}"
            warm.append(dict(row, bucket=g, why=why))

    rows.sort(key=lambda r: (r['group'] != 'clients', -r['attention']))
    write_json('engagers.json', rows)
    write_json('targets_engagers.json', sorted([r for r in rows if r['own']], key=lambda r: -r['attention']))
    write_json('targets_warm.json', warm)

    for a, st in stats.items():
        print(f"{a}: дописів {st['posts']} · реакцій {st['reactions']} · коментарів {st['comments']}")
    cl_comp = sum(1 for r in rows if r['group'] == 'clients' and r['competitors'])
    print(f"людей: {len(rows)} · теплі: {len(warm)} · клієнти й ліди під конкурентами: {cl_comp} · співробітників конкурентів відкинуто: {dropped} · "
          f"витрачено ${budget.usd:.2f}" + (' · ⚠️ уперлися в ліміт витрат' if budget.stopped else ''))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
