# -*- coding: utf-8 -*-
# pylint: disable=no-member, line-too-long

import datetime
import os
import time

import arrow

from requests_oauthlib import OAuth1Session

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from ...decorators import handle_lock
from ...models import DataPoint

GENERATOR_NAME = 'pdk-withings-device: Passive Data Kit Server'

class Command(BaseCommand):
    help = 'Compiles data reports requested by end users.'

    def add_arguments(self, parser):
        parser.add_argument('--start',
                            type=str,
                            dest='start',
                            help='Start of date range to retrieve Withings data in format YYYY-MM-DD')

        parser.add_argument('--end',
                            type=str,
                            dest='end',
                            help='End of date range to retrieve Withings data in format YYYY-MM-DD')

    @handle_lock
    def handle(self, *args, **options): # pylint: disable=too-many-locals,too-many-branches,too-many-statements
        os.umask(000)

        start = options['start']
        if start is None:
            start = (timezone.now() - datetime.timedelta(days=1)).strftime('%Y-%m-%d')

        end = options['end']

        if end is None:
            end = timezone.now().strftime('%Y-%m-%d')

        start_date = arrow.get(start).replace(hour=0, minute=0, second=0).to(settings.TIME_ZONE)
        end_date = arrow.get(end).replace(hour=0, minute=0, second=0).to(settings.TIME_ZONE)

        sources = DataPoint.objects.order_by('source').values_list('source', flat=True).distinct()

        for source in sources:
            data_point = DataPoint.objects.filter(source=source, generator_identifier='pdk-withings-device').order_by('-created').first()

            if data_point is not None:
                properties = data_point.fetch_properties()

                if 'oauth_user_token' in properties and 'oauth_user_secret' in properties and 'oauth_user_id' in properties:
                    index_date = start_date

                    while index_date < end_date:
                        next_day = index_date.replace(days=+1)

    #                    print('FETCHING INTRADAY FOR ' + source + ': ' + str(index_date) + ': ' + str(next_day))

                        fetch_intraday(source, properties, index_date, next_day)

                        time.sleep(1)

    #                    print('FETCHING SLEEP MEASURES FOR ' + source + ': ' + str(index_date) + ': ' + str(next_day))

                        fetch_sleep_measures(source, properties, index_date, next_day)

                        time.sleep(1)

                        index_date = next_day


def fetch_intraday(user_id, properties, start_date, end_date): # pylint: disable=too-many-locals, too-many-statements, too-many-branches
    api_url = 'https://wbsapi.withings.net/v2/measure?action=getintradayactivity'
    api_url += '&userid=' + properties['oauth_user_id']
    api_url += '&startdate=' + str(start_date.timestamp)
    api_url += '&enddate=' + str(end_date.timestamp)

    oauth = OAuth1Session(settings.PDK_WITHINGS_API_KEY, \
                          client_secret=settings.PDK_WITHINGS_API_SECRET, \
                          resource_owner_key=properties['oauth_user_token'], \
                          resource_owner_secret=properties['oauth_user_secret'],
                          signature_type='query')

    response = oauth.get(url=api_url)

    results = response.json()

    if 'body' in results and 'series' in results['body']:
        if results['body']['series'] == []:
            return

        for timestamp, values in list(results['body']['series'].items()):
            found = False

            created_date = arrow.get(timestamp).datetime

            matches = DataPoint.objects.filter(source=user_id, generator_identifier='pdk-withings-device', created=created_date)

            for match in matches:
                match_props = match.fetch_properties()

                if match_props['datastream'] == 'intraday-activity':
                    found = True

            if found is False:
                now = arrow.utcnow()

                new_point = DataPoint(source=user_id, generator=GENERATOR_NAME, generator_identifier='pdk-withings-device')

                new_point.created = created_date
                new_point.recorded = now.datetime

                new_properties = {}
                new_properties['datastream'] = 'intraday-activity'

                new_properties['activity_start'] = int(timestamp)
                new_properties['activity_duration'] = values['duration']

                if 'calories' in values:
                    new_properties['calories'] = values['calories']

                if 'distance' in values:
                    new_properties['distance'] = values['distance']

                if 'steps' in values:
                    new_properties['steps'] = values['steps']

                if 'elevation' in values:
                    new_properties['elevation_climbed'] = values['elevation']

                if 'sleep_state' in values:
                    new_properties['sleep_state'] = values['sleep_state']

                new_properties['observed'] = now.timestamp * 1000
                new_properties['server_fetched'] = True

                new_properties['oauth_user_token'] = properties['oauth_user_token']
                new_properties['oauth_user_secret'] = properties['oauth_user_secret']
                new_properties['oauth_user_id'] = properties['oauth_user_id']

                pdk_metadata = {}
                pdk_metadata['source'] = user_id
                pdk_metadata['generator-id'] = 'pdk-withings-device'
                pdk_metadata['generator'] = GENERATOR_NAME
                pdk_metadata['timestamp'] = now.timestamp

                new_properties['passive-data-metadata'] = pdk_metadata

                new_point.properties = new_properties

                new_point.fetch_secondary_identifier()

                new_point.save()


def fetch_sleep_measures(user_id, properties, start_date, end_date): # pylint: disable=too-many-locals, too-many-statements, too-many-branches
    api_url = 'https://wbsapi.withings.net/v2/sleep?action=get'
    api_url += '&userid=' + properties['oauth_user_id']
    api_url += '&startdate=' + str(start_date.timestamp)
    api_url += '&enddate=' + str(end_date.timestamp)

    oauth = OAuth1Session(settings.PDK_WITHINGS_API_KEY, \
                          client_secret=settings.PDK_WITHINGS_API_SECRET, \
                          resource_owner_key=properties['oauth_user_token'], \
                          resource_owner_secret=properties['oauth_user_secret'],
                          signature_type='query')

    response = oauth.get(url=api_url)

    results = response.json()

    if 'body' in results and 'series' in results['body']:
        if results['body']['series'] == []:
            return

        for item in results['body']['series']:
            found = False

            created_date = arrow.get(item['enddate']).datetime

            matches = DataPoint.objects.filter(source=user_id, generator_identifier='pdk-withings-device', created=created_date)

            for match in matches:
                match_props = match.fetch_properties()

                if match_props['datastream'] == 'sleep-measures' and match_props['start_date'] == item['startdate']:
                    found = True

            if found is False:
                now = arrow.utcnow()

                new_point = DataPoint(source=user_id, generator=GENERATOR_NAME, generator_identifier='pdk-withings-device')

                new_point.created = created_date
                new_point.recorded = now.datetime

                new_properties = {}
                new_properties['datastream'] = 'sleep-measures'

                new_properties['start_date'] = item['startdate']
                new_properties['end_date'] = item['startdate']

                if item['state'] == 0:
                    new_properties['state'] = 'awake'
                elif item['state'] == 1:
                    new_properties['state'] = 'light-sleep'
                elif item['state'] == 2:
                    new_properties['state'] = 'deep-sleep'
                elif item['state'] == 3:
                    new_properties['state'] = 'rem-sleep'
                else:
                    new_properties['state'] = 'unknown'

                if results['body']['model'] == 32:
                    new_properties['measurement_device'] = 'aura'
                elif results['body']['model'] == 16:
                    new_properties['measurement_device'] = 'activity-tracker'
                else:
                    new_properties['measurement_device'] = 'unknown'

                new_properties['observed'] = now.timestamp * 1000
                new_properties['server_fetched'] = True

                new_properties['oauth_user_token'] = properties['oauth_user_token']
                new_properties['oauth_user_secret'] = properties['oauth_user_secret']
                new_properties['oauth_user_id'] = properties['oauth_user_id']

                pdk_metadata = {}
                pdk_metadata['source'] = user_id
                pdk_metadata['generator-id'] = 'pdk-withings-device'
                pdk_metadata['generator'] = GENERATOR_NAME
                pdk_metadata['timestamp'] = now.timestamp

                new_properties['passive-data-metadata'] = pdk_metadata

                new_point.properties = new_properties

                new_point.fetch_secondary_identifier()

                new_point.save()
#            else:
#                print('SKIPPING ' + str(created_date))
