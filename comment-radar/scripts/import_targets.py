#!/usr/bin/env python3
"""Завантаження своїх списків людей із таблиці CSV.

    python3 scripts/import_targets.py Connections.csv --list contacts   # ваші контакти LinkedIn -> ротація
    python3 scripts/import_targets.py signals.csv --list signals        # керівники компаній із сигналом
    python3 scripts/import_targets.py people.csv --list watchlist       # кого дивитися завжди
    python3 scripts/import_targets.py clients.csv --list clients        # клієнти й ліди, перевіряються першими

Назви колонок будь-які: скрипт сам знаходить посилання на LinkedIn, ім'я, посаду, компанію й сигнал.
Обов'язкова одна колонка: посилання на профіль. Сторінки компаній і порожні рядки відкидаються,
повтори прибираються. У файл експорту LinkedIn (Connections.csv) зверху вписано 3 рядки приміток,
скрипт їх пропускає.

Клієнти й ліди приходять із Twenty (twenty_sync.py). --list clients потрібен, лише поки Twenty не підключено.
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

from common import TODAY, canon, config, group_of, merge_targets

COLS = {
    'url': ('linkedin', 'url', 'profile', 'профіль', 'посилання'),
    'first': ('first name', 'firstname', 'ім\'я'),
    'last': ('last name', 'lastname', 'прізвище'),
    'name': ('full name', 'name', 'contact', 'контакт'),
    'position': ('position', 'title', 'job', 'посада', 'headline'),
    'company': ('company', 'account', 'organization', 'компанія'),
    'signal': ('signal', 'сигнал', 'trigger', 'why'),
}
FILES = {'contacts': 'targets_connections.json', 'signals': 'targets_signals.json',
         'watchlist': 'targets_watchlist.json', 'clients': 'targets_clients.json'}


def find_col(header: list[str], keys: tuple[str, ...]) -> int | None:
    low = [(h or '').strip().lower() for h in header]
    for k in keys:                      # exact header first: «Name» must not grab «First Name»
        if k in low:
            return low.index(k)
    for i, h in enumerate(low):
        if any(k in h for k in keys):
            return i
    return None


def rows_of(path: Path) -> list[list[str]]:
    lines = path.read_text(encoding='utf-8-sig', errors='replace').splitlines()
    # LinkedIn export starts with free-text notes; the real header is the first line with a URL column
    start = next((i for i, l in enumerate(lines[:20]) if 'url' in l.lower() or 'linkedin' in l.lower()), 0)
    body = '\n'.join(lines[start:])
    try:
        dialect = csv.Sniffer().sniff(body[:4000], delimiters=',;\t|')
    except csv.Error:
        dialect = csv.excel
    return list(csv.reader(body.splitlines(), dialect))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('csv_file')
    ap.add_argument('--list', required=True, choices=list(FILES))
    a = ap.parse_args()
    path = Path(a.csv_file)
    if not path.exists():
        print(f'не знайшов файл: {path}', file=sys.stderr)
        return 2
    rows = rows_of(path)
    if len(rows) < 2:
        print('у таблиці немає рядків', file=sys.stderr)
        return 2
    header, body = rows[0], rows[1:]
    idx = {k: find_col(header, keys) for k, keys in COLS.items()}
    if idx['url'] is None:
        print(f"немає колонки з посиланням на LinkedIn. Колонки: {', '.join(h for h in header if h)}.\n"
              'Перейменуйте потрібну на «linkedin» і повторіть.', file=sys.stderr)
        return 2

    cfg = config()
    out, bad = [], 0
    for row in body:
        def cell(k):
            i = idx[k]
            return row[i].strip() if i is not None and i < len(row) else ''
        url = canon(cell('url'))
        if not url:
            bad += 1
            continue
        name = f"{cell('first')} {cell('last')}".strip() or cell('name')
        headline = ' · '.join(x for x in (cell('position'), cell('company')) if x)
        rec = {'name': name or '—', 'headline': headline, 'company': cell('company'), 'profile_url': url,
               'source': f'{path.name}', 'added': TODAY}
        if a.list == 'contacts':
            rec['bucket'] = group_of(headline, cfg) or 'contacts'
        elif a.list == 'signals':
            rec['bucket'], rec['why'] = 'signals', cell('signal')
        else:
            rec['bucket'] = a.list
        out.append(rec)

    added, total = merge_targets(FILES[a.list], out)
    print(f'Додано: {added} · уже були: {len(out) - added} · без посилання на профіль: {bad}')
    print(f'У {FILES[a.list]} тепер: {total}')
    if a.list == 'contacts':
        print('Контакти перевіряються по черзі, до 150 на день. Хто публікує, переходить в активні сам.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
