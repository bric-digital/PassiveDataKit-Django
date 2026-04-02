# pylint: disable=no-member,line-too-long

from __future__ import print_function

from builtins import str # pylint: disable=redefined-builtin

import gzip
import json
import logging
import traceback

from multiprocessing.pool import ThreadPool

import humanize

from django.core.management.base import BaseCommand
from django.db import DataError
from django.db.transaction import TransactionManagementError
from django.utils import timezone

from ...decorators import handle_lock, log_scheduled_event
from ...bundle_processing import BundleProcessingCore, BundleProcessingHalt, \
                                 StopProcessingCurrentBundle, new_bundle_trace_id, \
                                 record_bundle_deleted, record_bundle_processing_trace
from ...models import DataBundle, DataPoint, DataServerMetadatum, TOTAL_DATA_POINT_COUNT_DATUM


def save_points(to_record, has_bundles, bundle_files, bundle, bundle_trace_id):
    try:
        points = DataPoint.objects.bulk_create(to_record)

        for point in points:
            record_bundle_processing_trace(bundle, bundle_trace_id, 'data_point_created', data_point_id=point.pk)

            if has_bundles:
                point.fetch_bundle_files(bundle_files)

        return True

    except DataError:
        for point in to_record:
            try:
                point.save()
                record_bundle_processing_trace(bundle, bundle_trace_id, 'data_point_created', data_point_id=point.pk)

                point.fetch_bundle_files(bundle_files)
            except: # pylint: disable=bare-except
                traceback.print_exc()

                if bundle.errored is not None:
                    logging.critical('Marking errored %s.', bundle.pk)

                    bundle = DataBundle.objects.get(pk=bundle.pk)
                    bundle.processed = False
                    bundle.errored = timezone.now()
                    bundle.save()
                    record_bundle_processing_trace(bundle, bundle_trace_id, 'errored', error_class='DataError')

        return False
    except: # pylint: disable=bare-except
        traceback.print_exc()

        logging.critical('Marking errored %s.', bundle.pk)

        bundle = DataBundle.objects.get(pk=bundle.pk)
        bundle.processed = False
        bundle.errored = timezone.now()
        bundle.save()
        record_bundle_processing_trace(bundle, bundle_trace_id, 'errored', error_class='Exception')

        return False


def multiprocessing_bad_payload_handler(bundle_point, bundle):
    if bundle_point is not None:
        point_json = json.dumps(bundle_point)
        point_json = point_json.encode('utf-16', 'surrogatepass').decode('utf-16')

        try:
            bundle_point = json.loads(point_json)
        except json.decoder.JSONDecodeError:
            bundle = DataBundle.objects.get(pk=bundle.pk)
            bundle.processed = False
            bundle.errored = timezone.now()
            bundle.save()

            raise StopProcessingCurrentBundle()

    return bundle_point


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

    @handle_lock
    @log_scheduled_event
    def handle(self, *args, **options):
        core = BundleProcessingCore.from_settings()
        pool = ThreadPool(processes=1)
        pending_processed_updates = []

        bundle_pks = DataBundle.objects.filter(processed=False, errored=None).order_by('-pk')[:options['bundle_count']].values_list('pk', flat=True)

        for bundle_pk in bundle_pks:
            if core.new_point_count >= core.process_limit:
                break

            bundle = DataBundle.objects.get(pk=bundle_pk)
            core.processed_bundle_count += 1
            bundle_trace_id = new_bundle_trace_id()

            try:
                result = core.process_bundle(bundle, bundle_trace_id, multiprocessing_bad_payload_handler)

                if len(result.to_record) > 0: # pylint: disable=len-as-condition
                    save_result = pool.apply_async(
                        save_points,
                        [result.to_record, result.has_bundles, result.bundle_files, bundle, bundle_trace_id],
                    )

                    for point in result.to_record:
                        core.record_created_point(point)
                else:
                    save_result = None

                bundle.properties = result.original_properties
                bundle.save()

                if result.mark_processed:
                    if save_result is None:
                        bundle = DataBundle.objects.get(pk=bundle.pk)
                        bundle.processed = True
                        bundle.save()
                        record_bundle_processing_trace(bundle, bundle_trace_id, 'processed')

                        if options['delete']:
                            record_bundle_deleted(bundle, bundle_trace_id)
                            core.to_delete.append(bundle)
                    else:
                        pending_processed_updates.append({
                            'bundle_pk': bundle.pk,
                            'bundle_trace_id': bundle_trace_id,
                            'delete_bundle': options['delete'],
                            'save_result': save_result,
                        })
            except BundleProcessingHalt:
                break
            except TransactionManagementError:
                logging.critical('Abandoning and marking errored %s.', bundle.pk)
                core.mark_bundle_errored(bundle.pk, bundle_trace_id, 'TransactionManagementError')
            except gzip.BadGzipFile:
                logging.critical('Bad GZip payload and marking errored %s.', bundle.pk)
                core.mark_bundle_errored(bundle.pk, bundle_trace_id, 'BadGzipFile')

        pool.close()
        pool.join()

        for pending_update in pending_processed_updates:
            if pending_update['save_result'].get():
                bundle = DataBundle.objects.get(pk=pending_update['bundle_pk'])

                if bundle.errored is None:
                    bundle.processed = True
                    bundle.save()
                    record_bundle_processing_trace(bundle, pending_update['bundle_trace_id'], 'processed')

                    if pending_update['delete_bundle']:
                        record_bundle_deleted(bundle, pending_update['bundle_trace_id'])
                        core.to_delete.append(bundle)

        elapsed = (timezone.now() - core.start_processing).total_seconds()

        logging.info(
            'Bundle Ingestion Summary: %d bundles, %.3f sec. elapsed, %.3f bundle/s, %s points added, %.3f MB, %.3f MB/s',
            core.processed_bundle_count,
            elapsed,
            (core.processed_bundle_count / elapsed),
            humanize.intcomma(core.new_point_count),
            core.bundle_size / (1024 * 1024),
            ((core.bundle_size / (1024 * 1024)) / elapsed),
        )

        core.flush_remote_points()
        core.delete_processed_bundles()

        if options['skip_stats'] is False:
            core.update_stats()
        else:
            DataServerMetadatum.objects.filter(key=TOTAL_DATA_POINT_COUNT_DATUM).delete()
