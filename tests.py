# pylint: disable=no-member, invalid-name, line-too-long

import calendar
import json

from django.test import TestCase
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from passive_data_kit.access_requests import build_django_user_identifier, \
                                             build_token_identifier, \
                                             format_user_identifier, \
                                             parse_user_identifier, \
                                             USER_IDENTIFIER_KIND_API_TOKEN, \
                                             USER_IDENTIFIER_KIND_DJANGO_USER

from passive_data_kit.bundle_processing import record_bundle_processing_trace, save_serial_points
from passive_data_kit.models import DataBundle, DataBundleProcessingTrace, DataFile, DataPoint, install_supports_jsonfield

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

        saved_points = save_serial_points(points, False, None, bundle, 'trace-id')

        self.assertEqual(len(saved_points), 2)
        self.assertEqual(DataPoint.objects.count(), 2)
        self.assertEqual(DataBundleProcessingTrace.objects.filter(status='data_point_created').count(), 2)
