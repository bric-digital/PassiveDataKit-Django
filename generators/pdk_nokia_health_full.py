# pylint: disable=line-too-long, no-member

import csv
import io
import tempfile
import time

from zipfile import ZipFile

import arrow
import requests

from django.utils import timezone

from ..models import DataPoint

REFRESH_ENDPOINT = 'https://account.health.nokia.com/oauth2/token'

def compile_report(generator, sources): # pylint: disable=too-many-locals
    now = arrow.get()
    filename = tempfile.gettempdir() + '/pdk_export_' + str(now.timestamp) + str(now.microsecond // 1e6) + '.zip'

    if generator == 'pdk-nokia-health-full':
        with ZipFile(filename, 'w') as export_file:
            for source in sources:
                last_point = DataPoint.objects.filter(source=source, generator_identifier='pdk-nokia-health', secondary_identifier='server-credentials').order_by('-created').first()

                if last_point is not None:
                    properties = last_point.fetch_properties()

                    if 'access_token' in properties and 'refresh_token' in properties and 'client_id' in properties and 'client_secret' in properties:
                        refresh_params = {
                            'grant_type': 'refresh_token',
                            'client_id': properties['client_id'],
                            'client_secret': properties['client_secret'],
                            'refresh_token': properties['refresh_token'],
                        }

                        api_request = requests.post(REFRESH_ENDPOINT, data=refresh_params, timeout=120)

                        access_payload = api_request.json()

                        access_token = access_payload['access_token']

                        first_point = DataPoint.objects.filter(source=source, generator_identifier='pdk-nokia-health').order_by('created').first()

                        # Added for legacy compatibility with legacy APIs

                        first_withings = DataPoint.objects.filter(source=source, generator_identifier='pdk-withings-device').order_by('created').first()

                        if first_withings is not None and first_withings.created < first_point.created:
                            first_point = first_withings

                        intraday_file = fetch_intraday(source, arrow.get(first_point.created), access_token)

                        export_file.write(intraday_file, source + '/' + intraday_file.split('/')[-1])

                        sleep_file = fetch_sleep_measures(source, arrow.get(first_point.created), access_token)

                        export_file.write(sleep_file, source + '/' + sleep_file.split('/')[-1])

                        new_point = DataPoint(source=last_point.source)
                        new_point.generator = last_point.generator
                        new_point.generator_identifier = last_point.generator_identifier
                        new_point.generator_identifier = last_point.generator_identifier
                        new_point.generator_identifier = last_point.generator_identifier
                        new_point.secondary_identifier = last_point.secondary_identifier
                        new_point.user_agent = 'Passive Data Kit Server'
                        new_point.created = timezone.now()
                        new_point.recorded = new_point.created

                        properties['access_token'] = access_payload['access_token']
                        properties['refresh_token'] = access_payload['refresh_token']

                        new_point.properties = properties

                        new_point.save()

        return filename

    return None

def fetch_intraday(source, start, access_token): # pylint: disable=too-many-locals, too-many-statements, too-many-branches
    final_end = arrow.now()

    intraday_filename = tempfile.gettempdir() + '/pdk-nokia-health-full-intraday.txt'

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
            api_url += '&access_token=' + access_token
            api_url += '&startdate=' + str(start.timestamp)
            api_url += '&enddate=' + str(end.timestamp)

            response = requests.get(url=api_url, timeout=120)

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

def fetch_sleep_measures(source, start, access_token): # pylint: disable=too-many-locals, too-many-statements, too-many-branches
    final_end = arrow.now()

    sleep_filename = tempfile.gettempdir() + '/pdk-nokia-health-full-sleep.txt'

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
            api_url += '&access_token=' + access_token
            api_url += '&startdate=' + str(start.timestamp)
            api_url += '&enddate=' + str(end.timestamp)

            response = requests.get(url=api_url, timeout=120)

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
