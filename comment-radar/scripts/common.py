"""Shared helpers for the comment radar: paths, JSON files, HarvestAPI and Apify clients, post filters.

Standard library only, so the kit runs on any Mac with python3 and nothing to install.

Keys live in files next to the scripts (never in config.json, never printed):
    scripts/harvest.env   HARVESTAPI_KEY=...
    scripts/apify.env     APIFY_TOKEN=...      (optional, makes the daily post check ~3x cheaper)
    scripts/twenty.env    TWENTY_API_KEY=...   (clients and leads from your Twenty)
"""
from __future__ import annotations

import datetime
import json
import os
import re
import shlex
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
ROOT = SCRIPTS.parent
TODAY = datetime.date.today().isoformat()

HARVEST = 'https://api.harvestapi.io'
APIFY = 'https://api.apify.com/v2'
# USD per request, HarvestAPI Starter tier (harvestapi.io pricing, 10.2026). Bigger packs are cheaper.
PRICE = {'posts': 0.004, 'reactions': 0.004, 'comments': 0.004, 'search': 0.004, 'profile': 0.004}
CONCURRENCY = 5   # Starter allows 5 parallel requests


# ---- files ---------------------------------------------------------------------------------------

def load_env(name: str) -> dict:
    """KEY=value lines from scripts/<name>; values may be shell-quoted (printf %q writes them so)."""
    p = SCRIPTS / name
    if not p.exists():
        return {}
    out = {}
    for line in p.read_text(encoding='utf-8').splitlines():
        if '=' in line and not line.lstrip().startswith('#'):
            k, v = line.split('=', 1)
            out[k.strip()] = (shlex.split(v)[0] if v.strip() else '')
    return out


def secret(name: str, var: str) -> str:
    v = os.environ.get(var) or load_env(name).get(var)
    if not v:
        raise SystemExit(f'Немає ключа {var}: збережіть його в scripts/{name} (див. README)')
    return v


def read_json(name: str, default):
    p = ROOT / name
    if not p.exists():
        return default
    return json.loads(p.read_text(encoding='utf-8'))


def write_json(name: str, data) -> None:
    p = ROOT / name
    tmp = p.with_name(p.name + '.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(tmp, p)


def config() -> dict:
    p = ROOT / 'config.json'
    if not p.exists():
        raise SystemExit('Немає config.json поруч із README')
    return json.loads(p.read_text(encoding='utf-8'))


# ---- people --------------------------------------------------------------------------------------

def slug(url: str) -> str:
    """linkedin.com/in/<slug> -> slug, lower-case and URL-decoded (CRM exports store Cyrillic slugs encoded)."""
    m = re.search(r'linkedin\.com/in/([^/?#]+)', url or '', re.I)
    return urllib.parse.unquote(m.group(1) if m else '').lower().rstrip('/')


def canon(url: str) -> str | None:
    """Any profile link form -> https://www.linkedin.com/in/<slug>. Company pages and junk -> None."""
    s = (url or '').strip()
    if not s or '/company/' in s or '/school/' in s:
        return None
    if 'linkedin.com/in/' not in s.lower():
        s = s.strip('/@ ')
        return f'https://www.linkedin.com/in/{s}' if re.fullmatch(r'[\w\-%.]{3,100}', s) else None
    sl = slug(s)
    return f'https://www.linkedin.com/in/{sl}' if sl else None


def merge_targets(name: str, rows: list[dict]) -> tuple[int, int]:
    """Append rows to a targets file, dedup by slug, keep existing records (and their history). -> (added, total)."""
    cur = read_json(name, [])
    seen = {slug(r.get('profile_url', '')) for r in cur}
    added = 0
    for r in rows:
        s = slug(r.get('profile_url', ''))
        if s and s not in seen:
            cur.append(r)
            seen.add(s)
            added += 1
    write_json(name, cur)
    return added, len(cur)


def group_of(text: str, cfg: dict) -> str | None:
    """Headline / position / company -> one of the config groups by keyword rules, or None.
    Exclusions (recruiters, competitors, streamers) win over everything."""
    t = text or ''
    for pat in cfg['groups'].get('exclude', {}).get('keywords', []):
        if re.search(pat, t, re.I):
            return None
    for g in ('copilots', 'icp', 'peers', 'tl'):   # vendors first: «CEO of a construction SaaS» is not a buyer
        for pat in cfg['groups'][g].get('keywords', []):
            if re.search(pat, t, re.I):
                return g
    return None


def in_markets(profile: dict, cfg: dict) -> bool:
    """Country of a HarvestAPI profile is one of the target markets (country codes in config)."""
    loc = profile.get('location') or {}
    code = ((loc.get('parsed') or {}).get('countryCode') or '').upper()
    if code:
        return code in {c.upper() for c in cfg['markets']['country_codes']}
    text = f"{loc.get('linkedinText') or loc.get('text') or ''}"
    return any(n.lower() in text.lower() for n in cfg['markets']['names'])


# ---- posts ---------------------------------------------------------------------------------------

MIN_CHARS = 250
KILL = [
    (r"\b(hiring|we are looking for|open position|apply now|send your (cv|resume)|join our team)\b", 'вакансія'),
    (r'#hiring|#job|#vacancy', 'вакансія'),
    (r'\b(book a demo|register now|limited seats|tickets are limited|visit us at|meet us at|booth)\b',
     'реклама/захід'),
    (r'(\+\d{1,3}[\s-]?\d{6,})', 'реклама з телефоном'),
]


def killed(text: str) -> str | None:
    if len((text or '').strip()) < MIN_CHARS:
        return 'закоротко'
    for pat, why in KILL:
        if re.search(pat, text, re.I | re.M):
            return why
    return None


def age_h(post: dict, now: float | None = None) -> float:
    """Hours since the post was published; unknown date -> very old."""
    pa = post.get('postedAt') or {}
    ts = pa.get('timestamp') if isinstance(pa, dict) else None
    if isinstance(ts, (int, float)) and ts > 0:
        ts = ts / 1000 if ts > 1e12 else ts
        return ((now or time.time()) - ts) / 3600
    m = re.match(r'(\d+)\s*(mo|m|h|d|w|y)', (pa.get('postedAgoShort') if isinstance(pa, dict) else '') or '')
    if not m:
        return 9e9
    n, u = int(m.group(1)), m.group(2)
    return n * {'m': 1 / 60, 'h': 1, 'd': 24, 'w': 168, 'mo': 720, 'y': 8760}[u]


def is_repost(post: dict) -> bool:
    return bool(post.get('repost') or post.get('repostId') or post.get('type') == 'repost')


# ---- HarvestAPI ----------------------------------------------------------------------------------

class Budget:
    """Spend guard for one run: refuses a paid request that would cross the cap."""
    def __init__(self, cap_usd: float):
        self.cap, self.usd, self.requests, self.stopped = cap_usd, 0.0, 0, False
        self._lock = threading.Lock()

    def take(self, usd: float) -> bool:
        with self._lock:
            if self.usd + usd > self.cap + 1e-9:
                self.stopped = True
                return False
            self.usd += usd
            self.requests += 1
            return True


def _http(url: str, headers: dict, data: bytes | None = None, timeout: int = 120) -> dict:
    # python-urllib's default User-Agent is blocked by Cloudflare in front of these APIs (HTTP 403)
    req = urllib.request.Request(url, data=data, headers={'User-Agent': 'curl/8.4.0', **headers},
                                 method='POST' if data is not None else 'GET')
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def harvest(path: str, params: dict, kind: str, budget: Budget, retries: int = 4) -> dict | None:
    """One paid GET. None when the budget is spent. Retries 429/5xx; 401/402 stop the run with a clear message."""
    if not budget.take(PRICE[kind]):
        return None
    q = urllib.parse.urlencode({k: v for k, v in params.items() if v not in (None, '')})
    hdr = {'X-API-Key': secret('harvest.env', 'HARVESTAPI_KEY')}
    for attempt in range(retries + 1):
        try:
            return _http(f'{HARVEST}{path}?{q}', hdr)
        except urllib.error.HTTPError as e:
            if e.code == 401:
                raise SystemExit('HarvestAPI 401: неправильний ключ у scripts/harvest.env')
            if e.code == 402:
                raise SystemExit('HarvestAPI 402: закінчилися кредити, поповніть баланс на harvestapi.io')
            if e.code not in (429, 500, 502, 503, 504) or attempt == retries:
                print(f'HarvestAPI {path}: HTTP {e.code}', flush=True)
                return {}
        except (urllib.error.URLError, TimeoutError) as e:
            if attempt == retries:
                print(f'HarvestAPI {path}: {e}', flush=True)
                return {}
        time.sleep(2 ** attempt * 2)
    return {}


def fan_out(fn, items):
    with ThreadPoolExecutor(CONCURRENCY) as ex:
        return list(ex.map(fn, items))


def profile_posts(url: str, posted_limit: str, budget: Budget) -> list[dict] | None:
    """First page of a person's posts (up to 50, one request), reposts dropped."""
    d = harvest('/linkedin/profile-posts', {'profile': url, 'postedLimit': posted_limit}, 'posts', budget)
    if d is None:
        return None   # budget spent: not checked, which is not the same as silent
    # the API does not always respect postedLimit (old and pinned posts come back), so the window is enforced here
    hours = {'24h': 24, 'week': 168, 'month': 744}[posted_limit] + 12
    return [p for p in d.get('elements') or [] if not is_repost(p) and age_h(p) <= hours]


def paged(path: str, params: dict, kind: str, budget: Budget, max_items: int) -> list[dict]:
    out, page, token = [], 1, None
    while len(out) < max_items:
        d = harvest(path, dict(params, page=page, paginationToken=token), kind, budget)
        if not d:
            break
        els = d.get('elements') or []
        out.extend(els)
        pag = d.get('pagination') or {}
        token = pag.get('paginationToken') or token
        if not els or (pag.get('totalPages') and page >= pag['totalPages']) or len(els) < (pag.get('pageSize') or 0):
            break
        page += 1
    return out[:max_items]


def profile(url: str, budget: Budget) -> dict:
    """Short profile ($0.004): headline, current position, location."""
    d = harvest('/linkedin/profile', {'query': url, 'main': 'true'}, 'profile', budget) or {}
    if d.get('error'):
        print(f"HarvestAPI profile {url[:70]}: {str(d['error'])[:120]}", flush=True)
    return d.get('element') or {}


# ---- Apify (optional, only for the daily post check) ---------------------------------------------

APIFY_ACTOR = 'harvestapi~linkedin-profile-posts'


def apify_posts(urls: list[str], posted_limit: str, max_posts: int, cap_usd: float) -> tuple[list[dict], float]:
    """The same HarvestAPI scraper run as an Apify actor: $0.001 per silent profile instead of $0.004
    per request, which is what makes 400 profiles a day affordable. -> (posts, usd)."""
    tok = secret('apify.env', 'APIFY_TOKEN')
    body = json.dumps({'targetUrls': urls, 'maxPosts': max_posts, 'postedLimit': posted_limit,
                       'includeReposts': False, 'includeQuotePosts': True}).encode()
    run = _http(f'{APIFY}/acts/{APIFY_ACTOR}/runs?maxTotalChargeUsd={cap_usd}',
                {'Authorization': f'Bearer {tok}', 'Content-Type': 'application/json'}, body)['data']
    deadline = time.time() + 1800
    while run.get('status') in ('READY', 'RUNNING') and time.time() < deadline:
        time.sleep(10)
        run = _http(f"{APIFY}/actor-runs/{run['id']}", {'Authorization': f'Bearer {tok}'})['data']
    items = _http(f"{APIFY}/datasets/{run['defaultDatasetId']}/items?clean=true",
                  {'Authorization': f'Bearer {tok}'}, timeout=300)
    print(f"Apify: {run.get('status')} · {len(items)} дописів · ${run.get('usageTotalUsd') or 0:.3f}", flush=True)
    return [p for p in items if isinstance(p, dict) and not is_repost(p)], float(run.get('usageTotalUsd') or 0)


def post_author_url(post: dict) -> str:
    a = post.get('author') or {}
    q = post.get('query') or {}
    return canon(q.get('targetUrl') or a.get('linkedinUrl') or '') or ''


def posts_by_profile(urls: list[str], posted_limit: str, max_posts: int, cap_usd: float) -> tuple[dict, float, int]:
    """Posts of many people at once -> ({slug: [posts newest first]}, usd, profiles checked).
    A profile the budget did not reach is absent from the dict (unchecked), not an empty list (silent).
    Apify when scripts/apify.env exists (cheaper on silent profiles), otherwise HarvestAPI directly."""
    urls = list(dict.fromkeys(u for u in urls if u))
    out: dict[str, list] = {}
    if (SCRIPTS / 'apify.env').exists() or os.environ.get('APIFY_TOKEN'):
        items, usd = apify_posts(urls, posted_limit, max_posts, cap_usd)
        out = {slug(u): [] for u in urls}
        for p in items:
            out.setdefault(slug(post_author_url(p)), []).append(p)
        checked = len(urls)
    else:
        budget = Budget(cap_usd)
        for u, posts in zip(urls, fan_out(lambda u: profile_posts(u, posted_limit, budget), urls)):
            if posts is not None:
                out[slug(u)] = posts
        usd, checked = budget.usd, budget.requests
        if budget.stopped:
            print(f'⚠️ ліміт ${cap_usd} вичерпано: перевірено {checked} з {len(urls)} профілів', flush=True)
    for k in out:
        out[k] = sorted(out[k], key=age_h)[:max_posts]
    return out, usd, checked
