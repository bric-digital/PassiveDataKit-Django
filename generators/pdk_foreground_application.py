# pylint: disable=line-too-long, no-member

from __future__ import division

from builtins import str # pylint: disable=redefined-builtin

import calendar
import csv
import datetime
import io
import json
import os
import tempfile
import time

from zipfile import ZipFile

from past.utils import old_div

import arrow
import pytz
import requests

from bs4 import BeautifulSoup

from django.conf import settings
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.text import slugify

from ..models import DataPoint, DataSourceReference, DataGeneratorDefinition, DataServerMetadatum

DEFAULT_INTERVAL = 600
APP_GENRE_PREFIX = 'Foreground App Genre: '
SLEEP_DELAY = 5

def extract_secondary_identifier(properties):
    if 'application' in properties:
        return properties['application']

    return None

def generator_name(identifier): # pylint: disable=unused-argument
    return 'Foreground Application'

def visualization(source, generator):
    context = {}
    context['source'] = source
    context['generator_identifier'] = generator

    filename = settings.MEDIA_ROOT + '/pdk_visualizations/' + source.identifier + '/pdk-foreground-application/timestamp-counts.json'

    try:
        with io.open(filename, encoding='utf-8') as infile:
            hz_data = json.load(infile)

            context['hz_data'] = hz_data
    except IOError:
        context['hz_data'] = {}

    return render_to_string('generators/pdk_foreground_application_template.html', context)

def compile_visualization(identifier, points, folder, source=None): # pylint: disable=unused-argument
    now = timezone.now().astimezone(pytz.timezone(settings.TIME_ZONE))

    interval = DEFAULT_INTERVAL

    try:
        interval = settings.PDK_DATA_FREQUENCY_VISUALIZATION_INTERVAL
    except AttributeError:
        pass

    now = now.replace(second=0, microsecond=0)

    remainder = now.minute % int(old_div(interval, 60))

    now = now.replace(minute=(now.minute - remainder))

    start = now - datetime.timedelta(days=2)

    end = start + datetime.timedelta(seconds=interval)

    timestamp_counts = {}

    keys = []

    while start < now:
        timestamp = str(calendar.timegm(start.utctimetuple()))

        keys.append(timestamp)

        timestamp_counts[timestamp] = points.filter(created__gte=start, created__lt=end).count()

        start = end
        end = start + datetime.timedelta(seconds=interval)

    timestamp_counts['keys'] = keys

    with io.open(folder + '/timestamp-counts.json', 'w', encoding='utf-8') as outfile:
        json.dump(timestamp_counts, outfile, indent=2)

def data_table(source, generator): # pylint: disable=too-many-locals
    context = {}
    context['source'] = source
    context['generator_identifier'] = generator

    end = timezone.now()
    start = end - datetime.timedelta(days=1)

    values = []

    last_active = None
    last_application = None
    last_start = None
    cumulative_duration = 0

    for point in DataPoint.objects.filter(source=source.identifier, generator_identifier=generator, created__gt=start, created__lte=end).order_by('created'):
        properties = point.fetch_properties()

        active = None

        if 'screen_active' in properties:
            active = properties['screen_active']

        application = None

        if 'application' in properties:
            application = properties['application']

        update = False

        if active != last_active:
            update = True

        if application != last_application:
            update = True

        if update:
            if last_start is not None:
                value = {
                    'screen_active': last_active,
                    'application': last_application,
                    'start': last_start,
                    'duration': datetime.timedelta(seconds=(old_div(cumulative_duration, 1000)))
                }

                values.append(value)

            last_active = active
            last_application = application
            last_start = point.created
            cumulative_duration = 0
        else:
            cumulative_duration += properties['duration']

    context['values'] = values

    return render_to_string('pdk_foreground_application_table_template.html', context)

def compile_report(generator, sources, data_start=None, data_end=None, date_type='created'): # pylint: disable=too-many-locals, too-many-branches, too-many-statements
    now = arrow.get()
    filename = tempfile.gettempdir() + '/pdk_export_' + str(now.timestamp) + str(old_div(now.microsecond, 1e6)) + '.zip'

    with ZipFile(filename, 'w') as export_file:
        for source in sources:
            identifier = slugify(generator + '__' + source)

            secondary_filename = tempfile.gettempdir() + '/' + identifier + '.txt'

            with io.open(secondary_filename, 'w', encoding='utf-8') as outfile:
                writer = csv.writer(outfile, delimiter='\t')

                columns = [
                    'Source',
                    'Created Timestamp',
                    'Created Date',
                    'Recorded Timestamp',
                    'Recorded Date',
                    'Application',
                    'Duration',
                    'Screen Active',
                    'Play Store Category',
                ]

                writer.writerow(columns)

                source_reference = DataSourceReference.reference_for_source(source)
                generator_definition = DataGeneratorDefinition.definition_for_identifier(generator)

                points = DataPoint.objects.filter(source_reference=source_reference, generator_definition=generator_definition)

                if data_start is not None:
                    if date_type == 'recorded':
                        points = points.filter(recorded__gte=data_start)
                    else:
                        points = points.filter(created__gte=data_start)

                if data_end is not None:
                    if date_type == 'recorded':
                        points = points.filter(recorded__lte=data_end)
                    else:
                        points = points.filter(created__lte=data_end)

                point_count = points.count()

                points = points.order_by('created')

                points_index = 0

                while points_index < point_count:
                    for point in points[points_index:(points_index+1000)]:
                        properties = point.fetch_properties()

                        row = []

                        created = point.created.astimezone(pytz.timezone(settings.TIME_ZONE))
                        recorded = point.recorded.astimezone(pytz.timezone(settings.TIME_ZONE))

                        row.append(point.source)
                        row.append(calendar.timegm(point.created.utctimetuple()))
                        row.append(created.isoformat())

                        row.append(calendar.timegm(point.recorded.utctimetuple()))
                        row.append(recorded.isoformat())

                        properties = point.fetch_properties()

                        if 'application' in properties:
                            row.append(properties['application'])
                        else:
                            row.append('')

                        if 'duration' in properties:
                            row.append(str(properties['duration']))
                        else:
                            row.append('')

                        if 'screen_active' in properties:
                            row.append(str(properties['screen_active']))
                        else:
                            row.append('')

                        if 'application' in properties:
                            row.append(fetch_app_genre(properties['application']))
                        else:
                            row.append('')

                        writer.writerow(row)

                    points_index += 1000

            export_file.write(secondary_filename, slugify(generator) + '/' + slugify(source) + '.txt')

            os.remove(secondary_filename)

    return filename

def fetch_app_genre(package_name):
    key = APP_GENRE_PREFIX + str(package_name)

    cached_metadata = DataServerMetadatum.objects.filter(key=key).first()

    if cached_metadata is not None:
        return cached_metadata.value

    time.sleep(SLEEP_DELAY)

    req = requests.get('https://play.google.com/store/apps/details?id=' + package_name, timeout=120)

    if req.status_code == 200:
        soup = BeautifulSoup(req.text, "lxml")

        matches = soup.find_all('a', itemprop='genre')

        for match in matches: # pylint: disable=not-an-iterable
            cached_metadata = DataServerMetadatum(key=key, value=match.string)
            cached_metadata.save()

            return cached_metadata.value

    cached_metadata = DataServerMetadatum(key=key, value='Unknown')
    cached_metadata.save()

    return cached_metadata.value

def update_data_type_definition(definition):
    if 'application' in definition:
        definition['application']['pdk_variable_name'] = 'Application identifier'
        definition['application']['pdk_variable_description'] = 'Identifier of an application observed running in the foreground. Note that in cases where the device has been configured to obscure certain applications, this identifier may be a device-specific hash value for the obscured application\'s identifier.'
        definition['application']['pdk_codebook_group'] = 'Passive Data Kit: Application Information'
        definition['application']['pdk_codebook_order'] = 0
        definition['application']['examples'] = sorted(definition['application']['observed'], key=lambda x: len(x))[:16] # pylint: disable=unnecessary-lambda

    if 'category' in definition:
        definition['category']['pdk_variable_name'] = 'Application category'
        definition['category']['pdk_variable_description'] = 'Category of an application observed running in the foreground. Note that in cases where the device has been configured to obscure certain applications, this may be a device-specific hash value for the obscured application\'s original category.'
        definition['category']['pdk_codebook_group'] = 'Passive Data Kit: Application Information'
        definition['category']['pdk_codebook_order'] = 1
        definition['category']['examples'] = [item for item in definition['category']['observed'] if len(item) < 48]

    if 'is_home' in definition:
        definition['is_home']['pdk_variable_name'] = 'Is home screen or launcher app'
        definition['is_home']['pdk_variable_description'] = 'Boolean value indicating whether the observed application is a home screen or launcher application.'
        definition['is_home']['pdk_codebook_group'] = 'Passive Data Kit: Application Information'
        definition['is_home']['pdk_codebook_order'] = 2
        definition['is_home']['types'] = ['boolean']

    if 'duration' in definition:
        definition['duration']['pdk_variable_name'] = 'Sample duration'
        definition['duration']['pdk_variable_description'] = 'Sampling duration used to generate this observation (in milliseconds)'
        definition['duration']['pdk_codebook_group'] = 'Passive Data Kit: Application Information'
        definition['duration']['pdk_codebook_order'] = 3

    if 'display_state' in definition:
        definition['display_state']['pdk_variable_name'] = 'Display mode'
        definition['display_state']['pdk_variable_description'] = 'State of the display when the application observation was made.'
        definition['display_state']['pdk_codebook_group'] = 'Passive Data Kit: Application Information (Device State)'
        definition['display_state']['pdk_codebook_order'] = 0

    if 'screen_active' in definition:
        definition['screen_active']['pdk_variable_name'] = 'Screen power state'
        definition['screen_active']['pdk_variable_description'] = 'Indicates whether the device\'s screen was powered on when the application observation was recorded.'
        definition['screen_active']['pdk_codebook_group'] = 'Data Kit: Application Information (Device State)'
        definition['screen_active']['pdk_codebook_order'] = 1

    del definition['observed']

    definition['pdk_description'] = 'Records the foreground applications running on the device, typically using a 5000 ms sampling interval.'
