# pylint: disable=line-too-long, no-member

import calendar
import csv
import datetime
import io
import os
import tempfile

from zipfile import ZipFile

import arrow

from django.template.loader import render_to_string
from django.utils import timezone

from ..models import DataPoint, DataSourceReference, DataGeneratorDefinition

SECONDARY_IDENTIFIER_ACTIVITY = 'activity-measures'
SECONDARY_IDENTIFIER_INTRADAY = 'intraday-activity'
SECONDARY_IDENTIFIER_SLEEP = 'sleep-measures'
SECONDARY_IDENTIFIER_BODY = 'body'

SECONDARY_FIELDS = {
    'intraday-activity': [
        'intraday_activity_history',
        'activity_start',
        'activity_duration',
        'calories',
        'distance',
        'elevation_climbed',
        'steps',
        'swim_strokes',
        'pool_laps',
    ],
    'body': [
        'measure_date',
        'measure_status',
        'measure_category',
        'measure_type',
        'measure_value',
    ],
    'activity-measures': [
        'date_start',
        'timezone',
        'steps',
        'distance',
        'active_calories',
        'total_calories',
        'elevation',
        'soft_activity_duration',
        'moderate_activity_duration',
        'intense_activity_duration',
    ],
    'sleep-measures': [
        'start_date',
        'end_date',
        'state',
        'measurement_device',
    ]
}

def generator_name(identifier): # pylint: disable=unused-argument
    return 'Withings Device'

def extract_secondary_identifier(properties):
    if 'datastream' in properties:
        return properties['datastream']

    return None

# def extra_generators(generator): # pylint: disable=unused-argument
#    return [('pdk-withings-device-full', 'Full Withings Server Data')]

def compile_report(generator, sources, data_start=None, data_end=None, date_type='created'): # pylint: disable=too-many-locals, too-many-branches
    now = arrow.get()
    filename = tempfile.gettempdir() + os.path.sep + 'pdk_export_' + str(now.timestamp) + str(now.microsecond // 1e6) + '.zip'

    if generator == 'pdk-withings-device':
        with ZipFile(filename, 'w') as export_file:
            for secondary_identifier, identifier_columns in SECONDARY_FIELDS.items():
                secondary_filename = tempfile.gettempdir() + os.path.sep + generator + '-' + \
                                     secondary_identifier + '.txt'

                with io.open(secondary_filename, 'w', encoding='utf-8') as outfile:
                    writer = csv.writer(outfile, delimiter='\t')

                    columns = [
                        'Source',
                        'Created Timestamp',
                        'Created Date',
                        'Recorded Timestamp',
                        'Recorded Date',
                    ]

                    for column in identifier_columns:
                        columns.append(column)

                    writer.writerow(columns)

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

                                row.append(point.source)
                                row.append(calendar.timegm(point.created.utctimetuple()))
                                row.append(point.created.isoformat())
                                row.append(calendar.timegm(point.recorded.utctimetuple()))
                                row.append(point.recorded.isoformat())

                                properties = point.fetch_properties()

                                for column in identifier_columns:
                                    if column in properties:
                                        row.append(properties[column])
                                    else:
                                        row.append('')

                                writer.writerow(row)

                            index += 5000

                export_file.write(secondary_filename, secondary_filename.split(os.path.sep)[-1])

                os.remove(secondary_filename)

        return filename

    return None

def data_table(source, generator):
    context = {}
    context['source'] = source
    context['generator_identifier'] = generator

    end = timezone.now()
    start = end - datetime.timedelta(days=7)

    context['activity_values'] = DataPoint.objects.filter(source=source.identifier, generator_identifier=generator, secondary_identifier=SECONDARY_IDENTIFIER_ACTIVITY, created__gt=start, created__lte=end).order_by('created')
    context['intraday_values'] = DataPoint.objects.filter(source=source.identifier, generator_identifier=generator, secondary_identifier=SECONDARY_IDENTIFIER_INTRADAY, created__gt=start, created__lte=end).order_by('created')
    context['sleep_values'] = DataPoint.objects.filter(source=source.identifier, generator_identifier=generator, secondary_identifier=SECONDARY_IDENTIFIER_SLEEP, created__lte=end).order_by('created') # created__gt=start,
    context['body_values'] = DataPoint.objects.filter(source=source.identifier, generator_identifier=generator, secondary_identifier=SECONDARY_IDENTIFIER_BODY, created__lte=end).order_by('created')

    return render_to_string('pdk_wearable_withings_device_table_template.html', context)
