"""Self-check: python3 test_radar.py (no network, writes into a temp folder)."""
import tempfile
from datetime import date

import radar

CFG = {'name': 'jobs', 'signal_type': 'вакансія висить понад 60 днів', 'min_age_days': 60, 'window_days': 90,
       'must_words': ['backend'], 'stop_words': ['recruitment agency'],
       'fields': {'object_id': 'url', 'domain': 'company', 'title': 'title', 'date': 'posted', 'text': 'text'}}
JOB = {'url': 'https://examplepay.com/careers/1', 'company': 'https://www.examplepay.com', 'title': 'Senior Backend Engineer',
       'posted': '2026-09-01', 'text': 'We need a backend engineer for legacy payments.'}
AGENCY = {**JOB, 'url': 'https://x.io/2', 'company': 'x.io', 'text': 'backend role, recruitment agency'}

with tempfile.TemporaryDirectory() as d:
    s1 = radar.run(CFG, [JOB, AGENCY], date(2026, 10, 1), d)          # 30 days: tracked, no signal; agency filtered
    assert s1 == [], s1
    s2 = radar.run(CFG, [JOB], date(2026, 11, 5), d)                  # 65 days: stale signal once
    assert len(s2) == 1 and s2[0]['domain'] == 'examplepay.com' and s2[0]['signal_age_days'] == 65, s2
    assert radar.run(CFG, [JOB], date(2026, 11, 6), d) == []          # no repeat
    radar.run(CFG, [], date(2026, 11, 7), d)                          # gone
    state = {r['object_id']: r for r in radar.read_csv(f'{d}/jobs_state.csv')}
    assert state[JOB['url']]['gone_at'] == '2026-11-07'
    radar.run(CFG, [JOB], date(2026, 11, 10), d)                      # reappeared
    state = {r['object_id']: r for r in radar.read_csv(f'{d}/jobs_state.csv')}
    assert state[JOB['url']]['reappeared'] == '1' and state[JOB['url']]['gone_at'] == ''
    assert len(radar.read_csv(f'{d}/runs.csv')) == 5
    ev = {**CFG, 'name': 'news', 'min_age_days': 0, 'signal_type': 'раунд'}
    assert len(radar.run(ev, [JOB], date(2026, 9, 3), d)) == 1        # event radar: new = signal
print('ok')
