# -*- coding: utf-8 -*-
# pylint: disable=no-member,line-too-long

import datetime
import importlib
import io
import json
import os
import tempfile
import zipfile

import zipstream

import pytz

from django.conf import settings
from django.core.files import File
from django.core.mail import send_mail
from django.core.management.base import BaseCommand
from django.template.loader import render_to_string
from django.utils import timezone

from ...models import DataPoint, ReportJob, DataGeneratorDefinition, DataSourceReference, DataSource

class Command(BaseCommand):
    help = 'Compiles data reports requested by end users.'

    def add_arguments(self, parser):
        parser.add_argument('report_pk',
                            type=int,
                            nargs=1,
                            help='Identifier of report to compile')

    def handle(self, *args, **options): # pylint: disable=too-many-locals,too-many-branches,too-many-statements
        os.umask(000)

        report = ReportJob.objects.get(pk=options['report_pk'][0])

        report.started = timezone.now()
        report.save()

        parameters = {}

        parameters = report.parameters

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
                                           0, \
                                           tz_info)

        if 'data_end' in parameters and parameters['data_end']:
            tokens = parameters['data_end'].split('/')

            data_end = datetime.datetime(int(tokens[2]), \
                                         int(tokens[0]), \
                                         int(tokens[1]), \
                                         23, \
                                         59, \
                                         59, \
                                         999999, \
                                         tz_info)

        date_type = 'created'

        if 'date_type' in parameters and parameters['date_type']:
            date_type = parameters['date_type']

        raw_json = False

        if ('raw_data' in parameters) and parameters['raw_data'] is True:
            raw_json = True

        prefix = 'pdk_export_final'

        if 'prefix' in parameters:
            prefix = parameters['prefix']

        suffix = report.started.date().isoformat()

        if 'suffix' in parameters:
            suffix = parameters['suffix']

        filename = tempfile.gettempdir() + '/' + prefix + '_' + str(report.pk) + '_' + suffix + '.zip'

        with io.open(filename, 'wb') as final_output_file:
            with zipstream.ZipFile(mode='w', compression=zipfile.ZIP_DEFLATED, allowZip64=True) as export_stream: # pylint: disable=line-too-long
                to_delete = []

                for generator in generators: # pylint: disable=too-many-nested-blocks
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
                                        output_file = pdk_api.compile_report(generator, sources, data_start=data_start, data_end=data_end, date_type=date_type)

                                        if output_file is not None:
                                            if output_file.lower().endswith('.zip'):
                                                with zipfile.ZipFile(output_file, 'r') as source_file:
                                                    for name in source_file.namelist():
                                                        with source_file.open(name) as data_file:
                                                            export_stream.write_iter(name, data_file, compress_type=zipfile.ZIP_DEFLATED)
                                            else:
                                                name = os.path.basename(os.path.normpath(output_file))

                                                export_stream.write(output_file, name, compress_type=zipfile.ZIP_DEFLATED)

                                            to_delete.append(output_file)
                                    except TypeError as exception:
                                        print('Verify that ' + app + '.' + generator + ' implements all compile_report arguments!')
                                        raise exception
                                except ImportError:
                                    output_file = None
                                except AttributeError:
                                    output_file = None

                for data in export_stream:
                    final_output_file.write(data)

                for output_file in to_delete:
                    os.remove(output_file)

        report.completed = timezone.now()

        with io.open(filename, 'rb') as report_file:
            report.report.save(filename.split('/')[-1], File(report_file))

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
            extra_destination.transmit(filename)

        os.remove(filename)
