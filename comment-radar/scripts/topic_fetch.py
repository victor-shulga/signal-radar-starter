#!/usr/bin/env python3
"""Пошук дописів за темами по всьому LinkedIn -> нові автори для активного списку.

Викликається з fetch_posts.py щоранку (вимкнути: config.json -> topics.enabled = false).
Окремий ручний запуск, щоб подивитися, кого знаходить:  python3 scripts/topic_fetch.py

Як відбирає автора: опис профілю збігся з однією з груп -> короткий профіль ($0.004, кеш
topic_profiles.json) -> країна з ваших ринків (для лідерів думок не важлива) і група підтверджена
за посадою. Ті, хто пройшов, дописуються в targets_active.json, так список росте сам. У підказки йдуть
лише їхні дописи, молодші за вікно свіжості (40 годин).
"""
from __future__ import annotations

from common import (Budget, TODAY, age_h, config, group_of, harvest, in_markets, is_repost, merge_targets,
                    profile, read_json, slug, write_json)


def run(cfg: dict, budget: Budget, known: set[str]) -> tuple[list[tuple[dict, dict]], dict]:
    """-> ([(target, post)] fresh enough for today's drafts, stats)."""
    tc = cfg['topics']
    st = {'queries': 0, 'posts': 0, 'matched': 0, 'checked': 0, 'passed': 0}
    posts: dict[str, dict] = {}
    for q in tc['queries']:
        st['queries'] += 1
        token = None
        for page in range(1, tc['pages_per_query'] + 1):
            d = harvest('/linkedin/post-search', {'search': q, 'sortBy': 'date', 'postedLimit': tc['posted_limit'],
                                                  'page': page, 'paginationToken': token}, 'search', budget)
            if not d or (d.get('status') and d.get('status') != 200):
                break
            els = d.get('elements') or []
            for el in els:
                if not is_repost(el):
                    posts.setdefault(el.get('linkedinUrl') or el.get('id'), el)
            token = (d.get('pagination') or {}).get('paginationToken') or token
            if not els:
                break
    st['posts'] = len(posts)

    short: dict[str, tuple[dict, str]] = {}
    for el in posts.values():
        a = el.get('author') or {}
        url = (a.get('linkedinUrl') or '').split('?')[0]
        k = slug(url)
        if not k or k in known or k in short:
            continue
        g = group_of(a.get('info') or '', cfg)
        if g:
            short[k] = (el, g)
    st['matched'] = len(short)

    cache = read_json('topic_profiles.json', {})
    ranked = sorted(short.items(), key=lambda kv: -(((kv[1][0].get('engagement') or {}).get('likes') or 0)
                                                    + 3 * ((kv[1][0].get('engagement') or {}).get('comments') or 0)))
    added, fresh = [], []
    for k, (el, g) in ranked:
        if k not in cache:
            if st['checked'] >= tc['max_profile_checks']:
                continue
            p = profile((el.get('author') or {}).get('linkedinUrl'), budget)
            if not p:
                continue
            st['checked'] += 1
            pos = (p.get('currentPosition') or [{}])[0] if p.get('currentPosition') else {}
            g2 = group_of(f"{p.get('headline') or ''} | {pos.get('position') or ''} | {pos.get('companyName') or ''}", cfg)
            cache[k] = {'group': g2, 'market': in_markets(p, cfg), 'headline': p.get('headline') or ''}
        c = cache[k]
        if not c['group'] or (c['group'] != 'tl' and not c['market']):
            continue
        st['passed'] += 1
        a = el.get('author') or {}
        t = {'name': a.get('name') or '', 'bucket': c['group'], 'headline': c['headline'] or a.get('info') or '',
             'profile_url': f'https://www.linkedin.com/in/{k}', 'source': 'пошук за темами', 'added': TODAY}
        added.append(t)
        if age_h(el) <= cfg['daily']['window_hours']:
            fresh.append((dict(t, bucket='topics', why=f"група {c['group']}"), el))
    write_json('topic_profiles.json', cache)
    st['new_in_active'] = merge_targets('targets_active.json', added)[0]
    return fresh, st


if __name__ == '__main__':
    cfg = config()
    b = Budget(0.4)
    fresh, st = run(cfg, b, set())
    print(st, f'свіжих дописів для підказок {len(fresh)} · ${b.usd:.2f}')
