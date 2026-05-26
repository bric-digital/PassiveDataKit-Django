# pylint: disable=line-too-long, no-member

import calendar
import csv
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
    return 'System Status'

def visualization(source, generator):
    context = {}
    context['source'] = source
    context['generator_identifier'] = generator

    start = timezone.now() - datetime.timedelta(days=7)

    context['values'] = DataPoint.objects.filter(source=source.identifier, generator_identifier=generator, created__gte=start).order_by('-created')

    filename = settings.MEDIA_ROOT + os.path.sep + 'pdk_visualizations' + os.path.sep + source.identifier + os.path.sep + 'pdk-system-status' + os.path.sep + 'timestamp-counts.json'

    try:
        with io.open(filename, encoding='utf-8') as infile:
            hz_data = json.load(infile)

            context['hz_data'] = hz_data
    except IOError:
        context['hz_data'] = {}

    return render_to_string('generators/pdk_device_system_status_template.html', context)

def data_table(source, generator):
    context = {}
    context['source'] = source
    context['generator_identifier'] = generator

    start = timezone.now() - datetime.timedelta(days=7)

    context['values'] = DataPoint.objects.filter(source=source.identifier, generator_identifier=generator, created__gte=start).order_by('-created')

    return render_to_string('generators/pdk_device_system_status_table_template.html', context)

def compile_report(generator, sources, data_start=None, data_end=None, date_type='created'): # pylint: disable=too-many-locals, too-many-branches, too-many-statements
    now = arrow.get()
    filename = tempfile.gettempdir() + os.path.sep + 'pdk_export_' + str(now.timestamp) + str(now.microsecond // 1e6) + '.zip'

    with ZipFile(filename, 'w') as export_file:
        seen_sources = []

        for source in sources:
            export_source = source

            seen_index = 1

            while slugify(export_source) in seen_sources:
                export_source = source + '__' + str(seen_index)

                seen_index += 1

            seen_sources.append(slugify(export_source))

            identifier = slugify(generator + '__' + export_source)

            secondary_filename = tempfile.gettempdir() + os.path.sep + identifier + '.txt'

            with io.open(secondary_filename, 'w', encoding='utf-8') as outfile:
                writer = csv.writer(outfile, delimiter='\t')

                columns = [
                    'Source',
                    'Created Timestamp',
                    'Created Date',
                    'Recorded Timestamp',
                    'Recorded Date',
                    'Available Storage',
                    'Other Storage',
                    'App Storage',
                    'Total Storage',
                    'App Runtime',
                    'System Runtime',
                    'Pending Points',
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

                    row.append(properties.get('storage_available', None))
                    row.append(properties.get('storage_other', None))
                    row.append(properties.get('storage_app', None))
                    row.append(properties.get('storage_total', None))

                    row.append(properties.get('runtime', None))
                    row.append(properties.get('system_runtime', None))

                    row.append(properties.get('pending_points', None))

                    writer.writerow(row)

            export_file.write(secondary_filename, slugify(generator) + '/' + slugify(export_source) + '.txt')

            os.remove(secondary_filename)

    return filename

def compile_visualization(identifier, points, folder, source=None): # pylint: disable=unused-argument, too-many-locals
    now = timezone.now()

    latest = points.order_by('-created').first()

    if latest is not None:
        now = latest.created

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

def update_data_type_definition(definition): # pylint: disable=too-many-branches, too-many-statements
    if 'runtime' in definition:
        definition['runtime']['pdk_variable_name'] = 'App runtime'
        definition['runtime']['pdk_variable_description'] = 'Measures the number of milliseconds since the app\'s last restart.'
        definition['runtime']['pdk_codebook_group'] = 'Passive Data Kit: Device Status (Runtime)'
        definition['runtime']['pdk_codebook_order'] = 0
        definition['runtime']['types'] = ['timestamp']

    if 'system_runtime' in definition:
        definition['system_runtime']['pdk_variable_name'] = 'Device runtime'
        definition['system_runtime']['pdk_variable_description'] = 'Measures the number of milliseconds since the device\'s last restart, including periods spent sleeping.'
        definition['system_runtime']['pdk_codebook_group'] = 'Passive Data Kit: Device Status (Runtime)'
        definition['system_runtime']['pdk_codebook_order'] = 1
        definition['system_runtime']['types'] = ['timestamp']

    if 'storage_path' in definition:
        definition['storage_path']['pdk_variable_name'] = 'App data path'
        definition['storage_path']['pdk_variable_description'] = 'Path to the location on the device where the app is storing user data.'
        definition['storage_path']['pdk_codebook_group'] = 'Passive Data Kit: Device Status (Storage)'
        definition['storage_path']['pdk_codebook_order'] = 0

    if 'storage_total' in definition:
        definition['storage_total']['pdk_variable_name'] = 'Total device storage'
        definition['storage_total']['pdk_variable_description'] = 'Total available storage space (used and free, in bytes) on the device.'
        definition['storage_total']['pdk_codebook_group'] = 'Passive Data Kit: Device Status (Storage)'
        definition['storage_total']['pdk_codebook_order'] = 1

    if 'storage_available' in definition:
        definition['storage_available']['pdk_variable_name'] = 'Availiable device storage'
        definition['storage_available']['pdk_variable_description'] = 'Total free storage space (in bytes) on the device available for use.'
        definition['storage_available']['pdk_codebook_group'] = 'Passive Data Kit: Device Status (Storage)'
        definition['storage_available']['pdk_codebook_order'] = 2

    if 'storage_app' in definition:
        definition['storage_app']['pdk_variable_name'] = 'App data storage'
        definition['storage_app']['pdk_variable_description'] = 'Storage space (in bytes) used for app data.'
        definition['storage_app']['pdk_codebook_group'] = 'Passive Data Kit: Device Status (Storage)'
        definition['storage_app']['pdk_codebook_order'] = 3

    if 'storage_other' in definition:
        definition['storage_other']['pdk_variable_name'] = 'System and other apps\' storage'
        definition['storage_other']['pdk_variable_description'] = 'Amount of storage (in bytes) used by other apps and the system.'
        definition['storage_other']['pdk_codebook_group'] = 'Passive Data Kit: Device Status (Storage)'
        definition['storage_other']['pdk_codebook_order'] = 0

    if 'granted_permissions' in definition:
        definition['granted_permissions']['pdk_variable_name'] = 'Granted permissions'
        definition['granted_permissions']['pdk_variable_description'] = 'Local device permissions granted to the app.'
        definition['granted_permissions']['pdk_codebook_group'] = 'Passive Data Kit: Device Status (Permissions)'
        definition['granted_permissions']['pdk_codebook_order'] = 0

    if 'missing_permissions' in definition:
        definition['missing_permissions']['pdk_variable_name'] = 'Denied permissions'
        definition['missing_permissions']['pdk_variable_description'] = 'Local device permissions denied to the app by the user or system. Also includes permissions that may not be available on the device.'
        definition['missing_permissions']['pdk_codebook_group'] = 'Passive Data Kit: Device Status (Permissions)'
        definition['missing_permissions']['pdk_codebook_order'] = 1

    if 'has_app_usage_permission' in definition:
        definition['has_app_usage_permission']['pdk_variable_name'] = 'App usage data permission status'
        definition['has_app_usage_permission']['pdk_variable_description'] = 'Indicates whether the user has granted the app permission to access app usage data on the device.'
        definition['has_app_usage_permission']['pdk_codebook_group'] = 'Passive Data Kit: Device Status (Permissions)'
        definition['has_app_usage_permission']['pdk_codebook_order'] = 2
        definition['has_app_usage_permission']['types'] = ['boolean']

    if 'ignores_battery_optimization' in definition:
        definition['ignores_battery_optimization']['pdk_variable_name'] = 'App ignores system power optimizations'
        definition['ignores_battery_optimization']['pdk_variable_description'] = 'Indicates whether the user has granted the app ignore device power optimizations and run unimpeded.'
        definition['ignores_battery_optimization']['pdk_codebook_group'] = 'Passive Data Kit: Device Status (Permissions)'
        definition['ignores_battery_optimization']['pdk_codebook_order'] = 3
        definition['ignores_battery_optimization']['types'] = ['boolean']

    if 'pending_transmissions' in definition:
        definition['pending_transmissions']['pdk_variable_name'] = 'Pending data transmissions'
        definition['pending_transmissions']['pdk_variable_description'] = 'Number of data bundles on the device awaiting transmission to the server.'
        definition['pending_transmissions']['pdk_codebook_group'] = 'Passive Data Kit: Device Status'
        definition['pending_transmissions']['pdk_codebook_order'] = 0

    if 'remote_options' in definition:
        definition['remote_options']['pdk_variable_name'] = 'Remote configuration'
        definition['remote_options']['pdk_variable_description'] = 'Contains the remote configuration (in JSON format) that the device retrieved from the server.'
        definition['remote_options']['pdk_codebook_group'] = 'Passive Data Kit: Device Status'
        definition['remote_options']['pdk_codebook_order'] = 0
        definition['remote_options']['types'] = ['timestamp']

    del definition['observed']

    definition['pdk_description'] = 'Routine device status reports generated to assist with app troubleshooting (e.g. missing data transmissions) and to monitor the status of devices sending data.'
