#!/bin/sh
set -eu
python -m pip install --require-hashes --only-binary=:all: -r requirements.txt
# Dysk nie jest dostępny podczas build; brak migracji, inicjalizacji i wysyłek.
DYNA_DATA_DIR="$(mktemp -d)" DJANGO_SETTINGS_MODULE=config.settings_static_build \
  python manage.py collectstatic --noinput
