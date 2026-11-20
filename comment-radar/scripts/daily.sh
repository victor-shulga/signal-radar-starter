#!/usr/bin/env bash
# Ранковий збір: клієнти з Twenty -> свіжі дописи -> candidates.json.
# Коментарі за candidates.json пише Claude (PROMPTS.md, завдання 2), потім publish_page.py кладе їх на сторінку.
# Щопонеділка оновлює «хто реагує», у перший робочий день місяця перевіряє активність усіх списків.
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

if [[ -f twenty.env ]]; then
  python3 twenty_sync.py || echo "⚠️ Twenty не оновився, беру вчорашній список клієнтів"
else
  echo "Twenty не підключено (немає scripts/twenty.env), група «клієнти» порожня"
fi

dom=$((10#$(date +%d))); dow=$(date +%u)   # 10#: «08» і «09» не вісімкові
if [[ "$dow" -le 5 && ( "$dom" -eq 1 || ( "$dom" -le 3 && "$dow" == 1 ) ) ]]; then
  echo "Перший робочий день місяця: перевіряю активність усіх списків"
  python3 check_activity.py
fi
if [[ "$dow" == 1 ]]; then
  echo "Понеділок: оновлюю «хто реагує»"
  python3 engagers.py || echo "⚠️ engagers.py впав, беру список минулого тижня"
fi

python3 fetch_posts.py
