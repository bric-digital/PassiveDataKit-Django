# -*- coding: utf-8 -*-
# pylint: disable=no-member,line-too-long

import copy
import os

from django.core.management.base import BaseCommand

from ...decorators import handle_lock
from ...models import ReportJob

class Command(BaseCommand):
    help = 'Splits existing jobs into two new jobs.'

    def add_arguments(self, parser):
        parser.add_argument('--pk',
                            type=int,
                            dest='pk',
                            default=None,
                            help='PK of the job to split')

    @handle_lock
    def handle(self, *args, **options): # pylint: disable=too-many-locals,too-many-branches,too-many-statements
        os.umask(000)

        report = ReportJob.objects.get(pk=options['pk'])

        new_report = ReportJob(requester=report.requester, requested=report.requested)
        new_report.sequence_index = report.sequence_index
        new_report.sequence_count = report.sequence_count

        parameters = report.parameters

        new_sources = []
        old_sources = []

        index = 0

        print('Original sources: ' + str(len(parameters['sources'])))

        for source in parameters['sources']:
            if (index % 2) == 1:
                new_sources.append(source)
            else:
                old_sources.append(source)

            index += 1

        parameters['sources'] = old_sources

        new_parameters = copy.deepcopy(parameters)

        new_parameters['sources'] = new_sources

        print('Updated sources: ' + str(len(parameters['sources'])))
        print('New sources: ' + str(len(new_parameters['sources'])))

        report.parameters = parameters
        new_report.parameters = new_parameters

        report.save()
        new_report.save()
