# pylint: disable=no-member,line-too-long

import base64
import datetime
import importlib
import os
import sys
import traceback

from io import BytesIO

import boto3
import dropbox
import pytz

from azure.storage.blob import BlobServiceClient
from botocore.config import Config
from nacl.secret import SecretBox

from django.conf import settings
from django.core.management.base import BaseCommand

from passive_data_kit.decorators import handle_lock

try:
    from urllib.parse import urlparse
except ImportError:
    from urlparse import urlparse

class Command(BaseCommand):
    help = 'Generates incremental backups of data content and transmits to storage.'

    def add_arguments(self, parser):
        parser.add_argument('--start-date',
                            type=str,
                            dest='start_date',
                            default=None,
                            help='Start of date range for incremental backup')

        parser.add_argument('--end-date',
                            type=str,
                            dest='end_date',
                            default=None,
                            help='End of date range for incremental backup')

        parser.add_argument('--clear-archived',
                            dest='clear_archived',
                            action='store_true',
                            help='Delete backed-up content after successful transmission')

        parser.add_argument('--skip-apps',
                            dest='skip_apps',
                            action='store_true',
                            help='Skip backup of app data other than PDK data points')

        parser.add_argument('--filter-sensitive-data',
                            dest='filter_sensitive',
                            action='store_true',
                            help='Filter sensitive data from the backup data points written')

    def folder_for_options(self, options): # pylint: disable=no-self-use
        folder_path_format = '%(start_date)s__%(end_date)s'

        try:
            folder_path_format = settings.PDK_BACKUP_FOLDER_FORMAT
        except AttributeError:
            pass

        folder_args = {}

        if 'start_date' in options:
            folder_args['start_date'] = str(options['start_date'])
        else:
            folder_args['start_date'] = 'start'

        if 'end_date' in options:
            folder_args['end_date'] = str(options['end_date'])
        else:
            folder_args['end_date'] = 'end'

        if 'clear_archived' in options and options['clear_archived']:
            folder_args['clear'] = 'data-cleared'
        else:
            folder_args['clear'] = 'data-retained'

        return folder_path_format % folder_args


    @handle_lock
    def handle(self, *args, **options): # pylint: disable=too-many-locals, too-many-statements, too-many-branches
        here_tz = pytz.timezone(settings.TIME_ZONE)

        parameters = {}

        yesterday = datetime.date.today() - datetime.timedelta(days=1)

        if options['start_date'] is not None:
            components = options['start_date'].split('-')

            parameters['start_date'] = datetime.datetime(int(components[0]), int(components[1]), int(components[2]), 0, 0, 0, 0, here_tz)
        else:
            parameters['start_date'] = datetime.datetime(yesterday.year, yesterday.month, yesterday.day, 0, 0, 0, 0, here_tz)

            options['start_date'] = yesterday.isoformat()

        if options['end_date'] is not None:
            components = options['end_date'].split('-')

            end_date = datetime.datetime(int(components[0]), int(components[1]), int(components[2]), 0, 0, 0, 0, here_tz) + datetime.timedelta(days=1)

            parameters['end_date'] = end_date
        else:
            today = yesterday + datetime.timedelta(days=1)

            parameters['end_date'] = datetime.datetime(today.year, today.month, today.day, 0, 0, 0, 0, here_tz)

            options['end_date'] = today.isoformat()

        parameters['clear_archived'] = options['clear_archived']
        parameters['skip_apps'] = options['skip_apps']
        parameters['filter_sensitive'] = options['filter_sensitive']

        key = None

        try:
            key = base64.b64decode(settings.PDK_BACKUP_KEY)
        except AttributeError:
            print('Please define PDK_BACKUP_KEY in the settings.')

            sys.exit(1)

        destinations = None

        try:
            destinations = settings.PDK_BACKUP_DESTINATIONS
        except AttributeError:
            print('Please define PDK_BACKUP_DESTINATIONS in the settings.')

            sys.exit(1)

        for app in settings.INSTALLED_APPS: # pylint: disable=too-many-nested-blocks
            try:
                pdk_api = importlib.import_module(app + '.pdk_api')

                to_transmit, to_clear = pdk_api.incremental_backup(parameters)

                for destination in destinations:
                    destination_url = urlparse(destination)

                    if destination_url.scheme == 'file':
                        dest_path = destination_url.path

                        final_folder = self.folder_for_options(options)

                        if final_folder is not None:
                            dest_path = os.path.join(dest_path, final_folder)

                        if os.path.exists(dest_path) is False:
                            print('Creating folder for archive storage: ' + dest_path)
                            sys.stdout.flush()
                            os.makedirs(dest_path)

                        for path in to_transmit:
                            box = SecretBox(key)

                            with open(path, 'rb') as backup_file:
                                encrypted_str = box.encrypt(backup_file.read())

                                filename = os.path.basename(path) + '.encrypted'

                                encrypted_path = os.path.join(dest_path, filename)

                                print('Writing to filesystem: ' + encrypted_path)
                                sys.stdout.flush()

                                with open(encrypted_path, 'wb') as encrypted_file:
                                    encrypted_file.write(encrypted_str)
                    elif destination_url.scheme == 'dropbox':
                        access_token = destination_url.netloc

                        client = dropbox.Dropbox(access_token)

                        for path in to_transmit:
                            box = SecretBox(key)

                            with open(path, 'rb') as backup_file:
                                backup_io = BytesIO()
                                backup_io.write(backup_file.read())
                                backup_io.seek(0)

                                filename = os.path.basename(path) + '.encrypted'

                                final_folder = self.folder_for_options(options)

                                dropbox_path = os.path.join(destination_url.path, final_folder + '/' + filename)

                                print('Uploading to Dropbox: ' + dropbox_path)
                                sys.stdout.flush()

                                client.files_upload(box.encrypt(backup_io.read()), dropbox_path)
                    elif destination_url.scheme == 's3':
                        try:
                            aws_config = Config(
                                region_name=settings.PDK_BACKUP_AWS_REGION,
                                retries={'max_attempts': 10, 'mode': 'standard'}
                            )

                            os.environ['AWS_ACCESS_KEY_ID'] = settings.PDK_BACKUP_AWS_ACCESS_KEY_ID
                            os.environ['AWS_SECRET_ACCESS_KEY'] = settings.PDK_BACKUP_AWS_SECRET_ACCESS_KEY

                            client = boto3.client('s3', config=aws_config)

                            s3_bucket = destination_url.netloc

                            for path in to_transmit:
                                box = SecretBox(key)

                                with open(path, 'rb') as backup_file:
                                    backup_io = BytesIO()
                                    backup_io.write(backup_file.read())
                                    backup_io.seek(0)

                                    filename = os.path.basename(path) + '.encrypted'

                                    final_folder = self.folder_for_options(options)

                                    final_filename = final_folder + '/' + filename

                                    print('Uploading to S3: ' + final_filename)
                                    sys.stdout.flush()

                                    client.put_object(Body=box.encrypt(backup_io.read()), Bucket=s3_bucket, Key=final_filename)
                        except: # pylint: disable=bare-except
                            traceback.print_exc()
                    elif destination_url.scheme == 'azure-blob':
                        blob_service_client = BlobServiceClient.from_connection_string(settings.PDK_AZURE_CONNECTION_STRING)

                        try:
                            for path in to_transmit:
                                box = SecretBox(key)

                                with open(path, 'rb') as backup_file:
                                    backup_io = BytesIO()
                                    backup_io.write(backup_file.read())
                                    backup_io.seek(0)

                                    filename = os.path.basename(path) + '.encrypted'

                                    final_folder = self.folder_for_options(options)

                                    final_filename = final_folder + '/' + filename

                                    blob_client = blob_service_client.get_blob_client(container=settings.PDK_AZURE_BLOB_CONTAINER, blob=final_filename)

                                    print('Uploading to Azure Blob Service: ' + final_filename)
                                    sys.stdout.flush()

                                    blob_client.upload_blob(backup_io)
                        except: # pylint: disable=bare-except
                            traceback.print_exc()
                    else:
                        print('Unknown destination: ' + destination)

                for path in to_transmit:
                    os.remove(path)

                pdk_api.clear_points(to_clear)

            except ImportError:
                pass
            except AttributeError:
                pass
