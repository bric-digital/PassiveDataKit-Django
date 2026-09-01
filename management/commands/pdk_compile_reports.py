# -*- coding: utf-8 -*-
# pylint: disable=no-member,line-too-long

import datetime
import importlib
import io
import json
import logging
import os
import tempfile
import traceback
import zipfile

import zipstream

import pytz

from django.conf import settings
from django.core.files import File
from django.core.mail import send_mail
from django.core.management.base import BaseCommand
from django.template.loader import render_to_string
from django.utils import timezone

from ...decorators import handle_lock, log_scheduled_event
from ...models import DataPoint, ReportJob, ReportJobBatchRequest, DataGeneratorDefinition, DataSourceReference, DataSource

REMOVE_SLEEP_MAX = 60 # Added to avoid "WindowsError: [Error 32] The process cannot access the file because it is being used by another process"

class Command(BaseCommand):
    help = 'Compiles data reports requested by end users.'

    def add_arguments(self, parser):
        pass

    @handle_lock()
    @log_scheduled_event
    def handle(self, *args, **options): # pylint: disable=too-many-locals,too-many-branches,too-many-statements
        os.umask(000)

        pending = ReportJob.objects.filter(started=None, completed=None)

        while pending.count() > 0:
            report = ReportJob.objects.filter(started=None, completed=None)\
                                      .order_by('-priority', 'requested', 'pk')\
                                      .first()

            if report is not None:
                report.started = timezone.now()
                report.save()

                parameters = report.fetch_parameters()

                sources = parameters['sources']
                generators = parameters['generators']

                data_start = None
                data_end = None

                tz_info = pytz.timezone(settings.TIME_ZONE)

                if 'data_start' in parameters and parameters['data_start']:
                    tokens = parameters['data_start'].split('/')

                    data_start = datetime.datetime(int(tokens[2]), \
                                                   int(tokens[0]), \
                                                   int(tokens[1]), \
                                                   0, \
                                                   0, \
                                                   0, \
                                                   0).astimezone(tz_info)

                if 'data_end' in parameters and parameters['data_end']:
                    tokens = parameters['data_end'].split('/')

                    data_end = datetime.datetime(int(tokens[2]), \
                                                 int(tokens[0]), \
                                                 int(tokens[1]), \
                                                 23, \
                                                 59, \
                                                 59, \
                                                 999999).astimezone(tz_info)

                date_type = 'created'

                if 'date_type' in parameters and parameters['date_type']:
                    date_type = parameters['date_type']

                raw_json = False

                if ('raw_data' in parameters) and (parameters['raw_data'] is True or parameters['raw_data'] == 'on'):
                    raw_json = True

                prefix = 'pdk_export_final'

                if 'prefix' in parameters:
                    prefix = parameters['prefix']

                suffix = report.started.date().isoformat()

                if 'suffix' in parameters:
                    suffix = parameters['suffix']

                filename = tempfile.gettempdir() + os.path.sep + prefix + '_' + str(report.pk) + '_' + suffix + '.zip'

                zips_to_merge = []

                excluded_sources = []

                try:
                    excluded_sources = settings.PDK_EXCLUDED_SOURCES
                except AttributeError:
                    pass

                for excluded_source in excluded_sources:
                    while excluded_source in sources:
                        sources.remove(excluded_source)

                with open(filename, 'wb') as final_output_file:
                    to_delete = []

                    with zipstream.ZipFile(mode='w', compression=zipfile.ZIP_DEFLATED, allowZip64=True) as export_stream: # pylint: disable=line-too-long
                        for generator in generators: # pylint: disable=too-many-nested-blocks
                            logging.info('pdk_compile_reports: Exporting %s for %s.', generator, sources)

                            if raw_json:
                                for source in sources:
                                    data_source = DataSource.objects.filter(identifier=source).first()

                                    if data_source is not None and data_source.server is None:
                                        generator_definition = DataGeneratorDefinition.definition_for_identifier(generator)
                                        source_reference = DataSourceReference.reference_for_source(source)

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

                                        points = points.order_by('created')

                                        first = points.first() # pylint: disable=line-too-long
                                        last = points.last() # pylint: disable=line-too-long

                                        if first is not None:
                                            first_create = first.created
                                            last_create = last.created

                                            start = datetime.datetime(first_create.year, \
                                                                      first_create.month, \
                                                                      first_create.day, \
                                                                      0, \
                                                                      0, \
                                                                      0, \
                                                                      0, \
                                                                      first_create.tzinfo)

                                            end = datetime.datetime(last_create.year, \
                                                                    last_create.month, \
                                                                    last_create.day, \
                                                                    0, \
                                                                    0, \
                                                                    0, \
                                                                    0, \
                                                                    first_create.tzinfo) + \
                                                                    datetime.timedelta(days=1)

                                            if data_start is not None and data_start > start:
                                                start = data_start

                                            if data_end is not None and data_end < end:
                                                end = data_end

                                            while start <= end:
                                                day_end = start + datetime.timedelta(days=1)

                                                day_filename = source + '__' + generator + '__' + \
                                                               start.date().isoformat() + '.json'

                                                points = DataPoint.objects.filter(source_reference=source_reference, generator_definition=generator_definition, created__gte=start, created__lt=day_end).order_by('created') # pylint: disable=line-too-long

                                                out_points = []

                                                for point in points:
                                                    out_points.append(point.fetch_properties())

                                                if out_points:
                                                    export_stream.writestr(day_filename, str(json.dumps(out_points, indent=2)).encode("utf-8")) # pylint: disable=line-too-long

                                                start = day_end
                            else:
                                output_file = None

                                for app in settings.INSTALLED_APPS:
                                    if output_file is None:
                                        try:
                                            pdk_api = importlib.import_module(app + '.pdk_api')

                                            try:
                                                logging.info('pdk_compile_reports: Exporting for %s: %s.%s.', sources, app, generator)

                                                output_file = pdk_api.compile_report(generator, sources, data_start=data_start, data_end=data_end, date_type=date_type)

                                                if output_file is not None:
                                                    output_file = os.path.normpath(output_file)

                                                    if generator != 'pdk-personal-data':
                                                        if output_file.lower().endswith('.zip'):
                                                            zips_to_merge.append(output_file)

                                                            # with zipfile.ZipFile(output_file, 'r') as source_file:
                                                            #    for name in source_file.namelist():
                                                            #        data_file = source_file.open(name)

                                                            #        export_stream.write_iter(name, data_file, compress_type=zipfile.ZIP_DEFLATED)
                                                        else:
                                                            name = os.path.basename(os.path.normpath(output_file))

                                                            export_stream.write(output_file, name, compress_type=zipfile.ZIP_DEFLATED)

                                                            to_delete.append(output_file)
                                                    else:
                                                        name = os.path.basename(os.path.normpath(output_file))

                                                        export_stream.write(output_file, name, compress_type=zipfile.ZIP_DEFLATED)
                                            except TypeError as exception:
                                                traceback.print_exc()
                                                logging.warning('Verify that %s.%s implements all compile_report arguments!', app, generator)
                                                raise exception
                                        except ImportError:
                                            output_file = None
                                        except AttributeError:
                                            output_file = None

                        for data in export_stream:
                            final_output_file.write(data)

                if zips_to_merge:
                    with zipfile.ZipFile(filename, 'a', compression=zipfile.ZIP_BZIP2) as zip_output:
                        for zip_filename in zips_to_merge:
                            with zipfile.ZipFile(zip_filename, 'r') as zip_file:
                                for child_file in zip_file.namelist():
                                    child_filename = tempfile.gettempdir() + os.path.sep + child_file

                                    logging.info('pdk_compile_reports: Extracting %s to %s.', child_file, child_filename)

                                    zip_file.extract(child_file, path=tempfile.gettempdir())

                                    logging.info('pdk_compile_reports: Extracted %s to %s.', child_file, child_filename)

                                    zip_output.write(child_filename, child_file, compress_type=zipfile.ZIP_BZIP2)

                                    logging.info('pdk_compile_reports: Finished writing %s.', child_file)

                                    os.remove(child_filename)

                            to_delete.append(zip_filename)

                for output_file in to_delete:
                    remove_sleep = 1.0

                    while remove_sleep < REMOVE_SLEEP_MAX:
                        try:
                            os.remove(output_file)

                            remove_sleep = REMOVE_SLEEP_MAX
                        except OSError:
                            remove_sleep = remove_sleep * 2

                            if remove_sleep >= REMOVE_SLEEP_MAX:
                                traceback.print_exc()

                report.completed = timezone.now()

                with io.open(filename, 'rb') as report_file:
                    report.report.save(filename.split(os.path.sep)[-1], File(report_file))

                report.save()

                if report.requester.email is not None:
                    subject = render_to_string('pdk_report_subject.txt', {
                        'report': report,
                        'url': settings.SITE_URL
                    })

                    if 'email_subject' in parameters:
                        subject = parameters['email_subject']

                    message = render_to_string('pdk_report_message.txt', {
                        'report': report,
                        'url': settings.SITE_URL
                    })

                    tokens = settings.SITE_URL.split('/')
                    host = ''

                    while tokens and tokens[-1] == '':
                        tokens.pop()

                    if tokens:
                        host = tokens[-1]

                    send_mail(subject, \
                              message, \
                              'Petey Kay <noreply@' + host + '>', \
                              [report.requester.email], \
                              fail_silently=False)

                for extra_destination in report.requester.pdk_report_destinations.all():
                    extra_destination.transmit(report, filename)

                remove_sleep = 1.0

                while remove_sleep < REMOVE_SLEEP_MAX:
                    try:
                        os.remove(filename)

                        remove_sleep = REMOVE_SLEEP_MAX
                    except OSError:
                        remove_sleep = remove_sleep * 2

                        if remove_sleep >= REMOVE_SLEEP_MAX:
                            traceback.print_exc()

        request = ReportJobBatchRequest.objects.filter(started=None, completed=None)\
                      .order_by('-priority', 'requested', 'pk')\
                      .first()

        if request is not None:
            if options.get('verbosity') > 0:
                logging.info('pdk_compile_reports: Splitting batch request %d.', request.pk)

            request.process()
