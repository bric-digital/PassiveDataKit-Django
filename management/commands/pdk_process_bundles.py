# pylint: disable=no-member,line-too-long

from __future__ import print_function

from builtins import str # pylint: disable=redefined-builtin

import base64
import datetime
import gzip
import json
import logging
import traceback

from io import BytesIO

import requests
import six

from nacl.public import PublicKey, PrivateKey, Box

from django.conf import settings
from django.contrib.gis.geos import GEOSGeometry
from django.core.management.base import BaseCommand
from django.db import transaction, DataError
from django.db.transaction import TransactionManagementError
from django.utils import timezone

from ...decorators import handle_lock, log_scheduled_event
from ...models import DataServerMetadatum, DataPoint, DataBundle, DataSource, DataSourceGroup, \
                      install_supports_jsonfield, TOTAL_DATA_POINT_COUNT_DATUM, \
                      SOURCES_DATUM, SOURCE_GENERATORS_DATUM

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
    def handle(self, *args, **options): # pylint: disable=too-many-locals, too-many-branches, too-many-statements
        to_delete = []

        supports_json = install_supports_jsonfield()

        default_tz = timezone.get_default_timezone()

        seen_sources = []
        seen_generators = []
        source_identifiers = {}

        latest_points = {}

        new_point_count = 0
        processed_bundle_count = 0
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

        sources = {}

        private_key = None
        public_key = None

        xmit_points = {}

        start_processing = timezone.now()

        bundle_size = 0

        for bundle in DataBundle.objects.filter(processed=False, errored=None)[:options['bundle_count']]: # pylint: disable=too-many-nested-blocks
            if new_point_count < process_limit:
                processed_bundle_count += 1

                original_properties = bundle.properties

                bundle_files = bundle.data_files.all()

                has_bundles = (bundle_files.count() > 0)

                try:
                    with transaction.atomic():
                        if supports_json is False:
                            bundle.properties = json.loads(bundle.properties)

                        if bundle.encrypted:
                            if 'nonce' in bundle.properties and 'encrypted' in bundle.properties:
                                payload = base64.b64decode(bundle.properties['encrypted'])
                                nonce = base64.b64decode(bundle.properties['nonce'])

                                if private_key is None:
                                    private_key = PrivateKey(base64.b64decode(settings.PDK_SERVER_KEY).strip()) # pylint: disable=line-too-long

                                if public_key is None:
                                    public_key = PublicKey(base64.b64decode(settings.PDK_CLIENT_KEY).strip()) # pylint: disable=line-too-long

                                box = Box(private_key, public_key)

                                decrypted_message = box.decrypt(payload, nonce)

                                decrypted = six.text_type(decrypted_message, encoding='utf8')

                                if bundle.compression != 'none':
                                    compressed = base64.b64decode(decrypted)

                                    if bundle.compression == 'gzip':
                                        fio = BytesIO(compressed)  # io.BytesIO for Python 3
                                        gzip_file_obj = gzip.GzipFile(fileobj=fio)
                                        payload = gzip_file_obj.read()
                                        gzip_file_obj.close()

                                        decrypted = payload

                                bundle.properties = json.loads(decrypted)
                            elif 'encrypted' in bundle.properties:
                                print('Missing "nonce" in encrypted bundle. Cannot decrypt bundle ' + str(bundle.pk) + '. Skipping...')
                                break
                            elif 'nonce' in bundle.properties:
                                print('Missing "encrypted" in encrypted bundle. Cannot decrypt bundle ' + str(bundle.pk) + '. Skipping...')
                                break
                        elif bundle.compression != 'none':
                            compressed = base64.b64decode(bundle.properties['payload'])

                            if bundle.compression == 'gzip':
                                fio = BytesIO(compressed)  # io.BytesIO for Python 3
                                gzip_file_obj = gzip.GzipFile(fileobj=fio)
                                payload = gzip_file_obj.read()
                                gzip_file_obj.close()

                                bundle_size += len(payload)

                                bundle.properties = json.loads(payload)

                                # print(' Compress: %d -- %s' % (bundle.pk, timezone.now()))

                        now = timezone.now()

                        to_record = []

                        for bundle_point in bundle.properties: # pylint: disable=too-many-nested-blocks
                            # logging.debug('POINT: %s', json.dumps(bundle_point, indent=2))

                            if bundle_point is not None:
                                point_json = json.dumps(bundle_point)

                                while r'\u0000' in point_json:
                                    print('Detected 0x00 byte in ' + str(bundle.pk) + '. Stripping and ingesting...')

                                    point_json = point_json.replace(r'\u0000', '')

                                # while r'\ud83c' in point_json:
                                #    print('Detected 0xd83c byte in ' + str(bundle.pk) + '. Stripping and ingesting...')

                                #    point_json = point_json.replace(r'\ud83c', '')

                                bundle_point = json.loads(point_json)

                            try:
                                if bundle_point is not None and 'passive-data-metadata' in bundle_point and 'source' in bundle_point['passive-data-metadata'] and 'generator' in bundle_point['passive-data-metadata']:
                                    source = bundle_point['passive-data-metadata']['source']

                                    if source == '':
                                        source = 'missing-source'

                                    try:
                                        source = settings.PDK_RENAME_SOURCE(source)

                                        bundle_point['passive-data-metadata']['source'] = source
                                    except AttributeError:
                                        pass # Optional method not defined

                                    try:
                                        settings.PDK_INSPECT_DATA_POINT_AT_INGEST(bundle_point)
                                    except AttributeError:
                                        pass # Optional method not defined

                                    server_url = None

                                    if source in sources:
                                        server_url = sources[source]
                                    else:
                                        source_obj = DataSource.objects.filter(identifier=source).first()

                                        if source_obj is not None:
                                            if source_obj.server is not None:
                                                server_url = source_obj.server.upload_url
                                        else:
                                            if source is not None:
                                                source_obj = DataSource(name=source, identifier=source)
                                                source_obj.save()

                                                # Extract group from metadata if available
                                                group_name = bundle_point.get('passive-data-metadata', {}).get('group')
                                                
                                                if group_name:
                                                    # Try to find existing group by name
                                                    group = DataSourceGroup.objects.filter(name=group_name).first()
                                                    
                                                    if group is None:
                                                        # Create new group if it doesn't exist
                                                        group = DataSourceGroup(name=group_name)
                                                        group.save()
                                                    
                                                    source_obj.group = group
                                                    source_obj.save()
                                                else:
                                                    # Fall back to default group if no group in metadata
                                                    source_obj.join_default_group()

                                        if server_url is None:
                                            server_url = ''

                                        sources[source] = server_url

                                    if server_url == '':
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

                                        point.created = datetime.datetime.fromtimestamp(bundle_point['passive-data-metadata']['timestamp'], tz=default_tz)

                                        if supports_json:
                                            point.properties = json.loads(json.dumps(bundle_point, indent=2).encode('utf-16', 'surrogatepass').decode('utf-16'))
                                        else:
                                            point.properties = json.dumps(bundle_point, indent=2)

                                        point.fetch_secondary_identifier(skip_save=True, properties=bundle_point)
                                        point.fetch_user_agent(skip_save=True, properties=bundle_point)
                                        point.fetch_generator_definition(skip_save=True)
                                        point.fetch_source_reference(skip_save=True)

                                        to_record.append(point)

#                                        point.save()
#
#                                        if has_bundles:
#                                            point.fetch_bundle_files(bundle_files)
#
#                                        if (point.source in seen_sources) is False:
#                                            seen_sources.append(point.source)
#
#                                        if (point.source in source_identifiers) is False:
#                                            source_identifiers[point.source] = []
#
#                                        latest_key = point.source + '--' + point.generator_identifier
#
#                                        if (latest_key in latest_points) is False or latest_points[latest_key].created < point.created:
#                                            latest_points[latest_key] = point
#
#                                        if (point.generator_identifier in seen_generators) is False:
#                                            seen_generators.append(point.generator_identifier)
#
#                                        if (point.generator_identifier in source_identifiers[point.source]) is False:
#                                            source_identifiers[point.source].append(point.generator_identifier)
                                    else:
                                        if (server_url in xmit_points) is False:
                                            xmit_points[server_url] = []

                                        xmit_points[server_url].append(bundle_point)

                                    new_point_count += 1
                            except DataError:
                                traceback.print_exc()
                                print('Error ingesting bundle: ' + str(bundle.pk) + ':')
                                print(str(bundle.properties))

                        if len(to_record) > 0: # pylint: disable=len-as-condition
                            points = DataPoint.objects.bulk_create(to_record)

                            for point in points:
                                if has_bundles:
                                    point.fetch_bundle_files(bundle_files)

                                if (point.source in seen_sources) is False:
                                    seen_sources.append(point.source)

                                if (point.source in source_identifiers) is False:
                                    source_identifiers[point.source] = []

                                latest_key = point.source + '--' + point.generator_identifier

                                if (latest_key in latest_points) is False or latest_points[latest_key].created < point.created:
                                    latest_points[latest_key] = point

                                if (point.generator_identifier in seen_generators) is False:
                                    seen_generators.append(point.generator_identifier)

                                if (point.generator_identifier in source_identifiers[point.source]) is False:
                                    source_identifiers[point.source].append(point.generator_identifier)

                        if len(xmit_points) == 0: # pylint: disable=len-as-condition
                            bundle.processed = True
                        else:
                            failed = False

                            for server_url, points in xmit_points.items():
                                if len(points) > remote_bundle_size:
                                    payload = {
                                        'payload': json.dumps(points, indent=2)
                                    }

                                    try:
                                        bundle_post = requests.post(server_url, data=payload, timeout=remote_timeout)

                                        if bundle_post.status_code < 200 and bundle_post.status_code >= 300:
                                            failed = True

                                        # print(server_url + ': ' + str(len(points)))

                                        xmit_points[server_url] = []
                                    except requests.exceptions.Timeout:
                                        print('Unable to transmit data to ' + server_url + ' (timeout=' + str(remote_timeout) + ').')

                                        failed = True

                            if failed is False:
                                bundle.processed = True
                            else:
                                print('Error encountered uploading contents of ' + str(bundle.pk) + '.')

                        bundle.properties = original_properties

                        bundle.save()

                        if options['delete']:
                            to_delete.append(bundle)

                except TransactionManagementError:
                    print('[TransactionManagementError] Abandoning and marking errored ' + str(bundle.pk) + '.')

                    bundle = DataBundle.objects.get(pk=bundle.pk)

                    bundle.errored = timezone.now()
                    bundle.save()

                except TypeError:
                    print('[TypeError] Abandoning and marking errored ' + str(bundle.pk) + '.')

                    bundle = DataBundle.objects.get(pk=bundle.pk)

                    bundle.errored = timezone.now()
                    bundle.save()

        end_processing = timezone.now()

        elapsed = (end_processing - start_processing).total_seconds()

        if processed_bundle_count > 0:
            logging.debug('PROCESSED: %d -- %.3f -- %.3f (%s / %s)', processed_bundle_count, elapsed, (elapsed / processed_bundle_count), new_point_count, bundle_size)
        else:
            logging.debug('PROCESSED: %d -- %.3f -- %.3f (%s / %s)', processed_bundle_count, elapsed, 0, new_point_count, bundle_size)

        for server_url, points in xmit_points.items():
            if points:
                payload = {
                    'payload': json.dumps(points, indent=2)
                }

                try:
                    bundle_post = requests.post(server_url, data=payload, timeout=remote_timeout)

                    if bundle_post.status_code < 200 and bundle_post.status_code >= 300:
                        failed = True

                    # print(server_url + ': ' + str(len(points)))

                    xmit_points[server_url] = []
                except requests.exceptions.Timeout:
                    print('Unable to transmit data to ' + server_url + ' (timeout=' + str(remote_timeout) + ').')

        for bundle in to_delete:
            bundle.delete()

        if options['skip_stats'] is False:
            data_point_count = DataServerMetadatum.objects.filter(key=TOTAL_DATA_POINT_COUNT_DATUM).first()

            if data_point_count is None:
                count = DataPoint.objects.all().count()

                data_point_count = DataServerMetadatum(key=TOTAL_DATA_POINT_COUNT_DATUM)

                data_point_count.value = str(count)
                data_point_count.save()
            else:
                count = int(data_point_count.value)

                count += new_point_count

                data_point_count.value = str(count)
                data_point_count.save()

            data_point_count = DataServerMetadatum.objects.filter(key=TOTAL_DATA_POINT_COUNT_DATUM).first()

            sources = DataServerMetadatum.objects.filter(key=SOURCES_DATUM).first()

            if sources is not None:
                updated = False

                source_list = json.loads(sources.value)

                for seen_source in seen_sources:
                    if (seen_source in source_list) is False:
                        source_list.append(seen_source)

                        updated = True

                if updated:
                    sources.value = json.dumps(source_list, indent=2)
                    sources.save()
            else:
                DataPoint.objects.sources()

            for source, identifiers in list(source_identifiers.items()):
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

            datum_key = SOURCE_GENERATORS_DATUM
            generators_datum = DataServerMetadatum.objects.filter(key=datum_key).first()

            generator_ids = []

            if generators_datum is not None:
                generator_ids = json.loads(generators_datum.value)
            else:
                generators_datum = DataServerMetadatum(key=datum_key)

            updated = False

            for identifier in seen_generators:
                if (identifier in generator_ids) is False:
                    generator_ids.append(identifier)

                    updated = True

            if updated:
                generators_datum.value = json.dumps(generator_ids, indent=2)
                generators_datum.save()

            for identifier, point in list(latest_points.items()):
                DataPoint.objects.set_latest_point(point.source, point.generator_identifier, point)
                DataPoint.objects.set_latest_point(point.source, 'pdk-data-frequency', point)

            logging.debug("%d unprocessed payloads remaining.", DataBundle.objects.filter(processed=False, errored=None).count())

        else:
            DataServerMetadatum.objects.filter(key=TOTAL_DATA_POINT_COUNT_DATUM).delete()

        # elapsed = timezone.now() - start_time

        # print('Elapsed: ' + str(elapsed) + ' -- ' + str(processed_bundle_count) + ' bundles')
