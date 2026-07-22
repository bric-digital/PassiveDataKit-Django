FROM ubuntu:24.04

# Add crontab file in the cron directory
ADD ./docker/cron/crontab /etc/cron.d/django

# Give execution rights on the cron job
RUN chmod 0644 /etc/cron.d/django

# Create the log file to be able to run tail
RUN touch /var/log/cron.log

# Install Ubuntu packages

RUN sed -i 's|http://archive.ubuntu.com|http://mirrors.ubuntu.com/mirrors.txt|g' /etc/apt/sources.list
RUN sed -i 's|http://security.ubuntu.com|http://mirrors.ubuntu.com/mirrors.txt|g' /etc/apt/sources.list

RUN apt-get update
RUN apt-get install -y apt-utils curl git build-essential python3-dev python3-venv libldap2-dev libsasl2-dev slapd ldap-utils cron gdal-bin ssmtp mailutils moreutils

WORKDIR /app

# Set up local application environment

RUN python3 -m venv /app/venv
RUN . /app/venv/bin/activate && pip install -U wheel pip
ADD requirements.txt /app/requirements.txt

WORKDIR /app/

RUN . /app/venv/bin/activate && pip install -r /app/requirements.txt

RUN . /app/venv/bin/activate && django-admin startproject live_site
ADD . /app/live_site/passive_data_kit

ADD ./docker/django/site_settings.py /app/live_site/live_site/settings.py
ADD ./docker/django/site_urls.py /app/live_site/live_site/urls.py
ADD ./docker/django/wsgi.py /app/live_site/live_site/wsgi.py
ADD .pylintrc /app/live_site/live_site.pylintrc

RUN mv /etc/environment /etc/environment.old
ADD ./docker/.env /etc/environment
RUN cat /etc/environment.old >> /etc/environment

# Setup SSMTP

ADD ./docker/cron/run.sh /app/run.sh
