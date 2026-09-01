# pylint: disable=no-member,line-too-long

import logging

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.transaction import TransactionManagementError
from django.utils import timezone

from ...decorators import log_scheduled_event, handle_named_lock

from ...bundle_processing import BundleProcessingCore, BundleProcessingHalt, \
                                 new_bundle_trace_id, record_bundle_deleted, \
                                 record_bundle_processing_trace, save_serial_points, \
                                 strip_null_bytes_bad_payload_handler
from ...models import DataBundle, DataServerMetadatum, TOTAL_DATA_POINT_COUNT_DATUM


class Command(BaseCommand):
    help = 'Convert unprocessed DataBundle instances into DataPoint instances.'

    def add_arguments(self, parser):
        parser.add_argument('--delete',
                            action='store_true',
                            dest='delete',
                            default=False,
                            help='Delete data bundles after processing')

        parser.add_argument('--count',
                            type=int,
                            dest='bundle_count',
                            default=50,
                            help='Number of bundles to process in a single run')

        parser.add_argument('--skip-stats',
                            action='store_true',
                            dest='skip_stats',
                            default=False,
                            help='Skips statistic updates for improved speeds')

    @handle_named_lock(lock_name='pdk_process_bundles')
    @log_scheduled_event
    def handle(self, *args, **options):  # pylint: disable=too-many-branches
        bundles = DataBundle.objects.filter(processed=False, errored=None)[:options.get('bundle_count', 50)]

        points_processed = 0
        bundles_processed = 0
        
        for bundle in bundles:
            bundle_points = bundle.process(delete_on_success=options.get('delete', False))

            points_processed += bundle_points

            if points_processed >= DataBundle.objects.process_points_limit():
                break

            bundles_processed += 1

        elapsed = (timezone.now() - core.start_processing).total_seconds()

        if core.processed_bundle_count > 0:
            logging.debug('PROCESSED: %d -- %.3f -- %.3f (%s / %s)', core.processed_bundle_count, elapsed, (elapsed / core.processed_bundle_count), core.new_point_count, core.bundle_size)
        else:
            logging.debug('PROCESSED: %d -- %.3f -- %.3f (%s / %s)', core.processed_bundle_count, elapsed, 0, core.new_point_count, core.bundle_size)

        core.flush_remote_points()
        core.delete_processed_bundles()

        if options['skip_stats'] is False:
            core.update_stats()
        else:
            DataServerMetadatum.objects.filter(key=TOTAL_DATA_POINT_COUNT_DATUM).delete()