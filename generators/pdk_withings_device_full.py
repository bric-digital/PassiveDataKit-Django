# pylint: disable=line-too-long, no-member

import csv
import io
import os
import tempfile
import time

from zipfile import ZipFile

import arrow

from requests_oauthlib import OAuth1Session

from django.conf import settings

from ..models import DataPoint

def compile_report(generator, sources): # pylint: disable=too-many-locals
    now = arrow.get()
    filename = tempfile.gettempdir() + os.path.sep + 'pdk_export_' + str(now.timestamp) + str(now.microsecond // 1e6) + '.zip'

    if generator == 'pdk-withings-device-full':
        with ZipFile(filename, 'w') as export_file:
            for source in sources:
                last_point = DataPoint.objects.filter(source=source, generator_identifier='pdk-withings-device').order_by('-created').first()

                if last_point is not None:
                    properties = last_point.fetch_properties()

                    if 'oauth_user_token' in properties and 'oauth_user_secret' in properties and 'oauth_user_id' in properties:
                        first_point = DataPoint.objects.filter(source=source, generator_identifier='pdk-withings-device').order_by('created').first()

                        intraday_file = fetch_intraday(source, properties, arrow.get(first_point.created))

                        export_file.write(intraday_file, source + '/' + intraday_file.split(os.path.sep)[-1])

                        sleep_file = fetch_sleep_measures(source, properties, arrow.get(first_point.created))

                        export_file.write(sleep_file, source + '/' + sleep_file.split(os.path.sep)[-1])

        return filename

    return None

def fetch_intraday(source, properties, start): # pylint: disable=too-many-locals, too-many-statements, too-many-branches
    final_end = arrow.now()

    intraday_filename = tempfile.gettempdir() + os.path.sep + 'pdk-withings-device-full-intraday.txt'

    with io.open(intraday_filename, 'w', encoding='utf-8') as outfile:
        writer = csv.writer(outfile, delimiter='\t')

        columns = [
            'Source',
            'Created Timestamp',
            'Created Date',
            'Duration',
            'Calories',
            'Distance',
            'Steps',
            'Elevation',
            'Strokes',
            'Pool Laps',
        ]

        writer.writerow(columns)

        while start < final_end:
            end = start.shift(hours=+12)

            api_url = 'https://api.health.nokia.com/v2/measure?action=getintradayactivity'
            api_url += '&userid=' + properties['oauth_user_id']
            api_url += '&startdate=' + str(start.timestamp)
            api_url += '&enddate=' + str(end.timestamp)

            oauth = OAuth1Session(settings.PDK_WITHINGS_API_KEY, \
                                  client_secret=settings.PDK_WITHINGS_API_SECRET, \
                                  resource_owner_key=properties['oauth_user_token'], \
                                  resource_owner_secret=properties['oauth_user_secret'],
                                  signature_type='query')

            response = oauth.get(url=api_url)

            results = response.json()

            if 'body' in results and 'series' in results['body']:
                if results['body']['series'] == []:
                    return None

                for timestamp, values in list(results['body']['series'].items()):
                    row = []

                    row.append(source)
                    row.append(timestamp)

                    created_date = arrow.get(timestamp).datetime

                    row.append(created_date.isoformat())

                    row.append(values['duration'])

                    if 'calories' in values:
                        row.append(values['calories'])
                    else:
                        row.append(None)

                    if 'distance' in values:
                        row.append(values['distance'])
                    else:
                        row.append(None)

                    if 'steps' in values:
                        row.append(values['steps'])
                    else:
                        row.append(None)

                    if 'elevation' in values:
                        row.append(values['elevation'])
                    else:
                        row.append(None)

                    if 'strokes' in values:
                        row.append(values['strokes'])
                    else:
                        row.append(None)

                    if 'pool_lap' in values:
                        row.append(values['pool_lap'])
                    else:
                        row.append(None)

                    writer.writerow(row)

            time.sleep(1)

            start = end

    return intraday_filename

def fetch_sleep_measures(source, properties, start): # pylint: disable=too-many-locals, too-many-statements, too-many-branches
    final_end = arrow.now()

    sleep_filename = tempfile.gettempdir() + os.path.sep + 'pdk-withings-device-full-sleep.txt'

    with io.open(sleep_filename, 'w', encoding='utf-8') as outfile:
        writer = csv.writer(outfile, delimiter='\t')

        columns = [
            'Source',
            'Duration Start',
            'Duration End',
            'Sleep State',
            'Device Model',
        ]

        writer.writerow(columns)

        while start < final_end:
            end = start.shift(hours=+12)

            api_url = 'https://api.health.nokia.com/v2/sleep?action=get'
            api_url += '&userid=' + properties['oauth_user_id']
            api_url += '&startdate=' + str(start.timestamp)
            api_url += '&enddate=' + str(end.timestamp)

            oauth = OAuth1Session(settings.PDK_WITHINGS_API_KEY, \
                                  client_secret=settings.PDK_WITHINGS_API_SECRET, \
                                  resource_owner_key=properties['oauth_user_token'], \
                                  resource_owner_secret=properties['oauth_user_secret'],
                                  signature_type='query')

            response = oauth.get(url=api_url)

            results = response.json()

            if 'body' in results and 'series' in results['body']:
                for item in results['body']['series']:
                    row = []

                    row.append(source)
                    row.append(item['startdate'])
                    row.append(item['enddate'])

                    if item['state'] == 0:
                        row.append('awake')
                    elif item['state'] == 1:
                        row.append('light-sleep')
                    elif item['state'] == 2:
                        row.append('deep-sleep')
                    elif item['state'] == 3:
                        row.append('rem-sleep')
                    else:
                        row.append('unknown (' + str(item['state']) + ')')

                    if results['body']['model'] == 32:
                        row.append('aura')
                    elif results['body']['model'] == 16:
                        row.append('activity-tracker')
                    else:
                        row.append('unknown (' + str(results['body']['model']) + ')')

                    writer.writerow(row)

            time.sleep(1)

            start = end

    return sleep_filename
