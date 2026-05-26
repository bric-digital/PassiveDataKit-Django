# pylint: disable=line-too-long, no-member

import calendar
import csv
import datetime
import io
import json
import math
import os
import tempfile
import time

from zipfile import ZipFile

import arrow
import numpy

from django.conf import settings
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.text import slugify

from ..models import DataPoint, DataSourceReference, DataGeneratorDefinition


SPLIT_SIZE = 10000

def generator_name(identifier): # pylint: disable=unused-argument
    return 'Accelerometer Sensor'

def compile_frequency_visualization(identifier, points, folder): # pylint: disable=unused-argument,too-many-locals
    now = timezone.now()

    now = now.replace(second=0, microsecond=0)

    remainder = now.minute % 10

    now = now.replace(minute=(now.minute - remainder))

    start = now - datetime.timedelta(days=2)

    points = list(points.filter(created__lte=now, created__gte=start).order_by('created'))

    end = start + datetime.timedelta(seconds=600)
    point_index = 0
    point_count = len(points)

    point = None

    if point_count > 0:
        point = points[point_index]

    timestamp_counts = {}

    keys = []

    while start < now: # pylint: disable=too-many-nested-blocks
        timestamp = str(calendar.timegm(start.utctimetuple()))

        keys.append(timestamp)

        timestamp_counts[timestamp] = 0

        while point is not None and point.created < end and point_index < (point_count - 1):
            properties = point.fetch_properties()

            if 'sensor_data' in properties:
                try:
                    for timestamp in properties['sensor_data']['observed']:
                        timestamp = timestamp // (1000 * 1000 * 1000)

                        for key in keys:
                            key_end = float(key) + 600

                            if float(key) <= timestamp <= key_end:
                                timestamp_counts[key] += 1
                except KeyError:
                    pass
                except TypeError:
                    pass

            point_index += 1

            point = points[point_index]

        start = end
        end = start + datetime.timedelta(seconds=600)

    timestamp_counts['keys'] = keys

    with io.open(folder + os.path.sep + 'timestamp-counts.json', 'wb') as outfile:
        json.dump(timestamp_counts, outfile, indent=2)

def compile_visualization(identifier, points, folder, source=None): # pylint: disable=unused-argument
    values = []

    now = timezone.now()

    now = now.replace(second=0, microsecond=0)

    remainder = now.minute % 10

    now = now.replace(minute=(now.minute - remainder))

    start = now - datetime.timedelta(days=2)

    points = points.filter(created__gte=start)

    point_ids = points.values_list('pk', flat=True).order_by('created')

    for point_id in point_ids:
        point = DataPoint.objects.get(pk=point_id)

        properties = point.fetch_properties()

        if 'sensor_data' in properties:
            try:
                value = {}

                value['ts'] = properties['passive-data-metadata']['timestamp']
                value['x_mean'] = numpy.mean(properties['sensor_data']['x'])
                value['y_mean'] = numpy.mean(properties['sensor_data']['y'])
                value['z_mean'] = numpy.mean(properties['sensor_data']['z'])

                value['x_std'] = numpy.std(properties['sensor_data']['x'])
                value['y_std'] = numpy.std(properties['sensor_data']['y'])
                value['z_std'] = numpy.std(properties['sensor_data']['z'])

                values.insert(0, value)
            except KeyError:
                pass
            except TypeError:
                pass

    context = {}

    context['values'] = values

    context['start'] = time.mktime(start.timetuple())
    context['end'] = time.mktime(now.timetuple())

    with io.open(folder + os.path.sep + 'accelerometer.json', 'w', encoding='utf-8') as outfile:
        json.dump(context, outfile, indent=2)


def visualization(source, generator): # pylint: disable=unused-argument
    context = {}

    filename = settings.MEDIA_ROOT + 'pdk_visualizations' + os.path.sep + source.identifier + os.path.sep + 'pdk-sensor-accelerometer' + os.path.sep + 'accelerometer.json'

    with io.open(filename, encoding='utf-8') as infile:
        data = json.load(infile)
        context['viz_data'] = data

    filename = settings.MEDIA_ROOT + os.path.sep + 'pdk_visualizations' + os.path.sep + source.identifier + os.path.sep + 'pdk-sensor-accelerometer' + os.path.sep + 'timestamp-counts.json'

    try:
        with io.open(filename, encoding='utf-8') as infile:
            hz_data = json.load(infile)

            context['hz_data'] = hz_data
    except IOError:
        context['hz_data'] = {}

    return render_to_string('generators/pdk_sensor_accelerometer_template.html', context)


def data_table(source, generator): # pylint: disable=unused-argument
    filename = settings.MEDIA_ROOT + 'pdk_visualizations' + os.path.sep + source.identifier + os.path.sep + 'pdk-sensor-accelerometer' + os.path.sep + 'accelerometer.json'

    with io.open(filename, encoding='utf-8') as infile:
        data = json.load(infile)

        return render_to_string('generators/pdk_sensor_accelerometer_table_template.html', data)

    return None

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

            points = points.order_by('source', 'created')

            points_count = float(points.count())

            splits = int(math.ceil(points_count // SPLIT_SIZE))

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
                        'X',
                        'Y',
                        'Z',
                        'Accuracy'
                    ]

                    writer.writerow(columns)

                    index = split_index * SPLIT_SIZE

                    while index < (split_index + 1) * SPLIT_SIZE and index < points_count:
                        for point in points[index:(index + 1000)]:
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
                                        row.append(properties['sensor_data']['x'][i])
                                    except IndexError:
                                        row.append('')

                                    try:
                                        row.append(properties['sensor_data']['y'][i])
                                    except IndexError:
                                        row.append('')

                                    try:
                                        row.append(properties['sensor_data']['z'][i])
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
