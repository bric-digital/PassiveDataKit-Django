from django.test import TestCase
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile

from passive_data_kit.access_requests import build_django_user_identifier, \
                                             build_token_identifier, \
                                             format_user_identifier, \
                                             parse_user_identifier, \
                                             USER_IDENTIFIER_KIND_API_TOKEN, \
                                             USER_IDENTIFIER_KIND_DJANGO_USER
from passive_data_kit.models import DataBundle, DataFile

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
