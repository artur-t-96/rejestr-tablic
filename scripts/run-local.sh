#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
if [ ! -x .venv/bin/python ]; then
  echo 'Utwórz środowisko .venv i zainstaluj requirements.txt zgodnie z README.md.'
  exit 1
fi
.venv/bin/python manage.py migrate --noinput
.venv/bin/python manage.py seed_local
# Lokalne uruchomienie obejmuje powiadomienia III, zaproszenia i wygaszanie rezerwacji.
# Pozostałe kanały korespondencji uruchamia się osobno po konfiguracji.
.venv/bin/python manage.py process_integrations --watch --interval 30 --provider SMTP --operation DECISION_NOTICE &
queue_pid=$!
.venv/bin/python manage.py process_account_invitations --watch --interval 30 &
invitation_pid=$!
.venv/bin/python manage.py expire_reservations --watch --interval 30 &
reservation_pid=$!
.venv/bin/python manage.py runserver 127.0.0.1:8765 --noreload --insecure &
web_pid=$!
cleanup() {
  kill "$web_pid" "$queue_pid" "$invitation_pid" "$reservation_pid" 2>/dev/null || true
  wait "$web_pid" 2>/dev/null || true
  wait "$queue_pid" 2>/dev/null || true
  wait "$invitation_pid" 2>/dev/null || true
  wait "$reservation_pid" 2>/dev/null || true
}
trap cleanup 0
trap 'exit 130' INT
trap 'exit 143' TERM HUP
wait "$web_pid"
