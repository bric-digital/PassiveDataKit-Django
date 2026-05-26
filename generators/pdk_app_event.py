# pylint: disable=line-too-long, no-member

import calendar
import csv
import datetime
import io
import json
import os
import tempfile
import time

import pytz

from django.conf import settings
from django.template.loader import render_to_string
from django.utils import timezone

from ..models import DataPoint, DataSourceReference, DataGeneratorDefinition

def generator_name(identifier): # pylint: disable=unused-argument
    return 'App Events'

def extract_secondary_identifier(properties):
    if 'event_name' in properties:
        return properties['event_name']

    return None

def compile_report(generator, sources, data_start=None, data_end=None, date_type='created'): # pylint: disable=too-many-locals
    filename = tempfile.gettempdir() + os.path.sep + 'pdk_' + generator + '.txt'

    with io.open(filename, 'w', encoding='utf-8') as outfile:
        writer = csv.writer(outfile, delimiter='\t')

        writer.writerow([
            'Source',
            'Created Timestamp',
            'Created Date',
            'Recorded Timestamp',
            'Recorded Date',
            'Event Name',
            'Event Properties'
        ])

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

            index = 0
            count = points.count()

            while index < count:
                for point in points[index:(index + 5000)]:
                    row = []

                    created = point.created.astimezone(pytz.timezone(settings.TIME_ZONE))
                    recorded = point.recorded.astimezone(pytz.timezone(settings.TIME_ZONE))

                    row.append(point.source)
                    row.append(calendar.timegm(point.created.utctimetuple()))
                    row.append(created.isoformat())

                    row.append(calendar.timegm(point.recorded.utctimetuple()))
                    row.append(recorded.isoformat())

                    properties = {}

                    properties = point.properties

                    row.append(properties['event_name'])

                    if 'event_details' in properties:
                        row.append(json.dumps(properties['event_details']))

                    writer.writerow(row)

                index += 5000

    return filename

def data_table(source, generator):
    context = {}
    context['source'] = source
    context['generator_identifier'] = generator

    end = timezone.now()
    start = end - datetime.timedelta(days=30)

    context['values'] = DataPoint.objects.filter(source=source.identifier, generator_identifier=generator, created__gt=start, created__lte=end).order_by('created')

    return render_to_string('pdk_app_event_table_template.html', context)

def visualization(source, generator): # pylint: disable=unused-argument
    filename = settings.MEDIA_ROOT + os.path.sep + 'pdk_visualizations' + os.path.sep + source.identifier + os.path.sep + 'pdk-app-event' + os.path.sep + 'timestamp-counts.json'

    with io.open(filename, encoding='utf-8') as infile:
        data = json.load(infile)

        context = {}

        context['data'] = data

        return render_to_string('pdk_app_event_viz_template.html', context)

    return None

def compile_visualization(identifier, points, folder, source=None): # pylint: disable=unused-argument
    now = timezone.now()

    now = now.replace(second=0, microsecond=0)

    remainder = now.minute % 10

    now = now.replace(minute=(now.minute - remainder))

    start = now - datetime.timedelta(days=2)

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
        timestamp = str(time.mktime(start.timetuple()))

        keys.append(timestamp)

        timestamp_counts[timestamp] = 0

        while point is not None and point.created < end and point_index < (point_count - 1):
            timestamp_counts[timestamp] += 1

            point_index += 1

            point = points[point_index]

        start = end
        end = start + datetime.timedelta(seconds=600)

    timestamp_counts['keys'] = keys

    with io.open(folder + os.path.sep + 'timestamp-counts.json', 'w', encoding='utf-8') as outfile:
        outfile.write(json.dumps(timestamp_counts, indent=2, ensure_ascii=False))

def update_data_type_definition(definition):
    if 'event_name' in definition:
        definition['event_name']['pdk_variable_name'] = 'Event name'
        definition['event_name']['pdk_variable_description'] = 'Name of the event emitted. Name assigned by app developer.'
        definition['event_name']['pdk_codebook_group'] = 'Passive Data Kit: App Events'
        definition['event_name']['pdk_codebook_order'] = 0
        definition['event_name']['examples'] = definition['event_name']['observed'][:16]

    if 'event_details' in definition:
        definition['event_details']['pdk_variable_name'] = 'Event value'
        definition['event_details']['pdk_variable_description'] = 'Details about the app event. Structure is determined by app developer.'
        definition['event_details']['pdk_codebook_group'] = 'Passive Data Kit: App Events'
        definition['event_details']['pdk_codebook_order'] = 1

    to_delete = []

    for key in definition.keys():
        if key.startswith('event_details.'):
            to_delete.append(key)

    for key in to_delete:
        del definition[key]

    del definition['observed']

    definition['pdk_description'] = 'Simple app event reporting capability built into Passive Data Kit. App developers can log events by name, and using a custom structure (expressible in JSON) for the values.'
