#!/usr/bin/env python3
"""Хто взагалі публікує: перевірка всіх списків за останній місяць -> targets_active.json.

    python3 scripts/check_activity.py          # після першого завантаження, далі перший робочий день місяця

Профіль без дописів за місяць у щоденну перевірку не йде: під ним нічого коментувати, а платити
щодня за його тишу немає сенсу. Його перевірять знову за місяць.

Заодно перепризначає лідерів думок за фактом: медіана від 25 реакцій на останніх дописах -> група tl
(попередня група зберігається в bucket_before). Активні, які мовчать понад 60 днів, прибираються.
"""
from __future__ import annotations

import datetime
import statistics

from common import TODAY, age_h, config, posts_by_profile, read_json, slug, write_json

SOURCES = ['targets_watchlist.json', 'targets_signals.json', 'targets_warm.json', 'targets_connections.json',
           'targets_active.json']
TL_MEDIAN = 25


def main() -> int:
    cfg = config()
    people: dict[str, dict] = {}
    for name in SOURCES:
        for r in read_json(name, []):
            people.setdefault(slug(r['profile_url']), r)
    urls = [r['profile_url'] for r in people.values()]
    print(f'перевіряю {len(urls)} профілів за місяць')
    posts, usd, checked = posts_by_profile(urls, 'month', 3, cfg['once']['activity_max_usd'])

    active = {slug(r['profile_url']): r for r in read_json('targets_active.json', [])}
    became, dropped, to_tl = 0, 0, 0
    for k, r in people.items():
        if k not in posts:
            continue                                      # budget did not reach it: leave as is
        ps = posts[k]
        if ps:
            r['last_post'] = (datetime.datetime.now() - datetime.timedelta(hours=min(age_h(ps[0]), 24 * 400))).date().isoformat()
            likes = [(p.get('engagement') or {}).get('likes') or 0 for p in ps]
            r['median_reactions'] = statistics.median(likes)
            if r['median_reactions'] >= TL_MEDIAN and r.get('bucket') not in ('tl', 'clients', 'watchlist', 'signals'):
                r['bucket_before'], r['bucket'] = r.get('bucket'), 'tl'
                to_tl += 1
            if k not in active:
                became += 1
            active[k] = r
        elif k in active and (r.get('last_post') or '0000') < _days_ago(60):
            del active[k]
            dropped += 1
        r['cadence_checked'] = TODAY

    write_json('targets_active.json', list(active.values()))
    for name in SOURCES[:-1]:                          # keep cadence_checked in the source lists too
        rows = read_json(name, [])
        if rows:
            write_json(name, [people.get(slug(r['profile_url']), r) for r in rows])

    n = len(active)
    print(f'перевірено {checked} · активних {n} ({n * 100 // max(1, len(people))}%) · нових {became} · '
          f'прибрано тих, хто мовчить 60+ днів, {dropped} · у лідери думок {to_tl} · ${usd:.2f}')
    print(f'це приблизно {n // 20} коментарів на день (на один коментар потрібно ~20 активних профілів)')
    return 0


def _days_ago(n: int) -> str:
    return (datetime.date.today() - datetime.timedelta(days=n)).isoformat()


if __name__ == '__main__':
    raise SystemExit(main())
