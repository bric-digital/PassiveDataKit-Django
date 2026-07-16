# pylint: disable=no-member,line-too-long

from __future__ import print_function

from builtins import str # pylint: disable=redefined-builtin
import logging

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.transaction import TransactionManagementError
from django.utils import timezone

from ...db_locks import handle_bundle_processing_lock
from ...decorators import log_scheduled_event
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

    @handle_bundle_processing_lock
    @log_scheduled_event
    def handle(self, *args, **options):  # pylint: disable=too-many-branches
        core = BundleProcessingCore.from_settings()
        bundles = DataBundle.objects.filter(processed=False, errored=None)[:options['bundle_count']]
        remote_upload_failed = False

        for bundle in bundles:
            if core.new_point_count >= core.process_limit:
                break

            core.processed_bundle_count += 1
            bundle_trace_id = new_bundle_trace_id()

            try:
                with transaction.atomic():
                    result = core.process_bundle(bundle, bundle_trace_id, strip_null_bytes_bad_payload_handler)

                    if result.mark_processed is False:
                        bundle.properties = result.original_properties
                        bundle.save()
                        remote_upload_failed = True
                        break

                    if len(result.to_record) > 0: # pylint: disable=len-as-condition
                        points = save_serial_points(
                            result.to_record,
                            result.has_bundles,
                            result.bundle_files,
                            bundle,
                            bundle_trace_id,
                            persistence_adapter=core.persistence_adapter,
                        )

                        for point in points:
                            core.record_created_point(point)

                    bundle.processed = True
                    record_bundle_processing_trace(
                        bundle,
                        bundle_trace_id,
                        'processed',
                        properties=bundle.properties,
                        persistence_adapter=core.persistence_adapter,
                    )

                    bundle.properties = result.original_properties
                    bundle.save()

                    if options['delete']:
                        record_bundle_deleted(
                            bundle,
                            bundle_trace_id,
                            persistence_adapter=core.persistence_adapter,
                        )
                        core.to_delete.append(bundle)
            except BundleProcessingHalt:
                break
            except TransactionManagementError:
                print('[TransactionManagementError] Abandoning and marking errored ' + str(bundle.pk) + '.')
                core.mark_bundle_errored(bundle.pk, bundle_trace_id, 'TransactionManagementError')
            except TypeError:
                print('[TypeError] Abandoning and marking errored ' + str(bundle.pk) + '.')
                core.mark_bundle_errored(bundle.pk, bundle_trace_id, 'TypeError')

        elapsed = (timezone.now() - core.start_processing).total_seconds()

        if core.processed_bundle_count > 0:
            logging.debug('PROCESSED: %d -- %.3f -- %.3f (%s / %s)', core.processed_bundle_count, elapsed, (elapsed / core.processed_bundle_count), core.new_point_count, core.bundle_size)
        else:
            logging.debug('PROCESSED: %d -- %.3f -- %.3f (%s / %s)', core.processed_bundle_count, elapsed, 0, core.new_point_count, core.bundle_size)

        if remote_upload_failed is False:
            core.flush_remote_points()
        core.delete_processed_bundles()

        if options['skip_stats'] is False:
            core.update_stats()
        else:
            DataServerMetadatum.objects.filter(key=TOTAL_DATA_POINT_COUNT_DATUM).delete()
