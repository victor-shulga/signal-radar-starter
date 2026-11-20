#!/usr/bin/env python3
"""Self-check without network or keys:  python3 scripts/selftest.py  -> «selftest ok»."""
import json
import tempfile
import time
from pathlib import Path

import common
import engagers
import fetch_posts
import import_targets
import publish_page

cfg = json.loads((common.ROOT / 'config.example.json').read_text(encoding='utf-8'))

# links
assert common.canon('https://www.linkedin.com/in/Ivan-Petrov/?utm=x') == 'https://www.linkedin.com/in/ivan-petrov'
assert common.canon('https://www.linkedin.com/company/some-co/') is None
assert common.slug('https://linkedin.com/in/%D0%B0%D0%BD%D1%8F') == 'аня'

# groups
assert common.group_of('CTO · SaaS platform, Boston', cfg) == 'icp'
assert common.group_of('Head of Engineering at a startup', cfg) == 'icp'
assert common.group_of('Senior Recruiter, AI startups', cfg) is None
assert common.group_of('CEO · Software development company, outsourcing', cfg) == 'peers'
assert common.group_of('Fractional CFO for SaaS startups', cfg) == 'copilots'
assert common.group_of('Frontend developer', cfg) is None
assert common.in_markets({'location': {'parsed': {'countryCode': 'US'}}}, cfg)
assert not common.in_markets({'location': {'parsed': {'countryCode': 'CH'}}}, cfg)

# post filters and budget
assert common.killed('short') == 'закоротко'
assert common.killed('x' * 300 + ' We are hiring a PM') == 'вакансія'
now = time.time()
assert abs(common.age_h({'postedAt': {'timestamp': (now - 3600) * 1000}}, now) - 1) < 0.01
b = common.Budget(0.01)
assert b.take(0.004) and b.take(0.004) and not b.take(0.004) and b.stopped

# engagers: same person across endpoints is one key, levels by distinct posts
assert engagers.person({'actor': {'id': 'A1', 'linkedinUrl': 'https://linkedin.com/in/ACoAAx', 'name': 'N', 'position': 'P'}})['key'] == 'A1'
assert [engagers.level(n) for n in (1, 2, 3)] == ['⚪', '🟡', '🔥']

# page SQL: quotes cannot break out, state is never overwritten, engagers are a full snapshot
assert publish_page.q("it's") == "'it''s'" and publish_page.q(None) == 'NULL'
rows = publish_page.draft_rows({'date': '2026-11-05', 'buckets': {'clients': [
    {'author': "O'Neil", 'post_url': 'u1', 'comment': 'текст', 'type': 'досвід'}, {'author': 'no url'}]}}, {'u1': {'text': 'допис', 'reactions': 3}})
assert len(rows) == 1 and rows[0][11] == 'допис'
sql = publish_page.drafts_sql(rows)
assert sql.startswith('INSERT OR IGNORE') and "O''Neil" in sql
assert publish_page.engagers_sql([{'profile_url': 'https://www.linkedin.com/in/a', 'competitors': ['X', 'Y']}]).startswith('DELETE FROM engager;')

# queue priority, dedup and the 7-day skip
with tempfile.TemporaryDirectory() as tmp:
    common.ROOT = Path(tmp)
    for mod in (fetch_posts, import_targets):
        mod.read_json, mod.write_json = common.read_json, common.write_json
    p = lambda s, **kw: dict(profile_url=f'https://www.linkedin.com/in/{s}', name=s, headline='', **kw)
    common.write_json('targets_clients.json', [p('a'), p('b')])
    common.write_json('targets_active.json', [p('a', bucket='icp'), p('c', bucket='peers'), p('skip', bucket='icp')])
    common.write_json('targets_connections.json', [p('d', bucket='contacts'), p('e', cadence_checked='2026-01-01')])
    main_q, sig, rot = fetch_posts.build_queue(cfg, {'skip'})
    assert [r['profile_url'][-1] for r in main_q] == ['a', 'b', 'c'] and main_q[0]['bucket'] == 'clients'
    assert [r['profile_url'][-1] for r in rot] == ['d'] and sig == []

print('selftest ok')
