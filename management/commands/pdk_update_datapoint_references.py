# pylint: disable=no-member, line-too-long

from __future__ import print_function

from builtins import str # pylint: disable=redefined-builtin

import sys

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from ...decorators import handle_lock
from ...models import DataPoint

PAGE_SIZE = 5000

class Command(BaseCommand):
    help = 'Populates generator and source references on data points missing that metadata by iterating through all points in reverse order of ingestion.'

    @handle_lock
    def handle(self, *args, **options):
        last_check = timezone.now()

        query = Q(source_reference_id=None) | Q(generator_definition_id=None)

        remaining = DataPoint.objects.filter(query).count()

        # print('Pending: ' + str(remaining))
        # sys.stdout.flush()

        while remaining > 0:
            with transaction.atomic():
                for point in DataPoint.objects.filter(query)[:PAGE_SIZE]:
                    updated = False

                    if point.source_reference is None:
                        point.fetch_source_reference(skip_save=True)
                        updated = True

                    if point.generator_definition is None:
                        point.fetch_generator_definition(skip_save=True)
                        updated = True

                    if updated:
                        point.save()

            now = timezone.now()

            print('Elapsed: ' + str((now - last_check).total_seconds()))
            sys.stdout.flush()
            last_check = now

            remaining = DataPoint.objects.filter(query).count()

            print('Pending: ' + str(remaining))
            sys.stdout.flush()
