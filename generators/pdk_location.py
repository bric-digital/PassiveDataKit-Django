# pylint: disable=line-too-long, no-member

import calendar
import csv
import io
import json
import os
import tempfile
import time
import traceback
import zipfile

from zipfile import ZipFile

import arrow
import pytz

from django.conf import settings
from django.contrib.gis.geos import GEOSGeometry
from django.template.loader import render_to_string
from django.utils.text import slugify

from ..models import DataPoint, DataSourceReference, DataGeneratorDefinition

def extract_secondary_identifier(properties):
    if 'status' in properties:
        return properties['status']

    return None

def generator_name(identifier): # pylint: disable=unused-argument
    return 'Device Location'

def visualization(source, generator):
    context = {}
    context['source'] = source
    context['generator_identifier'] = generator

    try:
        context['google_api_key'] = settings.PDK_GOOGLE_MAPS_API_KEY
    except AttributeError:
        pass

    values = []

    min_latitude = 90
    max_latitude = -90

    min_longitude = 180
    max_longitude = -180

    start = None
    end = None

    for point in DataPoint.objects.filter(source=source.identifier, generator_identifier=generator).order_by('-created')[:500]:
        if end is None:
            end = point.created

        start = point.created

        properties = point.fetch_properties()

        values.append(properties)

        latitude = properties['latitude']
        longitude = properties['longitude']

        min_latitude = min(min_latitude, latitude)

        max_latitude = max(max_latitude, latitude)

        min_longitude = min(min_longitude, longitude)

        max_longitude = max(max_longitude, longitude)

    context['values'] = values

    context['center_latitude'] = (min_latitude + max_latitude) // 2
    context['center_longitude'] = (min_longitude + max_longitude) // 2

    context['start'] = time.mktime(start.timetuple())
    context['end'] = time.mktime(end.timetuple())

    return render_to_string('generators/pdk_device_location_template.html', context)

def data_table(source, generator):
    context = {}
    context['source'] = source
    context['generator_identifier'] = generator

    context['values'] = DataPoint.objects.filter(source=source.identifier, generator_identifier=generator).order_by('-created')[:500]

    return render_to_string('generators/pdk_device_location_table_template.html', context)

def compile_report(generator, sources, data_start=None, data_end=None, date_type='created'): # pylint: disable=too-many-locals, too-many-branches, too-many-statements
    now = arrow.get()
    filename = tempfile.gettempdir() + os.path.sep + 'pdk_export_' + str(now.timestamp) + str(now.microsecond // 1e6) + '.zip'

    with ZipFile(filename, 'w', allowZip64=True) as export_file:
        seen_sources = []

        for source in sources:
            export_source = source

            seen_index = 1

            while slugify(export_source) in seen_sources:
                export_source = source + '__' + str(seen_index)

                seen_index += 1

            seen_sources.append(slugify(export_source))

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
                    'Raw Timestamp',
                    'Provider',
                    'Latitude',
                    'Longitude',
                    'Accuracy',
                    'Altitude',
                    'Speed',
                    'Bearing',
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
                        row.append(properties['location_timestamp'])
                    except KeyError:
                        row.append('')

                    try:
                        row.append(properties['provider'])
                    except KeyError:
                        row.append('')

                    try:
                        row.append(properties['latitude'])
                    except KeyError:
                        row.append('')

                    try:
                        row.append(properties['longitude'])
                    except KeyError:
                        row.append('')

                    try:
                        row.append(properties['accuracy'])
                    except KeyError:
                        row.append('')

                    try:
                        row.append(properties['altitude'])
                    except KeyError:
                        row.append('')

                    try:
                        row.append(properties['speed'])
                    except KeyError:
                        row.append('')

                    try:
                        row.append(properties['bearing'])
                    except KeyError:
                        row.append('')

                    writer.writerow(row)

            export_file.write(secondary_filename, slugify(generator) + '/' + slugify(export_source) + '.txt')

            os.remove(secondary_filename)

    return filename

def extract_location(point):
    properties = point.fetch_properties()

    latitude = properties['latitude']
    longitude = properties['longitude']

    if latitude is not None and longitude is not None:
        point.generated_at = GEOSGeometry('POINT(' + str(longitude) + ' ' + str(latitude) + ')')
        point.save()


def compile_personal_report(generator, sources, data_start=None, data_end=None, date_type='created'): # pylint: disable=too-many-locals, too-many-branches, too-many-statements, unused-argument
    now = arrow.get()

    filename = tempfile.gettempdir() + '/pdk_export_' + str(now.timestamp) + str(now.microsecond // 1e6) + '.zip'

    try:
        with zipfile.ZipFile(filename, 'w', allowZip64=True) as export_file:
            for source in sources:
                source_reference = DataSourceReference.reference_for_source(source)
                generator_definition = DataGeneratorDefinition.definition_for_identifier('pdk-location')

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

                root_geojson = {
                    'type': 'FeatureCollection',
                    'crs': {
                        'type': 'name',
                        'properties': {
                            'name': 'urn:ogc:def:crs:OGC:1.3:CRS84'
                        }
                    }
                }

                features = []

                last_timestamp = 0

                for point in points.order_by('created'):
                    properties = point.fetch_properties()

                    here_tz = pytz.timezone(settings.TIME_ZONE)

                    if 'timezone' in properties['passive-data-metadata']:
                        here_tz = pytz.timezone(properties['passive-data-metadata']['timezone'])

                    created_date = point.created.astimezone(here_tz)

                    timestamp = calendar.timegm(created_date.utctimetuple())

                    if (timestamp - last_timestamp) >= 300:
                        last_timestamp = timestamp

                        feature = {
                            'type': 'Feature',
                            'properties': {
                                'id': 'pk:' + str(point.pk),
                                'timestamp': timestamp,
                                'datetime': created_date.isoformat()
                            }
                        }

                        try:
                            feature['properties']['provider'] = properties['provider']
                        except KeyError:
                            pass

                        try:
                            feature['properties']['accuracy'] = properties['accuracy']
                        except KeyError:
                            pass

                        try:
                            feature['properties']['speed'] = properties['speed']
                        except KeyError:
                            pass

                        try:
                            feature['properties']['bearing'] = properties['bearing']
                        except KeyError:
                            pass

                        coordinates = [properties['longitude'], properties['latitude'], 0]

                        try:
                            feature['properties']['altitude'] = properties['altitude']
                            coordinates[2] = properties['altitude']
                        except KeyError:
                            pass

                        feature['geometry'] = {
                            'type': 'Point',
                            'coordinates': coordinates
                        }

                        features.append(feature)

                root_geojson['features'] = features

                export_file.writestr('data/pdk-location.json', 'var data = ' + json.dumps(root_geojson, indent=2) + ';', zipfile.ZIP_DEFLATED)

                path = os.path.abspath(__file__)

                dir_path = os.path.dirname(path)

                assets_path = dir_path + '/../assets/pdk_personal_data'

                export_file.write(os.path.join(assets_path, 'pdk-location.html'), 'pdk-location.html')
    except: # pylint: disable=bare-except
        traceback.print_exc()

        filename = None

    return filename
