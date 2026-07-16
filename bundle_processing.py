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
from django.utils.module_loading import import_string
from django.utils import timezone

from .models import DataBundle, DataBundleProcessingTrace, DataPoint, DataServerMetadatum, DataSource, \
                    SOURCE_GENERATORS_DATUM, SOURCES_DATUM, TOTAL_DATA_POINT_COUNT_DATUM, \
                    install_supports_jsonfield


BUNDLE_POINT_STAGE_NORMALIZED = 'normalized'
BUNDLE_POINT_STAGE_PREPARED = 'prepared'


def new_bundle_trace_id():
    return str(uuid.uuid4())


def bundle_summary(bundle, properties, bundle_trace_id):
    point_count = 0
    sources = set()
    generators = set()

    if isinstance(properties, list):
        point_count = len(properties)

        for point in properties:
            if isinstance(point, dict) and 'passive-data-metadata' in point:
                metadata = point['passive-data-metadata']

                source = metadata.get('source')
                generator = metadata.get('generator')

                if source:
                    sources.add(source)

                if generator:
                    generators.add(generator)

    return {
        'bundle_trace_id': bundle_trace_id,
        'bundle_id': bundle.pk,
        'encrypted': bundle.encrypted,
        'compression': bundle.compression,
        'point_count': point_count,
        'source_count': len(sources),
        'generator_count': len(generators),
    }


def bundle_log_fields(bundle, properties, bundle_trace_id):
    summary = bundle_summary(bundle, properties, bundle_trace_id)

    return (
        summary['bundle_trace_id'],
        summary['bundle_id'],
        summary['encrypted'],
        summary['compression'],
        summary['point_count'],
        summary['source_count'],
        summary['generator_count'],
    )


def attach_trace_context(bundle_point, bundle, bundle_trace_id, cache=None):
    bundle_point['_pdk_trace_context'] = {
        'bundle_trace_id': bundle_trace_id,
        'bundle_id': bundle.pk,
    }

    if cache is not None:
        bundle_point['_pdk_trace_context']['cache'] = cache


def strip_null_bytes_bad_payload_handler(bundle_point, bundle):  # pylint: disable=invalid-name
    if bundle_point is not None:
        point_json = json.dumps(bundle_point)

        while r'\u0000' in point_json:
            print('Detected 0x00 byte in ' + str(bundle.pk) + '. Stripping and ingesting...')
            point_json = point_json.replace(r'\u0000', '')

        bundle_point = json.loads(point_json)

    return bundle_point


class PersistenceOperationNotSupported(RuntimeError):
    pass


class PassiveDataKitPersistenceAdapter(object):  # pylint: disable=too-few-public-methods,useless-object-inheritance
    """Persistence boundary for bundle processing.

    Implementations may use the Django database, another persistence service,
    or deliberately reject persistence. The base implementation is fail-closed
    so a partial adapter cannot silently discard writes.
    """

    def _unsupported(self, operation):
        raise PersistenceOperationNotSupported(
            '%s does not support %s.' % (self.__class__.__name__, operation)
        )

    def save_bundle_processing_trace(self, trace):  # pylint: disable=unused-argument
        self._unsupported('save_bundle_processing_trace')

    def mark_bundle_errored(self, bundle_pk, errored_at):  # pylint: disable=unused-argument
        self._unsupported('mark_bundle_errored')

    def bundle_files_for_bundle(self, bundle):  # pylint: disable=unused-argument
        self._unsupported('bundle_files_for_bundle')

    def server_url_for_source(self, source):  # pylint: disable=unused-argument
        self._unsupported('server_url_for_source')

    # pylint: disable=unused-argument,too-many-arguments,too-many-positional-arguments
    def inspect_bundle_point(self, bundle_point, bundle, bundle_trace_id, cache):
        self._unsupported('inspect_bundle_point')

    def prepare_local_point(self, point, properties, supports_json):
        self._unsupported('prepare_local_point')
    # pylint: enable=unused-argument,too-many-arguments,too-many-positional-arguments

    def capture_decoded_bundle(self, bundle, properties):  # pylint: disable=unused-argument
        """Observe a decoded bundle without requiring persistence."""

    def create_bundle_point_context(self, bundle_record_index, decoded_point):  # pylint: disable=unused-argument,no-self-use
        """Create adapter-owned context for one decoded bundle record."""
        return None

    def capture_bundle_point_stage(self, point_context, stage, bundle_point):  # pylint: disable=unused-argument
        """Observe normalization stages without copying them in the core."""

    def capture_local_point(self, point_context, point, properties):  # pylint: disable=unused-argument
        """Associate an accepted local point with adapter-owned context."""

    def delete_bundles(self, bundles):  # pylint: disable=unused-argument
        self._unsupported('delete_bundles')

    def update_stats(self, core):  # pylint: disable=unused-argument
        self._unsupported('update_stats')

    # pylint: disable=unused-argument,too-many-arguments,too-many-positional-arguments
    def save_serial_points(self, to_record, has_bundles, bundle_files, bundle, bundle_trace_id):
        self._unsupported('save_serial_points')
    # pylint: enable=unused-argument,too-many-arguments,too-many-positional-arguments

    def save_points(self, points):  # pylint: disable=unused-argument
        self._unsupported('save_points')


class DatabasePassiveDataKitPersistenceAdapter(PassiveDataKitPersistenceAdapter):
    """Compatibility adapter containing the original Django ORM behavior."""

    def save_bundle_processing_trace(self, trace):
        trace.save()
        return trace

    def mark_bundle_errored(self, bundle_pk, errored_at):
        bundle = DataBundle.objects.get(pk=bundle_pk)
        bundle.errored = errored_at
        bundle.save()
        return bundle

    def bundle_files_for_bundle(self, bundle):
        bundle_files = bundle.data_files.all()
        return bundle_files, (bundle_files.count() > 0)

    def server_url_for_source(self, source):
        server_url = ''
        source_obj = DataSource.objects.filter(identifier=source).first()

        if source_obj is not None:
            if source_obj.server is not None:
                server_url = source_obj.server.upload_url
        elif source is not None:
            source_obj = DataSource(name=source, identifier=source)
            source_obj.save()
            source_obj.join_default_group()

        return server_url

    # pylint: disable=too-many-arguments,too-many-positional-arguments
    def inspect_bundle_point(self, bundle_point, bundle, bundle_trace_id, cache):
        try:
            attach_trace_context(bundle_point, bundle, bundle_trace_id, cache)
            settings.PDK_INSPECT_DATA_POINT_AT_INGEST(bundle_point)
        except AttributeError:
            pass
    # pylint: enable=too-many-arguments,too-many-positional-arguments

    def prepare_local_point(self, point, properties, supports_json):
        if supports_json:
            point.properties = json.loads(
                json.dumps(properties, indent=2).encode('utf-16', 'surrogatepass').decode('utf-16')
            )
        else:
            point.properties = json.dumps(properties, indent=2)

        point.fetch_secondary_identifier(skip_save=True, properties=properties)
        point.fetch_user_agent(skip_save=True, properties=properties)
        point.fetch_generator_definition(skip_save=True)
        point.fetch_source_reference(skip_save=True)
        return point

    def delete_bundles(self, bundles):
        for bundle in bundles:
            bundle.delete()

    def update_stats(self, core):  # pylint: disable=too-many-locals,too-many-branches,too-many-statements
        data_point_count = DataServerMetadatum.objects.filter(key=TOTAL_DATA_POINT_COUNT_DATUM).first()

        if data_point_count is None:
            count = DataPoint.objects.all().count()
            data_point_count = DataServerMetadatum(key=TOTAL_DATA_POINT_COUNT_DATUM)
            data_point_count.value = str(count)
            data_point_count.save()
        else:
            count = int(data_point_count.value)
            count += core.new_point_count
            data_point_count.value = str(count)
            data_point_count.save()

        sources = DataServerMetadatum.objects.filter(key=SOURCES_DATUM).first()

        if sources is not None:
            updated = False
            source_list = json.loads(sources.value)

            for seen_source in core.seen_sources:
                if (seen_source in source_list) is False:
                    source_list.append(seen_source)
                    updated = True

            if updated:
                sources.value = json.dumps(source_list, indent=2)
                sources.save()

        for source, identifiers in list(core.source_identifiers.items()):
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

        for identifier in core.seen_generators:
            if (identifier in generator_ids) is False:
                generator_ids.append(identifier)
                updated = True

        if updated:
            generators_datum.value = json.dumps(generator_ids, indent=2)
            generators_datum.save()

        for latest_key, point in list(core.latest_points.items()):
            datum_key = 'latest_point--' + latest_key
            latest_datum = DataServerMetadatum.objects.filter(key=datum_key).first()

            if latest_datum is None:
                latest_datum = DataServerMetadatum(key=datum_key)

            latest_datum.value = str(point.pk)
            latest_datum.save()

    # pylint: disable=too-many-arguments,too-many-positional-arguments
    def save_serial_points(self, to_record, has_bundles, bundle_files, bundle, bundle_trace_id):
        points = DataPoint.objects.bulk_create(to_record)
        traces = []

        for point in points:
            traces.append(record_bundle_processing_trace(
                bundle,
                bundle_trace_id,
                'data_point_created',
                data_point_id=point.pk,
                save=False,
            ))

            if has_bundles:
                point.fetch_bundle_files(bundle_files)

        if traces:
            DataBundleProcessingTrace.objects.bulk_create(traces)

        return points
    # pylint: enable=too-many-arguments,too-many-positional-arguments

    def save_points(self, points):
        return DataPoint.objects.bulk_create(points)


_DEFAULT_PERSISTENCE_ADAPTER = None


def set_default_persistence_adapter(persistence_adapter):
    """Set a process-wide adapter class, factory, or dotted path.

    Passing ``None`` restores the database compatibility adapter.
    Adapter instances are worker-scoped and must be passed explicitly to a
    ``BundleProcessingCore`` or writer function; sharing one as the process
    default would leak mutable adapter state between concurrent workers.
    """
    global _DEFAULT_PERSISTENCE_ADAPTER  # pylint: disable=global-statement

    if isinstance(persistence_adapter, PassiveDataKitPersistenceAdapter):
        raise TypeError(
            'Default bundle persistence adapter must be a class, factory, or dotted path; '
            'pass adapter instances explicitly to a worker core.'
        )

    _DEFAULT_PERSISTENCE_ADAPTER = (
        DatabasePassiveDataKitPersistenceAdapter
        if persistence_adapter is None
        else persistence_adapter
    )


def _instantiate_persistence_adapter(persistence_adapter, allow_instance=True):
    if isinstance(persistence_adapter, six.string_types):
        persistence_adapter = import_string(persistence_adapter)

    if isinstance(persistence_adapter, PassiveDataKitPersistenceAdapter):
        if allow_instance:
            return persistence_adapter

        raise TypeError(
            'Configured bundle persistence adapter must create a new adapter per worker.'
        )

    if callable(persistence_adapter):
        persistence_adapter = persistence_adapter()

    if isinstance(persistence_adapter, PassiveDataKitPersistenceAdapter) is False:
        raise TypeError('Bundle persistence adapter must extend PassiveDataKitPersistenceAdapter.')

    return persistence_adapter


def get_default_persistence_adapter():
    persistence_adapter = getattr(
        settings,
        'PDK_BUNDLE_PROCESSING_PERSISTENCE_ADAPTER',
        _DEFAULT_PERSISTENCE_ADAPTER,
    )

    if persistence_adapter is None:
        persistence_adapter = DatabasePassiveDataKitPersistenceAdapter

    return _instantiate_persistence_adapter(persistence_adapter, allow_instance=False)


def resolve_persistence_adapter(persistence_adapter=None):
    if persistence_adapter is None:
        return get_default_persistence_adapter()

    return _instantiate_persistence_adapter(persistence_adapter)


# Keep the explicit signature to avoid introducing a needless compatibility
# wrapper structure. Once Python 2 support is dropped, make the optional
# context keyword-only instead of allowing additional positional arguments.
def record_bundle_processing_trace(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        bundle, bundle_trace_id, status, properties=None, data_point_id=None, error_class=None, save=True,
        persistence_adapter=None):
    point_count = None

    if isinstance(properties, list):
        point_count = len(properties)

    trace = DataBundleProcessingTrace(
        bundle_id=bundle.pk,
        bundle_trace_id=bundle_trace_id,
        data_point_id=data_point_id,
        status=status,
        bundle_recorded=bundle.recorded,
        point_count=point_count,
        encrypted=bundle.encrypted,
        compression=bundle.compression,
        error_class=error_class,
    )

    if save:
        resolve_persistence_adapter(persistence_adapter).save_bundle_processing_trace(trace)

    return trace


def record_bundle_deleted(bundle, bundle_trace_id, persistence_adapter=None):
    record_bundle_processing_trace(
        bundle,
        bundle_trace_id,
        'deleted',
        persistence_adapter=persistence_adapter,
    )


class BundleProcessingHalt(Exception):
    pass


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
    # pylint: disable=too-many-arguments,too-many-positional-arguments
    def __init__(self, supports_json, default_tz, process_limit, remote_bundle_size, remote_timeout,
                 persistence_adapter=None):
        self.supports_json = supports_json
        self.default_tz = default_tz
        self.process_limit = process_limit
        self.remote_bundle_size = remote_bundle_size
        self.remote_timeout = remote_timeout
        self.persistence_adapter = resolve_persistence_adapter(persistence_adapter)

        self.seen_sources = []
        self.seen_generators = []
        self.source_identifiers = {}
        self.latest_points = {}

        self.sources = {}
        self.xmit_points = {}
        self.trace_context_cache = {}

        self.private_key = None
        self.public_key = None

        self.to_delete = []
        self.new_point_count = 0
        self.processed_bundle_count = 0
        self.bundle_size = 0
        self.start_processing = timezone.now()
    # pylint: enable=too-many-arguments,too-many-positional-arguments

    @classmethod
    def from_settings(cls, persistence_adapter=None, supports_json=None):
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

        if supports_json is None:
            supports_json = install_supports_jsonfield()

        return cls(
            supports_json=supports_json,
            default_tz=timezone.get_default_timezone(),
            process_limit=process_limit,
            remote_bundle_size=remote_bundle_size,
            remote_timeout=remote_timeout,
            persistence_adapter=persistence_adapter,
        )

    def mark_bundle_errored(self, bundle_pk, bundle_trace_id, error_class):
        bundle = self.persistence_adapter.mark_bundle_errored(bundle_pk, timezone.now())

        record_bundle_processing_trace(
            bundle,
            bundle_trace_id,
            'errored',
            error_class=error_class,
            persistence_adapter=self.persistence_adapter,
        )

    def decode_bundle_properties(self, bundle):
        if self.supports_json is False:
            bundle.properties = json.loads(bundle.properties)

        if bundle.encrypted:
            if 'nonce' in bundle.properties and 'encrypted' in bundle.properties:
                payload = base64.b64decode(bundle.properties['encrypted'])
                nonce = base64.b64decode(bundle.properties['nonce'])

                if self.private_key is None:
                    self.private_key = PrivateKey(base64.b64decode(settings.PDK_SERVER_KEY).strip()) # pylint: disable=line-too-long

                if self.public_key is None:
                    self.public_key = PublicKey(base64.b64decode(settings.PDK_CLIENT_KEY).strip()) # pylint: disable=line-too-long

                box = Box(self.private_key, self.public_key)
                decrypted_message = box.decrypt(payload, nonce)
                decrypted = six.text_type(decrypted_message, encoding='utf8')

                if bundle.compression != 'none':
                    compressed = base64.b64decode(decrypted)

                    if bundle.compression == 'gzip':
                        fio = BytesIO(compressed)
                        gzip_file_obj = gzip.GzipFile(fileobj=fio)
                        payload = gzip_file_obj.read()
                        gzip_file_obj.close()

                        decrypted = payload

                bundle.properties = json.loads(decrypted)
            elif 'encrypted' in bundle.properties:
                print('Missing "nonce" in encrypted bundle. Cannot decrypt bundle ' + str(bundle.pk) + '. Skipping...')
                # Preserve current malformed-encrypted behavior for now: stop
                # processing additional bundles without marking this one errored.
                raise BundleProcessingHalt()
            elif 'nonce' in bundle.properties:
                print('Missing "encrypted" in encrypted bundle. Cannot decrypt bundle ' + str(bundle.pk) + '. Skipping...')
                raise BundleProcessingHalt()
        elif bundle.compression != 'none':
            compressed = base64.b64decode(bundle.properties['payload'])

            if bundle.compression == 'gzip':
                fio = BytesIO(compressed)
                gzip_file_obj = gzip.GzipFile(fileobj=fio)
                payload = gzip_file_obj.read()
                gzip_file_obj.close()

                self.bundle_size += len(payload)

                bundle.properties = json.loads(payload)

        return bundle.properties

    @staticmethod
    def is_ingestable_point(bundle_point):
        return bundle_point is not None and 'passive-data-metadata' in bundle_point and \
               'source' in bundle_point['passive-data-metadata'] and \
               'generator' in bundle_point['passive-data-metadata']

    def prepare_bundle_point(self, bundle_point, bundle, bundle_trace_id):
        source = bundle_point['passive-data-metadata']['source']

        if source == '':
            source = 'missing-source'

        try:
            source = settings.PDK_RENAME_SOURCE(source)
            bundle_point['passive-data-metadata']['source'] = source
        except AttributeError:
            pass

        self.persistence_adapter.inspect_bundle_point(
            bundle_point,
            bundle,
            bundle_trace_id,
            self.trace_context_cache,
        )

        return bundle_point

    def server_url_for_source(self, source):
        if source in self.sources:
            return self.sources[source]

        server_url = self.persistence_adapter.server_url_for_source(source)

        self.sources[source] = server_url

        return server_url

    def build_local_point(self, bundle_point, now, bundle, point_context=None):
        point = DataPoint(recorded=now)
        bundle_point['passive-data-metadata']['encrypted_transmission'] = bundle.encrypted

        point.source = bundle_point['passive-data-metadata']['source']

        if point.source is None:
            point.source = '-'

        point.generator = bundle_point['passive-data-metadata']['generator']

        if 'generator-id' in bundle_point['passive-data-metadata']:
            point.generator_identifier = bundle_point['passive-data-metadata']['generator-id']

        if 'latitude' in bundle_point['passive-data-metadata'] and 'longitude' in bundle_point['passive-data-metadata']:
            point.generated_at = GEOSGeometry('POINT(' + str(bundle_point['passive-data-metadata']['longitude']) + ' ' + str(bundle_point['passive-data-metadata']['latitude']) + ')')
        elif 'latitude' in bundle_point and 'longitude' in bundle_point:
            point.generated_at = GEOSGeometry('POINT(' + str(bundle_point['longitude']) + ' ' + str(bundle_point['latitude']) + ')')

        point.created = datetime.datetime.fromtimestamp(bundle_point['passive-data-metadata']['timestamp'], tz=self.default_tz)

        point = self.persistence_adapter.prepare_local_point(
            point,
            bundle_point,
            self.supports_json,
        )
        self.persistence_adapter.capture_local_point(point_context, point, bundle_point)
        return point

    def queue_remote_point(self, server_url, bundle_point):
        if (server_url in self.xmit_points) is False:
            self.xmit_points[server_url] = []

        self.xmit_points[server_url].append(bundle_point)

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
        # A source bundle is the durable retry record for its remote points.
        # Deferring a small tail here would allow callers to mark that bundle
        # processed before the later flush had a result.
        if self.flush_remote_points():
            return True

        logging.critical(
            'Error encountered uploading contents of trace_id=%s bundle_id=%s encrypted=%s compression=%s point_count=%s source_count=%s generator_count=%s',
            *bundle_log_fields(bundle, bundle.properties, bundle_trace_id)
        )
        record_bundle_processing_trace(
            bundle,
            bundle_trace_id,
            'upload_failed',
            properties=bundle.properties,
            persistence_adapter=self.persistence_adapter,
        )

        return False

    def process_bundle(self, bundle, bundle_trace_id, bad_payload_handler,
                       evaluate_remote_uploads=True): # pylint: disable=too-many-locals,too-many-branches,too-many-statements
        original_properties = bundle.properties
        bundle_files, has_bundles = self.persistence_adapter.bundle_files_for_bundle(bundle)

        bundle.properties = self.decode_bundle_properties(bundle)
        self.persistence_adapter.capture_decoded_bundle(bundle, bundle.properties)

        logging.info(
            'Processing bundle trace_id=%s bundle_id=%s encrypted=%s compression=%s point_count=%s source_count=%s generator_count=%s',
            *bundle_log_fields(bundle, bundle.properties, bundle_trace_id)
        )
        record_bundle_processing_trace(
            bundle,
            bundle_trace_id,
            'started',
            properties=bundle.properties,
            persistence_adapter=self.persistence_adapter,
        )

        now = timezone.now()
        to_record = []

        for bundle_record_index, bundle_point in enumerate(bundle.properties):
            point_context = self.persistence_adapter.create_bundle_point_context(
                bundle_record_index,
                bundle_point,
            )

            try:
                bundle_point = bad_payload_handler(bundle_point, bundle)
            except StopProcessingCurrentBundle:
                break

            try:
                if self.is_ingestable_point(bundle_point):
                    self.persistence_adapter.capture_bundle_point_stage(
                        point_context,
                        BUNDLE_POINT_STAGE_NORMALIZED,
                        bundle_point,
                    )
                    bundle_point = self.prepare_bundle_point(bundle_point, bundle, bundle_trace_id)
                    self.persistence_adapter.capture_bundle_point_stage(
                        point_context,
                        BUNDLE_POINT_STAGE_PREPARED,
                        bundle_point,
                    )
                    server_url = self.server_url_for_source(bundle_point['passive-data-metadata']['source'])

                    if server_url == '':
                        point = self.build_local_point(
                            bundle_point,
                            now,
                            bundle,
                            point_context=point_context,
                        )
                        to_record.append(point)
                    else:
                        self.queue_remote_point(server_url, bundle_point)

                    self.new_point_count += 1
            except DataError:
                traceback.print_exc()
                logging.debug('Error ingesting bundle: %s:', bundle.pk)
                logging.debug(str(bundle.properties))
                logging.critical(
                    'Error ingesting bundle trace_id=%s bundle_id=%s encrypted=%s compression=%s point_count=%s source_count=%s generator_count=%s',
                    *bundle_log_fields(bundle, bundle.properties, bundle_trace_id)
                )
                record_bundle_processing_trace(
                    bundle,
                    bundle_trace_id,
                    'errored',
                    properties=bundle.properties,
                    error_class='DataError',
                    persistence_adapter=self.persistence_adapter,
                )

        return BundleProcessResult(
            original_properties=original_properties,
            bundle_files=bundle_files,
            has_bundles=has_bundles,
            to_record=to_record,
            mark_processed=(
                self.evaluate_remote_uploads(bundle, bundle_trace_id)
                if evaluate_remote_uploads
                else True
            ),
        )

    def flush_remote_points(self):
        """Send all pending points, retaining every batch that does not receive 2xx."""
        failed = False

        for server_url, points in self.xmit_points.items():
            if points:
                payload = {
                    'payload': json.dumps(points, indent=2)
                }

                try:
                    bundle_post = requests.post(server_url, data=payload, timeout=self.remote_timeout)

                    if bundle_post.status_code < 200 or bundle_post.status_code >= 300:
                        failed = True
                        continue

                    self.xmit_points[server_url] = []
                except requests.exceptions.RequestException:
                    logging.exception(
                        'Unable to transmit data to %s (timeout=%s).',
                        server_url,
                        self.remote_timeout,
                    )
                    failed = True

        return failed is False

    def delete_processed_bundles(self):
        self.persistence_adapter.delete_bundles(self.to_delete)

    def update_stats(self):
        self.persistence_adapter.update_stats(self)


# pylint: disable=too-many-arguments,too-many-positional-arguments
def save_serial_points(to_record, has_bundles, bundle_files, bundle, bundle_trace_id, persistence_adapter=None):
    return resolve_persistence_adapter(persistence_adapter).save_serial_points(
        to_record,
        has_bundles,
        bundle_files,
        bundle,
        bundle_trace_id,
    )
# pylint: enable=too-many-arguments,too-many-positional-arguments


def save_points(points, persistence_adapter=None):
    return resolve_persistence_adapter(persistence_adapter).save_points(points)
