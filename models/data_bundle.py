import json
import logging

import six

from django.contrib.gis.db import models

from .data_point import DataPoint
from .data_source import DataSource
from .data_server import DataServer, BundleFederationFailure

class BundleProcessingHalt(Exception):
    pass

COMPRESSION_CHOICES = (
    ('none', 'None'),
    ('gzip', 'Gzip'),
)

class BundleProcessingHalt(Exception):
    pass

class StopProcessingCurrentBundle(Exception):
    pass

class DataBundleManager(models.Manager):
    process_limit = None

    def process_points_limit(self):
        if self.process_limit is None:
            self.process_limit = 1000
            
            try:
                self.process_limit = settings.PDK_BUNDLE_PROCESS_LIMIT
            except AttributeError:
                pass

        return self.process_limit

    def fetch_server_key(self):
        return PrivateKey(base64.b64decode(settings.PDK_SERVER_KEY).strip())

    def fetch_client_key(self):
        return PublicKey(base64.b64decode(settings.PDK_CLIENT_KEY).strip())

class DataBundle(models.Model):
    objects = DataBundleManager()

    recorded = models.DateTimeField()

    errored = models.DateTimeField(null=True, blank=True)

    properties = models.JSONField()

    processed = models.BooleanField(default=False, db_index=True)
    encrypted = models.BooleanField(default=False)
    compression = models.CharField(max_length=128, choices=COMPRESSION_CHOICES, default='none')

    metadata = models.JSONField(null=True, blank=True)

    def mark_error(self, message, bundle_trace_id, error_class):
        if self.metadata is None:
            self.metadata = {}

        self.metadata['error'] = message
        self.errored = timezone.now()
        self.save()

        record_bundle_processing_trace(self, bundle_trace_id, 'errored', error_class=error_class)

    def decode_properties(self):
        if self.encrypted:
            if 'nonce' in self.properties and 'encrypted' in self.properties:
                payload = base64.b64decode(self.properties['encrypted'])
                nonce = base64.b64decode(self.properties['nonce'])

                private_key = DataBundle.objects.fetch_server_key()
                public_key = DataBundle.objects.fetch_client_key()

                box = Box(private_key, public_key)
                decrypted_message = box.decrypt(payload, nonce)
                decrypted = six.text_type(decrypted_message, encoding='utf8')

                if self.compression != 'none':
                    compressed = base64.b64decode(decrypted)

                    if self.compression == 'gzip':
                        fio = BytesIO(compressed)
                        gzip_file_obj = gzip.GzipFile(fileobj=fio)
                        payload = gzip_file_obj.read()
                        gzip_file_obj.close()

                        decrypted = payload

                return json.loads(decrypted)
            elif 'encrypted' in bundle.properties:
                logging.error('Missing "nonce" in encrypted bundle. Cannot decrypt bundle %s. Skipping...', bundle.pk)

                self.mark_error('Unable to process. Nonce is missing.')

                raise BundleProcessingHalt(self.metadata.get('error', 'No error message available.'))
            elif 'nonce' in bundle.properties:
                logging.error('Missing "encrypted" in encrypted bundle. Cannot decrypt bundle %s. Skipping...', bundle.pk)
                
                self.mark_error('Unable to process. Encrypted payload is missing.')

                raise BundleProcessingHalt(self.metadata.get('error', 'No error message available.'))
        elif self.compression != 'none':
            compressed = base64.b64decode(self.properties['payload'])

            if self.compression == 'gzip':
                fio = BytesIO(compressed)
                gzip_file_obj = gzip.GzipFile(fileobj=fio)
                payload = gzip_file_obj.read()
                gzip_file_obj.close()

                return = json.loads(payload)

        return self.properties

    def process(self, delete_on_success=False):
        points_processed = 0

        bundle_trace_id = new_bundle_trace_id()

        bundle_payload = self.decode_properties()

        remote_points = {}

        try:
            with transaction.atomic(): # TODO: Check for memory issues on lower-spec'ed machines. Data points can be rather large.
                original_properties = self.properties
                bundle_files = self.data_files.all()
                has_files = (bundle_files.count() > 0)

                record_bundle_processing_trace(self, bundle_trace_id, 'started', properties=bundle_payload)

                now = timezone.now()
                pending_points = []

                for data_point in bundle_payload:
                    bundle_point = DataPoint.objects.clean_definition(data_point)

                    try:
                        if DataPoint.objects.is_valid_definition(data_point):
                            data_point = DataPoint.objects.prepare_definition(bundle_point)

                            DataBundleProcessingTraceManager.objects.attach_trace_context(data_point, self, bundle_trace_id)

                            server_url = DataSource.objects.url_for_identifier(bundle_point['passive-data-metadata']['source'])

                            if server_url is None:
                                point_obj = DataPoint.objects.prepare_object(data_point, now, self)

                                pending_points.append(point_obj)
                            else:
                                server_points = remote_points.get(server_url, None)

                                if server_points is None:
                                    server_points = []

                                    remote_points[server_url].append(data_point)
                    except DataError:
                        traceback.print_exc()
                        logging.debug('Error ingesting bundle: %s:', bundle.pk)
                        logging.debug(str(bundle_payload))
                        
                        logging.critical(
                            'Error ingesting bundle trace_id=%s bundle_id=%s encrypted=%s compression=%s point_count=%s source_count=%s generator_count=%s',
                            *bundle_log_fields(self, bundle_payload, bundle_trace_id)
                        )

                        record_bundle_processing_trace(bundle, bundle_trace_id, 'errored', properties=bundle_payload, error_class='DataError')

                if len(pending_points) > 0:
                    # def save_serial_points(to_record, has_bundles, bundle_files, bundle, bundle_trace_id):

                    saved_points = DataPoint.objects.bulk_create(pending_points)

                    points_processed += len(saved_points)

                    for point in saved_points:
                        record_bundle_processing_trace(self, bundle_trace_id, 'data_point_created', data_point_id=point.pk)

                        if has_bundles:
                            point.fetch_bundle_files(bundle_files)

                for server_url in remote_points.keys():
                    pending_points = remote_points.get(server_url, [])

                    points_processed += DataServer.objects.federate_points(server_url, pending_points)

                self.processed = True

                record_bundle_processing_trace(self, bundle_trace_id, 'processed', properties=bundle_payload)

                bundle.save()

                if delete_on_success:
                    record_bundle_deleted(self, bundle_trace_id)

                    self.delete()

        except BundleProcessingHalt:
            break
        except BundleFederationFailure as ex:
            logging.critical(
                'Error encountered uploading contents of trace_id=%s bundle_id=%s encrypted=%s compression=%s point_count=%s source_count=%s generator_count=%s',
                *bundle_log_fields(self, bundle_payload, bundle_trace_id)
            )
    
            self.mark_error(ex.message, bundle_trace_id, 'BundleFederationFailure')

            record_bundle_processing_trace(bundle, bundle_trace_id, 'upload_failed', properties=bundle_payload)

        except TransactionManagementError:
            message = '[TransactionManagementError] Abandoning and marking errored: %s.' % self.pk
            
            logger.error(message)
            
            self.mark_error(message, bundle_trace_id, 'TransactionManagementError')
        except TypeError:
            message = '[TypeError] Abandoning and marking errored: %s.' % self.pk

            logger.error(message)

            self.mark_error(message, bundle_trace_id, 'TransactionManagementError')

        return points_processed

class DataBundleProcessingTraceManager(models.Manager):
    is_tracing_enabled = None

    def is_enabled(self): # pylint: disable=invalid-name
        if self.is_tracing_enabled is not None:
            return self.is_tracing_enabled

        try:
            self.is_tracing_enabled = settings.BUNDLE_TRACE_PROCESSING_ENABLED
        except AttributeError:
            self.is_tracing_enabled = True

        return self.is_tracing_enabled

    def attach_trace_context(self, data_point, bundle, trace_id):
        if self.is_enabled():
            data_point['_pdk_trace_context'] = {
                'bundle_trace_id': trace_id,
                'bundle_id': bundle.pk,
            }        

class DataBundleProcessingTrace(models.Model):
    class Meta(object): # pylint: disable=old-style-class, no-init, too-few-public-methods, bad-option-value
        indexes = [
            models.Index(fields=['bundle_id', 'created']),
            models.Index(fields=['bundle_trace_id']),
            models.Index(fields=['status', 'created']),
            models.Index(fields=['data_point_id']),
        ]

        ordering = ['created', 'pk']

    objects = DataBundleProcessingTraceManager()

    bundle_id = models.BigIntegerField(db_index=True)
    bundle_trace_id = models.CharField(max_length=36, db_index=True)
    data_point_id = models.BigIntegerField(null=True, blank=True, db_index=True)
    status = models.CharField(max_length=64, db_index=True)
    bundle_recorded = models.DateTimeField(null=True, blank=True)
    point_count = models.IntegerField(null=True, blank=True)
    encrypted = models.BooleanField(default=False)
    compression = models.CharField(max_length=128, blank=True, default='')
    error_class = models.CharField(max_length=256, null=True, blank=True)
    created = models.DateTimeField(auto_now_add=True, db_index=True)


'''
# pylint: disable=no-member,line-too-long

from __future__ import print_function

from builtins import str # pylint: disable=redefined-builtin

import base64
import datetime
import gzip
import json
import logging
import traceback
import uuid

from io import BytesIO

import requests
import six

from nacl.public import PublicKey, PrivateKey, Box

from django.conf import settings
from django.contrib.gis.geos import GEOSGeometry
from django.db import DataError
from django.utils import timezone

from .models import DataBundle, DataBundleProcessingTrace, DataPoint, DataServerMetadatum, DataSource, \
                    SOURCE_GENERATORS_DATUM, SOURCES_DATUM, TOTAL_DATA_POINT_COUNT_DATUM, \
                    install_supports_jsonfield


def new_bundle_trace_id():
    }



# Keep the explicit signature to avoid introducing a needless compatibility
# wrapper structure. Once Python 2 support is dropped, make the optional
# context keyword-only instead of allowing additional positional arguments.

def record_bundle_deleted(bundle, bundle_trace_id):
    record_bundle_processing_trace(bundle, bundle_trace_id, 'deleted')




class StopProcessingCurrentBundle(Exception):
    pass


# Python 2.7 / 3.6-era jobs in the Circle matrix cannot rely on dataclasses or
# class attribute annotations here, so we keep this as a tiny compatibility
# container. That forces an explicit initializer with several fields, which is
# why the narrow Pylint suppressions live on this compatibility shim.
class BundleProcessResult(object):  # pylint: disable=too-few-public-methods,useless-object-inheritance
    def __init__(self, original_properties, bundle_files, has_bundles, to_record, mark_processed):  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self.original_properties = original_properties
        self.bundle_files = bundle_files
        self.has_bundles = has_bundles
        self.to_record = to_record
        self.mark_processed = mark_processed


class BundleProcessingCore(object):  # pylint: disable=too-many-instance-attributes,useless-object-inheritance
    def __init__(self, supports_json, default_tz, process_limit, remote_bundle_size, remote_timeout):  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self.supports_json = supports_json
        self.default_tz = default_tz
        self.process_limit = process_limit
        self.remote_bundle_size = remote_bundle_size
        self.remote_timeout = remote_timeout

        self.seen_sources = []
        self.seen_generators = []
        self.source_identifiers = {}
        self.latest_points = {}

        self.sources = {}
        self.xmit_points = {}

        self.private_key = None
        self.public_key = None

        self.to_delete = []
        self.new_point_count = 0
        self.processed_bundle_count = 0
        self.bundle_size = 0
        self.start_processing = timezone.now()

    @classmethod
    def from_settings(cls):
        process_limit = 1000
        remote_bundle_size = 100
        remote_timeout = 5

        try:
            process_limit = settings.PDK_BUNDLE_PROCESS_LIMIT
        except AttributeError:
            pass

        try:
            remote_bundle_size = settings.PDK_REMOTE_BUNDLE_SIZE
        except AttributeError:
            pass

        try:
            remote_timeout = settings.PDK_REMOTE_BUNDLE_TIMEOUT
        except AttributeError:
            pass

        return cls(
            supports_json=install_supports_jsonfield(),
            default_tz=timezone.get_default_timezone(),
            process_limit=process_limit,
            remote_bundle_size=remote_bundle_size,
            remote_timeout=remote_timeout,
        )


    def record_created_point(self, point):
        if (point.source in self.seen_sources) is False:
            self.seen_sources.append(point.source)

        if (point.source in self.source_identifiers) is False:
            self.source_identifiers[point.source] = []

        latest_key = point.source + '--' + point.generator_identifier

        if (latest_key in self.latest_points) is False or self.latest_points[latest_key].created < point.created:
            self.latest_points[latest_key] = point

        if (point.generator_identifier in self.seen_generators) is False:
            self.seen_generators.append(point.generator_identifier)

        if (point.generator_identifier in self.source_identifiers[point.source]) is False:
            self.source_identifiers[point.source].append(point.generator_identifier)

    def evaluate_remote_uploads(self, bundle, bundle_trace_id):
        if len(self.xmit_points) == 0: # pylint: disable=len-as-condition
            return True

        failed = False

        for server_url, points in self.xmit_points.items():
            if len(points) > self.remote_bundle_size:
                payload = {
                    'payload': json.dumps(points, indent=2)
                }

                try:
                    bundle_post = requests.post(server_url, data=payload, timeout=self.remote_timeout)

                    if bundle_post.status_code < 200 and bundle_post.status_code >= 300:
                        failed = True

                    self.xmit_points[server_url] = []
                except requests.exceptions.Timeout:
                    print('Unable to transmit data to ' + server_url + ' (timeout=' + str(self.remote_timeout) + ').')
                    failed = True

        if failed is False:
            return True

        logging.critical(
            'Error encountered uploading contents of trace_id=%s bundle_id=%s encrypted=%s compression=%s point_count=%s source_count=%s generator_count=%s',
            *bundle_log_fields(bundle, bundle.properties, bundle_trace_id)
        )
        record_bundle_processing_trace(bundle, bundle_trace_id, 'upload_failed', properties=bundle.properties)

        return False


    def update_stats(self):  # pylint: disable=too-many-locals,too-many-branches,too-many-statements
        data_point_count = DataServerMetadatum.objects.filter(key=TOTAL_DATA_POINT_COUNT_DATUM).first()

        if data_point_count is None:
            count = DataPoint.objects.all().count()
            data_point_count = DataServerMetadatum(key=TOTAL_DATA_POINT_COUNT_DATUM)
            data_point_count.value = str(count)
            data_point_count.save()
        else:
            count = int(data_point_count.value)
            count += self.new_point_count
            data_point_count.value = str(count)
            data_point_count.save()

        sources = DataServerMetadatum.objects.filter(key=SOURCES_DATUM).first()

        if sources is not None:
            updated = False
            source_list = json.loads(sources.value)

            for seen_source in self.seen_sources:
                if (seen_source in source_list) is False:
                    source_list.append(seen_source)
                    updated = True

            if updated:
                sources.value = json.dumps(source_list, indent=2)
                sources.save()
        else:
            DataPoint.objects.sources()

        for source, identifiers in list(self.source_identifiers.items()):
            datum_key = SOURCE_GENERATORS_DATUM + ': ' + source
            source_id_datum = DataServerMetadatum.objects.filter(key=datum_key).first()

            source_ids = []

            if source_id_datum is not None:
                source_ids = json.loads(source_id_datum.value)
            else:
                source_id_datum = DataServerMetadatum(key=datum_key)

            updated = False

            for identifier in identifiers:
                if (identifier in source_ids) is False:
                    source_ids.append(identifier)
                    updated = True

            if updated:
                source_id_datum.value = json.dumps(source_ids, indent=2)
                source_id_datum.save()

        generators_datum = DataServerMetadatum.objects.filter(key=SOURCE_GENERATORS_DATUM).first()

        generator_ids = []

        if generators_datum is not None:
            generator_ids = json.loads(generators_datum.value)
        else:
            generators_datum = DataServerMetadatum(key=SOURCE_GENERATORS_DATUM)

        updated = False

        for identifier in self.seen_generators:
            if (identifier in generator_ids) is False:
                generator_ids.append(identifier)
                updated = True

        if updated:
            generators_datum.value = json.dumps(generator_ids, indent=2)
            generators_datum.save()

        for latest_key, point in list(self.latest_points.items()):
            datum_key = 'latest_point--' + latest_key
            latest_datum = DataServerMetadatum.objects.filter(key=datum_key).first()

            if latest_datum is None:
                latest_datum = DataServerMetadatum(key=datum_key)

            latest_datum.value = str(point.pk)
            latest_datum.save()


def save_serial_points(to_record, has_bundles, bundle_files, bundle, bundle_trace_id):
    points = DataPoint.objects.bulk_create(to_record)

    for point in points:
        record_bundle_processing_trace(bundle, bundle_trace_id, 'data_point_created', data_point_id=point.pk)

        if has_bundles:
            point.fetch_bundle_files(bundle_files)

    return points
    '''