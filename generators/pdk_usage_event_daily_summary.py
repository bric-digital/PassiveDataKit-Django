# pylint: disable=line-too-long, no-member

import calendar
import csv
import io
import os
import tempfile

from zipfile import ZipFile

import arrow
import pytz

from django.conf import settings
from django.utils.text import slugify

from ..models import DataPoint, DataSourceReference, DataGeneratorDefinition

def generator_name(identifier): # pylint: disable=unused-argument
    return 'Device Usage Events (Daily Summary)'

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
                    'Package',
                    'Event',
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

                    for event in properties.get('events', []):
                        row = []

                        created = arrow.get(event.get('observed', 0.0)).datetime.astimezone(pytz.timezone(settings.TIME_ZONE))
                        recorded = point.recorded.astimezone(pytz.timezone(settings.TIME_ZONE))

                        row.append(point.source)
                        row.append(calendar.timegm(point.created.utctimetuple()))
                        row.append(created.isoformat())

                        row.append(calendar.timegm(point.recorded.utctimetuple()))
                        row.append(recorded.isoformat())

                        row.append(event.get('package', ''))
                        row.append(event.get('event_type', ''))

                        writer.writerow(row)

                if points.count() > 0:
                    export_file.write(secondary_filename, slugify(generator) + '/' + slugify(export_source) + '.txt')

            os.remove(secondary_filename)

    return filename
