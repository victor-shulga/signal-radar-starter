#!/usr/bin/env python3
"""Щоденний збір свіжих дописів -> candidates.json. Коментарі за ним пише Claude (PROMPTS.md, завдання 2).

    python3 scripts/fetch_posts.py

Порядок груп = пріоритет (config.json -> daily):
  1. clients    : клієнти й ліди з Twenty (twenty_sync.py), усі й першими
  2. engagers   : топ-15 тих, хто приходив під дописи автора
  3. warm       : теплі після оцінки (60+ балів)
  4. watchlist  : свій список «дивитися завжди»
  5. active     : усі, хто публікував за останній місяць
  6. signals    : керівники компаній із сигналом, понад загальний ліміт
  7. contacts   : ротація за вашими контактами: 150 місць заброньовано наперед, вікно місяць, 1 допис.
                  Це замір, чи людина взагалі публікує; хто публікує, переходить в active
  8. topics     : нові автори з пошуку за темами (topic_fetch.py)

Вікно свіжості 40 годин. Тих, кому готували підказку за останні 7 днів, пропускаємо.
"""
from __future__ import annotations

import re

import topic_fetch
from common import (Budget, TODAY, age_h, config, killed, merge_targets, posts_by_profile, read_json, slug,
                    write_json)

ORDER = ['clients', 'engagers', 'warm', 'watchlist', 'active', 'signals', 'contacts', 'topics']
TOPICS_USD = 0.25


def excluded(text: str, cfg: dict) -> bool:
    return any(re.search(p, text or '', re.I) for p in cfg['groups'].get('exclude', {}).get('keywords', []))


def recent_slugs(state: dict, days: int) -> set[str]:
    import datetime
    edge = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
    return {k for k, d in (state.get('log') or {}).items() if d >= edge}


def build_queue(cfg: dict, skip: set[str]) -> tuple[list[dict], list[dict], list[dict]]:
    """-> (main, signals, rotation). Each row carries its queue `part`; first appearance of a person wins."""
    d = cfg['daily']
    seen = set(skip)

    def take(rows, part, bucket=None):
        out = []
        for r in rows:
            k = slug(r.get('profile_url', ''))
            if k and k not in seen and not excluded(r.get('headline', ''), cfg):
                seen.add(k)
                out.append(dict(r, part=part, bucket=bucket or r.get('bucket') or part))
        return out

    main = take(read_json('targets_clients.json', []), 'clients', 'clients')
    main += take(read_json('targets_engagers.json', [])[:d['engagers_top']], 'engagers', 'engagers')
    main += take(read_json('targets_warm.json', []), 'warm')
    main += take(read_json('targets_watchlist.json', []), 'watchlist', 'watchlist')
    room = max(0, d['max_profiles'] - d['rotation_reserved'] - len(main))
    active = sorted(read_json('targets_active.json', []), key=lambda r: r.get('last_post') or '', reverse=True)
    main += take(active, 'active')[:room]
    signals = take(read_json('targets_signals.json', []), 'signals', 'signals')
    rotation = take([r for r in read_json('targets_connections.json', []) if not r.get('cadence_checked')],
                    'contacts')[:d['rotation_reserved']]
    return main, signals, rotation


def candidate(t: dict, p: dict) -> dict:
    a = p.get('author') or {}
    eng = p.get('engagement') or {}
    return {'bucket': t['bucket'], 'why': t.get('why', ''), 'author': t.get('name') or a.get('name', ''),
            'headline': t.get('headline') or a.get('info', ''), 'profile_url': t['profile_url'],
            'post_url': p.get('linkedinUrl') or '', 'age_min': round(age_h(p) * 60),
            'reactions': eng.get('likes', 0), 'comments': eng.get('comments', 0),
            'text': (p.get('content') or '').strip()[:2200]}


def main() -> int:
    cfg = config()
    d = cfg['daily']
    state = read_json('state.json', {'log': {}})
    skip = recent_slugs(state, d['skip_days'])
    main_q, signals, rotation = build_queue(cfg, skip)
    print('черга: ' + ' · '.join(f'{p} {sum(1 for r in main_q + signals + rotation if r["part"] == p)}'
                                   for p in ORDER[:-1]) + f' · пропущено (підказка за {d["skip_days"]} дн.) {len(skip)}')

    posts_usd = d['max_usd'] - (TOPICS_USD if cfg['topics'].get('enabled') else 0)
    n_week, n_month = len(main_q) + len(signals), len(rotation)
    cap_week = round(posts_usd * n_week / max(1, n_week + n_month), 3)
    week, usd1, checked1 = posts_by_profile([r['profile_url'] for r in main_q + signals], 'week', 2, cap_week)
    month, usd2, checked2 = (posts_by_profile([r['profile_url'] for r in rotation], 'month', 1,
                                              round(posts_usd - usd1, 3)) if rotation else ({}, 0.0, 0))

    cands, dropped, posted = [], {}, 0

    def consider(t, ps):
        nonlocal posted
        fresh = [p for p in ps if age_h(p) <= d['window_hours']]
        posted += bool(fresh)
        for p in fresh:
            why = killed(p.get('content') or '')
            if why:
                dropped[why] = dropped.get(why, 0) + 1
            else:
                cands.append(candidate(t, p))

    for t in main_q + signals:
        consider(t, week.get(slug(t['profile_url'])) or [])

    # rotation: mark checked, move whoever posted this month into the active list
    conns = read_json('targets_connections.json', [])
    by_slug = {slug(r['profile_url']): r for r in conns}
    moved = []
    for t in rotation:
        k = slug(t['profile_url'])
        if k not in month:
            continue
        by_slug[k]['cadence_checked'] = TODAY
        if month[k]:
            moved.append({x: t[x] for x in ('name', 'headline', 'profile_url', 'bucket') if x in t})
            consider(t, month[k])
    if conns:
        write_json('targets_connections.json', conns)
    n_moved = merge_targets('targets_active.json', moved)[0] if moved else 0

    t_usd, t_stats = 0.0, {}
    if cfg['topics'].get('enabled'):
        known = {slug(r['profile_url']) for r in main_q + signals + rotation} | skip
        known |= {slug(r['profile_url']) for r in read_json('targets_active.json', [])}
        b = Budget(TOPICS_USD)
        fresh, t_stats = topic_fetch.run(cfg, b, known)
        t_usd = b.usd
        for t, p in fresh:
            why = killed(p.get('content') or '')
            if not why:
                cands.append(candidate(t, p))

    uniq = {c['post_url'] or id(c): c for c in cands}
    cands = sorted(uniq.values(), key=lambda c: (ORDER.index(c['bucket']) if c['bucket'] in ORDER else 4, c['age_min']))
    checked = checked1 + checked2
    out = {'date': TODAY, 'checked_profiles': checked, 'posted_profiles': posted, 'max_drafts': d['max_drafts'],
           'spent_usd': round(usd1 + usd2 + t_usd, 3), 'dropped': dropped, 'rotation_moved_to_active': n_moved,
           'topics': t_stats, 'candidates': cands}
    write_json('candidates.json', out)
    by_b = {}
    for c in cands:
        by_b[c['bucket']] = by_b.get(c['bucket'], 0) + 1
    print(f'перевірено {checked} · публікували за {d["window_hours"]} год: {posted} · відсіяно {dropped} · '
          f'з контактів в активні +{n_moved}')
    print(f'теми: {t_stats}')
    print(f'кандидатів {len(cands)}: {by_b} · витрачено ${out["spent_usd"]:.2f}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
