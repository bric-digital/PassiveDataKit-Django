#!/bin/bash

set -euo pipefail

job="${1:-312}"
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
postgres_container="pdk-circleci-postgres-${job}-$$"

cleanup() {
  docker rm -f "$postgres_container" >/dev/null 2>&1 || true
}

trap cleanup EXIT

case "$job" in
  312)
    python_image="cimg/python:3.12"
    postgres_image="cimg/postgres:14.18-postgis"
    venv_command='python3 -m venv --copies /home/circleci/venv'
    startproject_command='django-admin startproject pdk'
    ;;
  310)
    python_image="cimg/python:3.10"
    postgres_image="cimg/postgres:14.18-postgis"
    venv_command='python3 -m venv --copies /home/circleci/venv'
    startproject_command='django-admin startproject pdk'
    ;;
  39)
    python_image="cimg/python:3.9"
    postgres_image="cimg/postgres:12.18-postgis"
    venv_command='python3 -m venv --copies /home/circleci/venv'
    startproject_command='django-admin startproject pdk'
    ;;
  38)
    python_image="cimg/python:3.8"
    postgres_image="cimg/postgres:12.18-postgis"
    venv_command='python3 -m venv --copies /home/circleci/venv'
    startproject_command='django-admin startproject pdk'
    ;;
  37)
    python_image="cimg/python:3.7"
    postgres_image="cimg/postgres:9.6-postgis"
    venv_command='python3 -m venv --copies /home/circleci/venv'
    startproject_command='django-admin.py startproject pdk'
    ;;
  36)
    python_image="cimg/python:3.6"
    postgres_image="cimg/postgres:9.6-postgis"
    venv_command='python3 -m venv --copies /home/circleci/venv'
    startproject_command='django-admin.py startproject pdk'
    ;;
  27)
    python_image="cimg/python:2.7"
    postgres_image="cimg/postgres:9.6-postgis"
    venv_command='virtualenv --copies /home/circleci/venv'
    startproject_command='django-admin.py startproject pdk'
    ;;
  *)
    echo "Unknown CircleCI job version: $job" >&2
    echo "Expected one of: 312 310 39 38 37 36 27" >&2
    exit 1
    ;;
esac

echo "Starting ${postgres_image} as ${postgres_container}..."
docker run -d \
  --name "$postgres_container" \
  -e POSTGRES_USER=root \
  -e POSTGRES_DB=circle_test \
  -e POSTGRES_PASSWORD= \
  "$postgres_image" >/dev/null

echo "Waiting for Postgres to become healthy..."
for _ in $(seq 1 60); do
  status="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$postgres_container")"

  if [[ "$status" == "healthy" || "$status" == "running" ]]; then
    break
  fi

  sleep 2
done

status="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$postgres_container")"

if [[ "$status" != "healthy" && "$status" != "running" ]]; then
  echo "Postgres container did not become ready." >&2
  docker logs "$postgres_container" >&2 || true
  exit 1
fi

echo "Running CircleCI build-${job} locally with ${python_image}..."
docker run --rm \
  --network "container:${postgres_container}" \
  -v "${repo_root}:/mnt/project:ro" \
  -w /mnt/project \
  "$python_image" \
  /bin/bash -lc "
    set -euo pipefail
    sudo apt-get update && sudo apt-get install -y gdal-bin
    ${venv_command}
    . /home/circleci/venv/bin/activate
    pip install -U pip
    pip install wheel
    rm -rf /tmp/circleci-run
    mkdir -p /tmp/circleci-run/project
    cp -a /mnt/project/. /tmp/circleci-run/project/
    cd /tmp/circleci-run/project
    pip install -r requirements.txt --progress-bar off
    cd ..
    rm -rf django passive_data_kit
    mv project passive_data_kit
    mkdir django
    cd django
    ${startproject_command}
    mv ../passive_data_kit pdk
    cd pdk
    cp passive_data_kit/.circleci/circle_settings.py pdk/settings.py
    cp passive_data_kit/.circleci/circle_urls.py pdk/urls.py
    python manage.py migrate
    python manage.py pdk_generate_backup_key
    python manage.py test
    cp passive_data_kit/.pylintrc .
    pylint passive_data_kit
    bandit -r .
  "
