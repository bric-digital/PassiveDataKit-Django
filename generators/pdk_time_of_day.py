# pylint: disable=line-too-long, no-member

import calendar
import csv
import datetime
import io
import os
import tempfile
import time

from zipfile import ZipFile

import arrow
import pytz

from django.conf import settings
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.text import slugify

from ..models import DataPoint, DataSourceReference, DataGeneratorDefinition

# def compile_visualization(identifier, points, folder): # pylint: disable=unused-argument
#    context = {}
#
#    values = []
#
#    end = timezone.now()
#    start = end - datetime.timedelta(days=7)
#
#    for point in points.order_by('-created'):
#        properties = point.fetch_properties()
#
#        if 'sensor_data' in properties:
#            value = {}
#
#            value['ts'] = properties['passive-data-metadata']['timestamp']
#            value['x_mean'] = numpy.mean(properties['sensor_data']['x'])
#            value['y_mean'] = numpy.mean(properties['sensor_data']['y'])
#            value['z_mean'] = numpy.mean(properties['sensor_data']['z'])
#
#            value['x_std'] = numpy.std(properties['sensor_data']['x'])
#            value['y_std'] = numpy.std(properties['sensor_data']['y'])
#            value['z_std'] = numpy.std(properties['sensor_data']['z'])
#
#            values.insert(0, value)
#
#    context['values'] = values
#
#    context['start'] = time.mktime(start.timetuple())
#    context['end'] = time.mktime(end.timetuple())
#
#    with open(folder + '/time-of-day.json', 'w') as outfile:
#        json.dump(context, outfile, indent=2)


def generator_name(identifier): # pylint: disable=unused-argument
    return 'Time of Day'

def visualization(source, generator):
    date = timezone.now().date()
    local_tz = pytz.timezone(settings.TIME_ZONE)

    values = []

    source_reference = DataSourceReference.reference_for_source(source.identifier)
    generator_definition = DataGeneratorDefinition.definition_for_identifier(generator)

    for counter in range(0, 14): # pylint: disable=unused-variable
        start = datetime.datetime(date.year, date.month, date.day, 0, 0, 0, 0, local_tz)
        end = start + datetime.timedelta(days=1)

        point = DataPoint.objects.filter(source_reference=source_reference, generator_definition=generator_definition, created__gt=start, created__lte=end).order_by('created').first()

        if point is not None:
            properties = point.fetch_properties()

            value = {}

            value['sunrise'] = properties['sunrise'] // 1000
            value['sunset'] = properties['sunset'] // 1000
            value['start'] = time.mktime(start.timetuple())
            value['end'] = time.mktime(end.timetuple())

            if value['sunset'] > value['end']:
                value['sunset'] -= (24 * 60 * 60)

            value['start_day'] = (value['sunset'] < value['sunrise'])

            value['date'] = point.created.astimezone(local_tz).isoformat()

            values.append(value)

        date = date - datetime.timedelta(days=1)

    context = {}
    context['source'] = source
    context['generator_identifier'] = generator

    context['values'] = values

    return render_to_string('generators/pdk_device_time_of_day_template.html', context)

def data_table(source, generator):
    context = {}
    context['source'] = source
    context['generator_identifier'] = generator

    end = timezone.now()
    start = end - datetime.timedelta(days=14)

    source_reference = DataSourceReference.reference_for_source(source.identifier)
    generator_definition = DataGeneratorDefinition.definition_for_identifier(generator)

    values = []

    for point in DataPoint.objects.filter(source_reference=source_reference, generator_definition=generator_definition, created__gt=start, created__lte=end).order_by('-created'):
        properties = point.fetch_properties()

        properties['is_day'] = (properties['observed'] > properties['sunrise']) and (properties['observed'] < properties['sunset'])
        properties['created'] = point.created
        properties['sunrise'] = properties['sunrise'] // 1000
        properties['sunset'] = properties['sunset'] // 1000

        properties['json'] = str(properties)

        values.append(properties)

    context['values'] = values

    return render_to_string('generators/pdk_device_time_of_day_table_template.html', context)

def compile_report(generator, sources, data_start=None, data_end=None, date_type='created'): # pylint: disable=too-many-locals, too-many-branches
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
                    'Sunrise',
                    'Sunset',
                    'Is Day',
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

                if data_start is not None:
                    points = points.filter(created__gte=data_start)

                if data_end is not None:
                    points = points.filter(created__lte=data_end)

                points = points.order_by('created')

                index = 0
                count = points.count()

                while index < count:
                    for point in points[index:(index + 500)]:
                        properties = point.fetch_properties()

                        row = []

                        row.append(point.source)
                        row.append(calendar.timegm(point.created.utctimetuple()))
                        row.append(point.created.isoformat())

                        row.append(calendar.timegm(point.recorded.utctimetuple()))
                        row.append(point.recorded.isoformat())

                        row.append(properties['sunrise'])
                        row.append(properties['sunset'])

                        if (properties['observed'] > properties['sunrise']) and (properties['observed'] < properties['sunset']):
                            row.append(1)
                        else:
                            row.append(0)

                        writer.writerow(row)

                    index += 500

            export_file.write(secondary_filename, slugify(generator) + '/' + slugify(source) + '.txt')

            os.remove(secondary_filename)

    return filename
