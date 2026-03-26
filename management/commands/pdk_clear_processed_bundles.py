# pylint: disable=no-member,line-too-long
from __future__ import print_function

import logging

from django.core.management.base import BaseCommand
from django.utils import timezone

from ...bundle_processing import new_bundle_trace_id, record_bundle_deleted
from ...decorators import handle_lock
from ...models import DataBundle

class Command(BaseCommand):
    help = 'Removes processed DataBundle instances ro reclaim disk space.'

    def add_arguments(self, parser):
        parser.add_argument('--count',
                            type=int,
                            dest='batch_count',
                            default=5000,
                            help='Number of bundles to process in a single loop before repeating')

    @handle_lock
    def handle(self, *args, **options): # pylint: disable=too-many-locals, too-many-branches, too-many-statements
        total = DataBundle.objects.filter(processed=True).count()

        first_bundle = DataBundle.objects.filter(processed=True).order_by('pk').only('pk').first()

        if first_bundle is not None:
            start = first_bundle.pk + options['batch_count']

            start = start - (start % options['batch_count'])

            deleted = 0

            bundles = DataBundle.objects.filter(processed=True, pk__lte=start)

            while bundles.count() > 0:
                logging.debug('Progress: %s of %s (%s)', deleted, total, timezone.now())

                for bundle in bundles.only('pk', 'recorded', 'encrypted', 'compression'):
                    record_bundle_deleted(bundle, new_bundle_trace_id())

                deleted += bundles._raw_delete(bundles.db) # pylint: disable=protected-access

                start += options['batch_count']

                bundles = DataBundle.objects.filter(processed=True, pk__lte=start)
