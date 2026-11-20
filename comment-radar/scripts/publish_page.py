#!/usr/bin/env python3
"""Кладе підказки й «хто реагує» на вашу сторінку (база D1 у вашому Cloudflare).

    python3 scripts/publish_page.py               # drafts.json + engagers.json -> сторінка, позначка в state.json
    python3 scripts/publish_page.py --note "..."  # прогін не вдався: на сторінці з'явиться рядок із причиною
    python3 scripts/publish_page.py --export      # що опубліковано й пропущено -> journal.csv (для завдання 3)
    --local                                       # локальна база для перевірки (wrangler dev)

Стан «опублікував / пропустив» ставите ви на сторінці. Повторний запуск його не перезаписує.
Пише через wrangler, якому ви вже дали доступ до свого Cloudflare, тому окремого ключа й відкритої адреси для запису немає.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import tempfile

from common import ROOT, TODAY, read_json, slug, write_json

DB = 'comment-radar'
COLS = ('day', 'bucket', 'author', 'headline', 'profile_url', 'post_url', 'age_min', 'why', 'about', 'ctype', 'comment',
        'post_text', 'reactions', 'comments_n')
ECOLS = ('slug', 'name', 'headline', 'company', 'profile_url', 'grp', 'status', 'reactions', 'comments', 'posts', 'own_n',
         'competitors', 'score', 'level', 'last_at', 'updated')


def q(v) -> str:
    if v is None:
        return 'NULL'
    if isinstance(v, bool):
        return str(int(v))
    if isinstance(v, (int, float)):
        return str(v)
    return "'" + str(v).replace("'", "''") + "'"


def run_sql(d: dict) -> str:
    return ('INSERT OR REPLACE INTO comment_run(day,checked,posted_profiles,spent_usd,note) VALUES('
            f"{q(d.get('date') or TODAY)},{q(d.get('checked_profiles'))},{q(d.get('posted_profiles'))},"
            f"{q(d.get('spent_usd'))},{q(d.get('mix_note'))});")


def draft_rows(d: dict, media: dict) -> list[tuple]:
    out = []
    for bucket, items in (d.get('buckets') or {}).items():
        for x in items or []:
            if not x.get('post_url'):
                continue
            m = media.get(x['post_url'], {})
            out.append((d.get('date') or TODAY, bucket, x.get('author'), x.get('headline'), x.get('profile_url'), x['post_url'],
                        x.get('age_min'), x.get('why'), x.get('about'), x.get('type'), x.get('comment'),
                        m.get('text'), m.get('reactions'), m.get('comments')))
    return out


def drafts_sql(rows: list[tuple]) -> str:
    # OR IGNORE: the unique post_url keeps the state the person already set on the page
    return '\n'.join(f"INSERT OR IGNORE INTO comment_draft({','.join(COLS)}) VALUES({','.join(q(v) for v in r)});" for r in rows)


def engagers_sql(rows: list[dict]) -> str:
    lines = ['DELETE FROM engager;']
    for r in rows[:800]:
        vals = (slug(r['profile_url']), r.get('name'), r.get('headline'), r.get('company'), r['profile_url'], r.get('group'),
                r.get('status'), r.get('reactions'), r.get('comments'), r.get('posts'), r.get('own'),
                ', '.join(r.get('competitors') or []), r.get('score'), r.get('level'), r.get('last'), r.get('updated'))
        lines.append(f"INSERT OR REPLACE INTO engager({','.join(ECOLS)}) VALUES({','.join(q(v) for v in vals)});")
    return '\n'.join(lines)


def wrangler(args: list[str], local: bool) -> str:
    env = dict(os.environ, CI='1')    # no prompts inside a scheduled run
    cmd = ['npx', '--yes', 'wrangler', 'd1', 'execute', DB, '--local' if local else '--remote', '--yes'] + args
    r = subprocess.run(cmd, cwd=ROOT / 'site', env=env, capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(f'wrangler не записав у базу: {(r.stderr or r.stdout)[-400:]}')
    return r.stdout


def execute(sql: str, local: bool) -> None:
    with tempfile.NamedTemporaryFile('w', suffix='.sql', delete=False, encoding='utf-8') as f:
        f.write(sql)
    try:
        wrangler([f'--file={f.name}'], local)
    finally:
        os.unlink(f.name)


def export(local: bool) -> int:
    out = wrangler(['--json', '--command=SELECT day,bucket,author,profile_url,post_url,comment,final_comment,state,skip_reason '
                    "FROM comment_draft WHERE day >= date('now','-30 day') ORDER BY day"], local)
    rows = json.loads(out)[0]['results']
    with (ROOT / 'journal.csv').open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]) if rows else ['day'])
        w.writeheader()
        w.writerows(rows)
    print(f'journal.csv: {len(rows)} рядків')
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--note')
    ap.add_argument('--export', action='store_true')
    ap.add_argument('--local', action='store_true')
    a = ap.parse_args()
    if a.export:
        return export(a.local)
    if a.note:
        execute(run_sql({'date': TODAY, 'mix_note': a.note}), a.local)
        print('на сторінці рядок із причиною')
        return 0
    if not (ROOT / 'drafts.json').exists():
        print('немає drafts.json: спершу завдання 2 з PROMPTS.md', file=sys.stderr)
        return 2
    d = read_json('drafts.json', {})
    cand = read_json('candidates.json', {})
    media = {c['post_url']: c for c in cand.get('candidates', []) if c.get('post_url')}
    d.setdefault('spent_usd', cand.get('spent_usd'))
    rows = draft_rows(d, media)
    execute('\n'.join([run_sql(d), drafts_sql(rows), engagers_sql(read_json('engagers.json', []))]), a.local)
    # recorded only after the write succeeded: an unpublished hint must not block the author for 7 days
    state = read_json('state.json', {'log': {}})
    for items in (d.get('buckets') or {}).values():
        for x in items or []:
            if slug(x.get('profile_url', '')):
                state.setdefault('log', {})[slug(x['profile_url'])] = d.get('date') or TODAY
    write_json('state.json', state)
    print(f'на сторінці: {len(rows)} підказок')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
