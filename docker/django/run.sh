#!/bin/bash

echo Starting Passive Data Kit server...
source /app/venv/bin/activate

cd /app/live_site

echo Initializing database and static resources...

python3 manage.py migrate
python3 manage.py collectstatic --no-input
python3 manage.py loaddata /app/users.json
python3 manage.py loaddata /app/pdk-test-data.json

echo Validating installation...

# python3 manage.py test
python3 manage.py check

# pylint passive_data_kit
# bandit -r .

echo Starting gunicorn...
exec gunicorn live_site.wsgi --log-file - --no-control-socket --bind="0.0.0.0:$DJANGO_WEB_PORT"

# Uncomment the line below if running on a local machine, and not a server container host.
# echo Starting built-in Django web server...
# python3 manage.py runserver 0.0.0.0:$WEB_PORT -v 3
