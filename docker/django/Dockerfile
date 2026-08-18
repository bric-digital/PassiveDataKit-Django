FROM ubuntu:24.04

WORKDIR /app

RUN sed -i 's|http://archive.ubuntu.com|http://mirrors.ubuntu.com/mirrors.txt|g' /etc/apt/sources.list
RUN sed -i 's|http://security.ubuntu.com|http://mirrors.ubuntu.com/mirrors.txt|g' /etc/apt/sources.list

RUN apt-get update
RUN apt-get install -y apt-utils curl
RUN apt-get install -y python3-dev gdal-bin python3-venv

RUN python3 -m venv /app/venv
RUN . /app/venv/bin/activate && pip install -U wheel pip
ADD ./requirements.txt /app/requirements.txt
RUN . /app/venv/bin/activate && pip install -r requirements.txt

RUN . /app/venv/bin/activate && django-admin startproject live_site
ADD . /app/live_site/passive_data_kit

ADD ./docker/django/site_settings.py /app/live_site/live_site/settings.py
ADD ./docker/django/site_urls.py /app/live_site/live_site/urls.py
ADD ./docker/django/wsgi.py /app/live_site/live_site/wsgi.py
ADD ./.pylintrc /app/live_site/.pylintrc

ADD ./docker/data/users.json /app/users.json
ADD ./docker/data/pdk-test-data.json /app/pdk-test-data.json

ADD ./docker/django/run.sh /app/run.sh

EXPOSE ${WEB_PORT}
