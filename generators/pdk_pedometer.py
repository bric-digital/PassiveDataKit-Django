# pylint: disable=line-too-long, no-member

import csv
import calendar
import datetime
import io
import json
import os
import tempfile

from zipfile import ZipFile

import arrow
import pytz

from django.conf import settings
from django.template.loader import render_to_string
from django.utils.text import slugify

from ..models import DataPoint, DataSourceReference, DataGeneratorDefinition

def extract_secondary_identifier(properties): # pylint: disable=unused-argument
    return None

def generator_name(identifier): # pylint: disable=unused-argument
    return 'Device Pedometer'

def visualization(source, generator): # pylint: disable=unused-argument
    context = {}

    filename = settings.MEDIA_ROOT + os.path.sep + 'pdk_visualizations' + os.path.sep + source.identifier + os.path.sep + 'pdk-pedometer' + os.path.sep + 'pedometer.json'

    with io.open(filename, encoding='utf-8') as infile:
        context['data'] = json.load(infile)

    filename = settings.MEDIA_ROOT + os.path.sep + 'pdk_visualizations' + os.path.sep + source.identifier + os.path.sep + 'pdk-pedometer' + os.path.sep + 'timestamp-counts.json'

    try:
        with io.open(filename, encoding='utf-8') as infile:
            hz_data = json.load(infile)

            context['hz_data'] = hz_data
    except IOError:
        context['hz_data'] = {}

    return render_to_string('generators/pdk_device_pedometer_template.html', context)

def compile_visualization(identifier, points, folder, source=None): # pylint: disable=unused-argument
    context = {}

    values = []

    latest = points.order_by('-created').first()

    now = latest.created.replace(second=0, microsecond=0)

    remainder = 10 - (now.minute % 10)

    now = now.replace(minute=((now.minute + remainder) % 60))

    start = now - datetime.timedelta(days=7)

    for point in points.filter(created__gte=start).order_by('created'):
        properties = point.fetch_properties()

        value = {}

        value['ts'] = properties['passive-data-metadata']['timestamp']

        if 'daily-summary-steps' in properties:
            value['steps'] = properties['daily-summary-steps']

        if 'daily-summary-floors' in properties:
            value['floors'] = properties['daily-summary-floors']

        if 'daily-summary-floors' in properties:
            value['floors'] = properties['daily-summary-floors']

        if 'daily-summary-floors-ascended' in properties:
            value['floors_ascended'] = properties['daily-summary-floors-ascended']

        if 'daily-summary-floors-descended' in properties:
            value['floors_descended'] = properties['daily-summary-floors-descended']

        values.append(value)

    context['values'] = values

    context['start'] = calendar.timegm(start.timetuple())
    context['end'] = calendar.timegm(now.timetuple())

    with io.open(folder + os.path.sep + 'pedometer.json', 'wb') as outfile:
        json.dump(context, outfile, indent=2)

    compile_frequency_visualization(identifier, points, folder)

def compile_frequency_visualization(identifier, points, folder): # pylint: disable=unused-argument
    latest = points.order_by('-created').first()

    now = latest.created.replace(second=0, microsecond=0)

    remainder = 10 - (now.minute % 10)

    now = now.replace(minute=((now.minute + remainder) % 60))

    start = now - datetime.timedelta(days=7)

    points = points.filter(created__lte=now, created__gte=start).order_by('created')

    end = start + datetime.timedelta(seconds=600)
    point_index = 0
    point_count = points.count()

    point = None

    if point_count > 0:
        point = points[point_index]

    timestamp_counts = {}

    keys = []

    while start < now:
        timestamp = str(calendar.timegm(start.timetuple()))

        keys.append(timestamp)

        timestamp_counts[timestamp] = 0

        while point is not None and point.created < end and point_index < (point_count - 1):
            timestamp_counts[timestamp] += 1

            point_index += 1

            point = points[point_index]

        start = end
        end = start + datetime.timedelta(seconds=600)

    timestamp_counts['keys'] = keys

    with io.open(folder + os.path.sep + 'timestamp-counts.json', 'wb') as outfile:
        json.dump(timestamp_counts, outfile, indent=2)

def data_table(source, generator):
    context = {}

    context['source'] = source
    context['generator_identifier'] = generator

    point_count = 1000

    try:
        point_count = settings.PDK_LOGGED_VALUES_COUNT
    except AttributeError:
        pass

    context['values'] = DataPoint.objects.filter(source_reference=DataSourceReference.reference_for_source(source.identifier), generator_definition=DataGeneratorDefinition.definition_for_identifier(generator)).order_by('-created')[:point_count]

    return render_to_string('generators/pdk_device_pedometer_table_template.html', context)

def compile_report(generator, sources, data_start=None, data_end=None, date_type='created'): # pylint: disable=too-many-locals, too-many-branches, too-many-statements
    now = arrow.get()
    filename = tempfile.gettempdir() + os.path.sep + 'pdk_export_' + str(now.timestamp) + str(now.microsecond // 1e6) + '.zip'

    with ZipFile(filename, 'w') as export_file:
        for source in sources:
            identifier = slugify(generator + '__' + source)

            secondary_filename = tempfile.gettempdir() + os.path.sep + identifier + '.txt'

            with io.open(secondary_filename, 'w', encoding='utf-8') as outfile:
                writer = csv.writer(outfile, delimiter='\t')

                columns = [
                    'Source',
                    'Created Timestamp',
                    'Created Date',
                    'Recorded Timestamp',
                    'Recorded Date',
                    'Daily Steps',
                    'Total Steps',
                    'Daily Average Pace',
                    'Total Average Pace',
                    'Daily Distance',
                    'Total Distance',
                    'Daily Floors Ascended',
                    'Total Floors Ascended',
                    'Daily Floors Descended',
                    'Total Floors Descended',
                    'Background Recording',
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

                points = points.order_by('source', 'created')

                for point in points:
                    properties = point.fetch_properties()

                    row = []

                    created = point.created.astimezone(pytz.timezone(settings.TIME_ZONE))
                    recorded = point.recorded.astimezone(pytz.timezone(settings.TIME_ZONE))

                    row.append(point.source)
                    row.append(calendar.timegm(point.created.utctimetuple()))
                    row.append(created.isoformat())

                    row.append(calendar.timegm(point.recorded.utctimetuple()))
                    row.append(recorded.isoformat())

                    if 'daily-summary-steps' in properties:
                        row.append(properties['daily-summary-steps'])
                    else:
                        row.append('')

                    if 'step-count' in properties:
                        row.append(properties['step-count'])
                    else:
                        row.append('')

                    if 'daily-average-pace' in properties:
                        row.append(properties['daily-average-pace'])
                    else:
                        row.append('')

                    if 'average-pace' in properties:
                        row.append(properties['average-pace'])
                    else:
                        row.append('')

                    if 'daily-summary-distance' in properties:
                        row.append(properties['daily-summary-distance'])
                    else:
                        row.append('')

                    if 'distance' in properties:
                        row.append(properties['distance'])
                    else:
                        row.append('')

                    if 'daily-summary-floors-ascended' in properties:
                        row.append(properties['daily-summary-floors-ascended'])
                    else:
                        row.append('')

                    if 'floors-ascended' in properties:
                        row.append(properties['floors-ascended'])
                    else:
                        row.append('')

                    if 'daily-summary-floors-descended' in properties:
                        row.append(properties['daily-summary-floors-descended'])
                    else:
                        row.append('')

                    if 'floors-descended' in properties:
                        row.append(properties['floors-descended'])
                    else:
                        row.append('')

                    if 'from-background' in properties:
                        row.append(properties['from-background'])
                    else:
                        row.append('')

                    writer.writerow(row)

            export_file.write(secondary_filename, slugify(generator) + '/' + slugify(source) + '.txt')

            os.remove(secondary_filename)

    return filename
