# pylint: disable=no-member, invalid-name, line-too-long

import calendar
import json
import threading

from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from passive_data_kit.access_requests import build_django_user_identifier, \
                                             build_token_identifier, \
                                             format_user_identifier, \
                                             parse_user_identifier, \
                                             USER_IDENTIFIER_KIND_API_TOKEN, \
                                             USER_IDENTIFIER_KIND_DJANGO_USER

from passive_data_kit.bundle_processing import BundleProcessingCore, \
                                               DatabasePassiveDataKitPersistenceAdapter, \
                                               get_default_persistence_adapter, \
                                               PassiveDataKitPersistenceAdapter, \
                                               PersistenceOperationNotSupported, \
                                               record_bundle_processing_trace, save_points, save_serial_points, \
                                               set_default_persistence_adapter
from passive_data_kit.models import DataBundle, DataBundleProcessingTrace, DataFile, DataPoint, install_supports_jsonfield


def recording_ingest_inspector(bundle_point):
    bundle_point['inspected'] = True


class RecordingPersistenceAdapter(PassiveDataKitPersistenceAdapter):
    def __init__(self):
        self.saved_traces = []
        self.saved_point_batches = []

    def save_bundle_processing_trace(self, trace):
        self.saved_traces.append(trace)
        return trace

    # pylint: disable=too-many-arguments,too-many-positional-arguments
    def save_serial_points(self, to_record, has_bundles, bundle_files, bundle, bundle_trace_id):
        self.saved_point_batches.append({
            'to_record': to_record,
            'has_bundles': has_bundles,
            'bundle_files': bundle_files,
            'bundle': bundle,
            'bundle_trace_id': bundle_trace_id,
        })
        return to_record
    # pylint: enable=too-many-arguments,too-many-positional-arguments

    def save_points(self, points):
        self.saved_point_batches.append({'to_record': points})
        return points


class TestBasicsTestCase(TestCase):
    def setUp(self):
        pass

    def test_tests_working(self):
        self.assertNotEqual('foo', 'bar')


class AccessRequestIdentifiersTestCase(TestCase):
    def test_django_user_identifier(self):
        user = get_user_model().objects.create_user(username='saml:entra-object-id')

        identifier = build_django_user_identifier(user)
        parsed = parse_user_identifier(identifier)

        self.assertEqual(parsed['kind'], USER_IDENTIFIER_KIND_DJANGO_USER)
        self.assertEqual(parsed['user_pk'], user.pk)
        self.assertEqual(parsed['username'], 'saml:entra-object-id')
        self.assertEqual(format_user_identifier(identifier), '#%s saml:entra-object-id' % user.pk)

    def test_api_token_identifier(self):
        identifier = build_token_identifier('example-token')
        parsed = parse_user_identifier(identifier)

        self.assertEqual(parsed['kind'], USER_IDENTIFIER_KIND_API_TOKEN)
        self.assertEqual(parsed['token'], 'example-token')
        self.assertEqual(format_user_identifier(identifier), 'api_token example-token')

    def test_parse_legacy_user_id(self):
        parsed = parse_user_identifier('42: saml:entra-object-id')

        self.assertEqual(parsed['kind'], USER_IDENTIFIER_KIND_DJANGO_USER)
        self.assertEqual(parsed['user_pk'], 42)
        self.assertEqual(parsed['username'], 'saml:entra-object-id')

    def test_parse_legacy_token_id(self):
        parsed = parse_user_identifier('api_token: example-token')

        self.assertEqual(parsed['kind'], USER_IDENTIFIER_KIND_API_TOKEN)
        self.assertEqual(parsed['token'], 'example-token')


class BundleUploadTests(TestCase):
    def test_add_bundle_uploads_data_file(self):
        data_file = SimpleUploadedFile(
            'example.txt',
            b'example file contents',
            content_type='text/plain',
        )

        response = self.client.post('/data/add-bundle.json', {
            'payload': '[]',
            'attachment': data_file,
        })

        self.assertEqual(response.status_code, 201)
        self.assertEqual(DataBundle.objects.count(), 1)
        self.assertEqual(DataFile.objects.count(), 1)
        self.assertEqual(DataFile.objects.first().identifier, 'attachment')


class BundleProcessingTraceTests(TestCase):
    def create_bundle(self): # pylint: disable=no-self-use
        properties = []

        if install_supports_jsonfield() is False:
            properties = json.dumps(properties)

        return DataBundle.objects.create(
            recorded=timezone.now(),
            properties=properties,
        )

    def create_point(self, source, generator_identifier): # pylint: disable=no-self-use
        now = timezone.now()
        metadata = {
            'source': source,
            'generator': generator_identifier + ': test',
            'generator-id': generator_identifier,
            'timestamp': calendar.timegm(now.utctimetuple()),
        }
        properties = {
            'passive-data-metadata': metadata,
        }

        if install_supports_jsonfield() is False:
            properties = json.dumps(properties)

        return DataPoint(
            source=source,
            generator=metadata['generator'],
            generator_identifier=generator_identifier,
            created=now,
            recorded=now,
            properties=properties,
        )

    def test_record_bundle_processing_trace_can_return_unsaved_trace(self):
        bundle = self.create_bundle()

        trace = record_bundle_processing_trace(
            bundle,
            'trace-id',
            'data_point_created',
            data_point_id=123,
            save=False,
        )

        self.assertIsNone(trace.pk)
        self.assertEqual(DataBundleProcessingTrace.objects.count(), 0)

    def test_save_serial_points_records_data_point_traces(self):
        bundle = self.create_bundle()
        points = [
            self.create_point('source-1', 'generator-1'),
            self.create_point('source-2', 'generator-2'),
        ]

        with CaptureQueriesContext(connection) as queries:
            saved_points = save_serial_points(points, False, None, bundle, 'trace-id')

        self.assertEqual(len(saved_points), 2)
        self.assertEqual(DataPoint.objects.count(), 2)
        self.assertEqual(DataBundleProcessingTrace.objects.filter(status='data_point_created').count(), 2)
        insert_queries = [query['sql'] for query in queries if query['sql'].lstrip().upper().startswith('INSERT')]
        self.assertEqual(len(insert_queries), 2)
        self.assertTrue(any('passive_data_kit_datapoint' in query.lower() for query in insert_queries))
        self.assertTrue(any('passive_data_kit_databundleprocessingtrace' in query.lower() for query in insert_queries))

    def test_save_points_bulk_inserts_a_batch(self):
        points = [
            self.create_point('source-1', 'generator-1'),
            self.create_point('source-2', 'generator-2'),
        ]

        with CaptureQueriesContext(connection) as queries:
            saved_points = save_points(points)

        insert_queries = [query['sql'] for query in queries if query['sql'].lstrip().upper().startswith('INSERT')]
        self.assertEqual(len(saved_points), 2)
        self.assertEqual(len(insert_queries), 1)
        self.assertIn('passive_data_kit_datapoint', insert_queries[0].lower())


class BundlePersistenceAdapterTests(TestCase):
    def tearDown(self):
        set_default_persistence_adapter(None)

    def test_database_adapter_is_the_compatibility_default(self):
        self.assertIsInstance(
            get_default_persistence_adapter(),
            DatabasePassiveDataKitPersistenceAdapter,
        )

    @override_settings(PDK_BUNDLE_PROCESSING_PERSISTENCE_ADAPTER=None)
    def test_none_django_setting_uses_the_database_compatibility_default(self):
        self.assertIsInstance(
            get_default_persistence_adapter(),
            DatabasePassiveDataKitPersistenceAdapter,
        )

    def test_base_adapter_fails_closed_for_unsupported_persistence(self):
        with self.assertRaises(PersistenceOperationNotSupported):
            PassiveDataKitPersistenceAdapter().save_points([])

    def test_setup_default_is_used_by_new_processing_cores(self):
        set_default_persistence_adapter(RecordingPersistenceAdapter)

        core = BundleProcessingCore.from_settings()

        self.assertIsInstance(core.persistence_adapter, RecordingPersistenceAdapter)

    def test_setup_default_rejects_a_shared_adapter_instance(self):
        with self.assertRaises(TypeError):
            set_default_persistence_adapter(RecordingPersistenceAdapter())

    def test_setup_default_creates_an_adapter_per_concurrent_worker(self):
        set_default_persistence_adapter(RecordingPersistenceAdapter)
        adapters = []
        adapters_lock = threading.Lock()

        def create_worker_adapter():
            adapter = BundleProcessingCore.from_settings().persistence_adapter

            with adapters_lock:
                adapters.append(adapter)

        workers = [threading.Thread(target=create_worker_adapter) for _index in range(4)]

        for worker in workers:
            worker.start()

        for worker in workers:
            worker.join()

        self.assertEqual(len(adapters), 4)
        self.assertEqual(len(set(id(adapter) for adapter in adapters)), 4)

    @override_settings(
        PDK_BUNDLE_PROCESSING_PERSISTENCE_ADAPTER='passive_data_kit.tests.RecordingPersistenceAdapter'
    )
    def test_django_setting_can_configure_the_default_adapter(self):
        self.assertIsInstance(get_default_persistence_adapter(), RecordingPersistenceAdapter)

    def test_explicit_core_adapter_overrides_the_configured_default(self):
        explicit_adapter = RecordingPersistenceAdapter()
        set_default_persistence_adapter(RecordingPersistenceAdapter)

        core = BundleProcessingCore.from_settings(persistence_adapter=explicit_adapter)

        self.assertIs(core.persistence_adapter, explicit_adapter)

    def test_explicit_json_capability_does_not_query_the_database(self):
        explicit_adapter = RecordingPersistenceAdapter()

        with CaptureQueriesContext(connection) as queries:
            core = BundleProcessingCore.from_settings(
                persistence_adapter=explicit_adapter,
                supports_json=True,
            )

        self.assertTrue(core.supports_json)
        self.assertEqual(len(queries), 0)

    @override_settings(PDK_INSPECT_DATA_POINT_AT_INGEST=recording_ingest_inspector)
    def test_database_adapter_runs_the_configured_ingest_inspector(self):
        adapter = DatabasePassiveDataKitPersistenceAdapter()
        bundle = DataBundle(recorded=timezone.now(), properties=[])
        bundle_point = {}
        cache = {}

        adapter.inspect_bundle_point(bundle_point, bundle, 'adapter-trace-id', cache)

        self.assertTrue(bundle_point['inspected'])
        self.assertEqual(
            bundle_point['_pdk_trace_context']['bundle_trace_id'],
            'adapter-trace-id',
        )
        self.assertIs(bundle_point['_pdk_trace_context']['cache'], cache)

    def test_trace_writer_accepts_an_explicit_adapter(self):
        bundle = DataBundle(recorded=timezone.now(), properties=[])
        adapter = RecordingPersistenceAdapter()

        trace = record_bundle_processing_trace(
            bundle,
            'adapter-trace-id',
            'started',
            persistence_adapter=adapter,
        )

        self.assertEqual(adapter.saved_traces, [trace])
        self.assertIsNone(trace.pk)

    def test_serial_point_writer_accepts_an_explicit_adapter(self):
        bundle = DataBundle(recorded=timezone.now(), properties=[])
        point = DataPoint(recorded=timezone.now())
        adapter = RecordingPersistenceAdapter()

        points = save_serial_points(
            [point],
            False,
            None,
            bundle,
            'adapter-trace-id',
            persistence_adapter=adapter,
        )

        self.assertEqual(points, [point])
        self.assertEqual(adapter.saved_point_batches[0]['bundle_trace_id'], 'adapter-trace-id')

    def test_point_writer_accepts_an_explicit_adapter(self):
        point = DataPoint(recorded=timezone.now())
        adapter = RecordingPersistenceAdapter()

        points = save_points([point], persistence_adapter=adapter)

        self.assertEqual(points, [point])
        self.assertEqual(adapter.saved_point_batches[0]['to_record'], [point])
