# pylint: disable=line-too-long, no-member

import calendar
import collections
import csv
import datetime
import io
import json
import os
import re
import tempfile

from zipfile import ZipFile

import arrow

from django.contrib.gis.geos import GEOSGeometry
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.text import slugify

from passive_data_kit.models import DataPoint, DataSourceReference, DataGeneratorDefinition

def generator_name(identifier): # pylint: disable=unused-argument
    return 'Geofence Events'

def extract_secondary_identifier(properties):
    if 'transition' in properties:
        return properties['transition']

    return None

def extract_value(pattern, properties):
    for key, value in list(properties.items()):

        match = re.search(pattern, key)

        if match: # pylint: disable=no-else-return
            return float(value)
        elif isinstance(value, collections.Mapping):
            found_value = extract_value(pattern, value)

            if found_value is not None:
                return found_value

    return None

def extract_location(point):
    properties = point.fetch_properties()

    latitude = extract_value('.*latitude.*', properties)
    longitude = extract_value('.*longitude.*', properties)

    if latitude is not None and longitude is not None:
        point.generated_at = GEOSGeometry('POINT(' + str(longitude) + ' ' + str(latitude) + ')')
        point.save()

def data_table(source, generator):
    context = {}
    context['source'] = source
    context['generator_identifier'] = generator

    start = timezone.now() - datetime.timedelta(days=7)

    context['values'] = DataPoint.objects.filter(source=source.identifier, generator_identifier=generator, created__gte=start).order_by('-created')

    return render_to_string('generators/pdk_geofence_event_table_template.html', context)


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
                    'Observed',
                    'Fence ID',
                    'Fence Name',
                    'Transition',
                    'Center Latitude',
                    'Center Longitude',
                    'Radius',
                    'Details',
                ]

                writer.writerow(columns)

                for point in points:
                    properties = point.fetch_properties()

                    row = []

                    row.append(point.source)
                    row.append(calendar.timegm(point.created.utctimetuple()))
                    row.append(point.created.isoformat())

                    row.append(calendar.timegm(point.recorded.utctimetuple()))
                    row.append(point.recorded.isoformat())

                    try:
                        row.append(properties['observed'])
                    except KeyError:
                        row.append('')

                    try:
                        row.append(properties['fence_details']['identifier'])
                    except KeyError:
                        row.append('')

                    try:
                        row.append(properties['fence_details']['name'])
                    except KeyError:
                        row.append('')

                    try:
                        row.append(properties['transition'])
                    except KeyError:
                        row.append('')

                    try:
                        row.append(properties['fence_details']['center_latitude'])
                    except KeyError:
                        row.append('')

                    try:
                        row.append(properties['fence_details']['center_longitude'])
                    except KeyError:
                        row.append('')

                    try:
                        row.append(properties['fence_details']['radius'])
                    except KeyError:
                        row.append('')

                    try:
                        row.append(json.dumps(properties['fence_details']))
                    except KeyError:
                        row.append('')

                    writer.writerow(row)

            export_file.write(secondary_filename, slugify(generator) + '/' + slugify(source) + '.txt')

            os.remove(secondary_filename)

    return filename
