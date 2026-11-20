#!/usr/bin/env bash
# Зберігає ключ сервісу в scripts/<файл>.env так, що він не з'являється на екрані й в історії команд.
#
#   bash scripts/save_key.sh harvest   # HarvestAPI  -> HARVESTAPI_KEY
#   bash scripts/save_key.sh apify     # Apify       -> APIFY_TOKEN   (за бажанням)
#   bash scripts/save_key.sh twenty    # Twenty      -> TWENTY_API_KEY
set -uo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
case "${1:-}" in
  harvest) VAR=HARVESTAPI_KEY ;;
  apify)   VAR=APIFY_TOKEN ;;
  twenty)  VAR=TWENTY_API_KEY ;;
  *) echo "Використання: bash scripts/save_key.sh harvest|apify|twenty"; exit 1 ;;
esac
read -rsp "Ключ $1: " tok
echo
[[ -n "${tok:-}" ]] || { echo "Порожньо. Скасовано."; exit 1; }
umask 077
printf '%s=%q\n' "$VAR" "$tok" > "$DIR/$1.env"
chmod 600 "$DIR/$1.env"
unset tok
echo "Збережено в scripts/$1.env (доступ лише у вас)."
