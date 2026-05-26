# pylint: disable=line-too-long, no-member

import calendar
import csv
import datetime
import io
import math
import os
import tempfile
import time

from zipfile import ZipFile

import arrow

from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.text import slugify

from ..models import DataPoint, DataSourceReference, DataGeneratorDefinition

WINDOW_SIZE = 300

SPLIT_SIZE = 25000

def fetch_values(source, generator, start, end):
    values = []

    index = start
    current_value = None

    source_reference = DataSourceReference.reference_for_source(source.identifier)
    generator_definition = DataGeneratorDefinition.definition_for_identifier(generator)

    for point in DataPoint.objects.filter(source_reference=source_reference, generator_definition=generator_definition, created__gt=start, created__lte=end).order_by('created'):
        if (point.created - index).total_seconds() > WINDOW_SIZE:
            if current_value is not None and current_value['min_value'] != -1: # pylint: disable=unsubscriptable-object
                values.append(current_value)

            current_value = None
            index = index + datetime.timedelta(seconds=WINDOW_SIZE)

        if current_value is None:
            current_value = {
                'min_value': -1,
                'max_value': -1,
                'timestamp': time.mktime(index.timetuple()),
                'created': index,
                'duration': WINDOW_SIZE
            }

        properties = point.fetch_properties()

        for level in properties['sensor_data']['light_level']:
            if current_value['min_value'] == -1 or level < current_value['min_value']:
                current_value['min_value'] = level

            if current_value['max_value'] == -1 or level > current_value['max_value']:
                current_value['max_value'] = level

#        duration = properties['sensor_data']['observed'][-1] - properties['sensor_data']['observed'][0]
#        timestamp = properties['sensor_data']['observed'][0] + (duration / 2)
#
#        value['min_value'] = min_value
#        value['max_value'] = max_value
#        value['duration'] = duration / (1000 * 1000 * 1000)
#        value['timestamp'] = timestamp / (1000 * 1000 * 1000)
#        value['created'] = point.created
#
#        values.append(value)

    return values


def generator_name(identifier): # pylint: disable=unused-argument
    return 'Light Sensor'

def visualization(source, generator):
    context = {}
    context['source'] = source
    context['generator_identifier'] = generator

    end = timezone.now()
    start = end - datetime.timedelta(days=1)

    context['values'] = fetch_values(source, generator, start, end)

    context['start'] = time.mktime(start.timetuple())
    context['end'] = time.mktime(end.timetuple())

    return render_to_string('pdk_sensor_light_template.html', context)

def data_table(source, generator):
    context = {}
    context['source'] = source
    context['generator_identifier'] = generator

    end = timezone.now()
    start = end - datetime.timedelta(days=1)

    context['values'] = fetch_values(source, generator, start, end)

    return render_to_string('pdk_sensor_light_table_template.html', context)

def compile_report(generator, sources, data_start=None, data_end=None, date_type='created'): # pylint: disable=too-many-locals, too-many-branches, too-many-statements
    now = arrow.get()
    filename = tempfile.gettempdir() + os.path.sep + 'pdk_export_' + str(now.timestamp) + str(now.microsecond // 1e6) + '.zip'

    with ZipFile(filename, 'w', allowZip64=True) as export_file:
        for source in sources:
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

            point_ids = points.values_list('pk', flat=True).order_by('created')

            points_count = len(point_ids)

            splits = int(math.ceil(points_count / SPLIT_SIZE))

            for split_index in range(0, splits):
                identifier = slugify(generator + '__' + source)

                if splits > 1:
                    identifier += '__' + str(split_index) + '_of_' + str(splits)

                secondary_filename = tempfile.gettempdir() + os.path.sep + identifier + '.txt'

                with io.open(secondary_filename, 'w', encoding='utf-8') as outfile:
                    writer = csv.writer(outfile, delimiter='\t')

                    columns = [
                        'Source',
                        'Created Timestamp',
                        'Created Date',
                        'Recorded Timestamp',
                        'Recorded Date',
                        'Raw Timestamp',
                        'Normalized Timestamp',
                        'Light Level',
                        'Accuracy'
                    ]

                    writer.writerow(columns)

                    index = split_index * SPLIT_SIZE

                    while index < (split_index + 1) * SPLIT_SIZE and index < points_count:
                        for point_id in point_ids[index:(index + 1000)]:
                            point = DataPoint.objects.get(pk=point_id)

                            properties = point.fetch_properties()

                            if 'observed' in properties['sensor_data']:
                                for i in range(0, len(properties['sensor_data']['observed'])):
                                    row = []

                                    row.append(point.source)
                                    row.append(calendar.timegm(point.created.utctimetuple()))
                                    row.append(point.created.isoformat())

                                    row.append(calendar.timegm(point.recorded.utctimetuple()))
                                    row.append(point.recorded.isoformat())

                                    try:
                                        row.append(properties['sensor_data']['raw_timestamp'][i])
                                    except IndexError:
                                        row.append('')

                                    try:
                                        row.append(properties['sensor_data']['observed'][i])
                                    except IndexError:
                                        row.append('')

                                    try:
                                        row.append(properties['sensor_data']['light_level'][i])
                                    except IndexError:
                                        row.append('')

                                    try:
                                        row.append(properties['sensor_data']['accuracy'][i])
                                    except IndexError:
                                        row.append('')

                                    writer.writerow(row)

                        index += 1000

                source_name = source

                if splits > 1:
                    source_name += '__' + str(split_index)

                export_file.write(secondary_filename, slugify(generator) + '/' + slugify(source_name) + '.txt')

                os.remove(secondary_filename)

    return filename
