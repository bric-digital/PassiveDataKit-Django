# pylint: disable=line-too-long, no-member

import csv
import calendar
import datetime
import io
import json
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

def generator_name(identifier): # pylint: disable=unused-argument
    return 'Web Visit'

def compile_report(generator, sources, data_start=None, data_end=None, date_type='created'): # pylint: disable=too-many-locals
    now = arrow.get()
    filename = tempfile.gettempdir() + os.path.sep + 'pdk_export_' + str(now.timestamp) + str(now.microsecond // 1e6) + '.zip'

    with ZipFile(filename, 'w') as export_file:
        for source in sources:
            source_reference = DataSourceReference.reference_for_source(source)
            generator_definition = DataGeneratorDefinition.definition_for_identifier(generator)

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
                    'Visit ID',
                    'URL',
                    'Protocol',
                    'Host',
                    'Title',
                    'Transition Type',
                    'Referrer Visit ID',
                ]

                writer.writerow(columns)

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

                    row.append(properties['visitId'])
                    row.append(properties['url'].encode('utf-8'))
                    row.append(properties['protocol'])
                    row.append(properties['host'].encode('utf-8'))
                    row.append(properties['title'].encode('utf-8'))
                    row.append(properties['transition'])
                    row.append(properties['referringVisitId'])

                    writer.writerow(row)

            export_file.write(secondary_filename, slugify(generator) + '/' + slugify(source) + '.txt')

            os.remove(secondary_filename)

    return filename

def data_table(source, generator):
    context = {}
    context['source'] = source
    context['generator_identifier'] = generator

    source_reference = DataSourceReference.reference_for_source(source.identifier)
    generator_definition = DataGeneratorDefinition.definition_for_identifier(generator)

    context['values'] = DataPoint.objects.filter(source_reference=source_reference, generator_definition=generator_definition).order_by('-created')

    return render_to_string('pdk_web_visit_table_template.html', context)


def visualization(source, generator): # pylint: disable=unused-argument
    filename = settings.MEDIA_ROOT + os.path.sep + 'pdk_visualizations' + os.path.sep + source.identifier + os.path.sep + 'pdk-web-visit' + os.path.sep + 'timestamp-counts.json'

    try:
        with io.open(filename, encoding='utf-8') as infile:
            data = json.load(infile)

            context = {}

            context['data'] = data

            return render_to_string('pdk_web_visit_viz_template.html', context)
    except IOError:
        pass

    return None

def compile_visualization(identifier, points, folder): # pylint: disable=unused-argument, too-many-locals
    now = timezone.now()

    points = list(points.order_by('-created'))
    points.reverse()

    first = points[0]

    start = first.created.replace(minute=0, second=0, microsecond=0)

    end = start + datetime.timedelta(hours=1)
    point_index = 0
    point_count = len(points)

    point = None

    if point_count > 0:
        point = points[point_index]

    timestamp_counts = {}

    keys = []

    while start < now:
        timestamp = str(time.mktime(start.timetuple()))

        keys.append(timestamp)

        timestamp_counts[timestamp] = 0

        while point is not None and point.created < end and point_index < (point_count - 1):
            timestamp_counts[timestamp] += 1

            point_index += 1

            point = points[point_index]

        start = end
        end = start + datetime.timedelta(hours=1)

    timestamp_counts['keys'] = keys

    with io.open(folder + os.path.sep + 'timestamp-counts.json', 'w', encoding='utf-8') as outfile:
        json.dump(timestamp_counts, outfile, indent=2)
