# pylint: disable=no-member,line-too-long

import base64
import bz2
import datetime
import json
import os
import random

from nacl.exceptions import CryptoError
from nacl.secret import SecretBox

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from passive_data_kit.decorators import handle_lock
from passive_data_kit.models import DataPoint, DataSourceReference, DataGeneratorDefinition

class Command(BaseCommand):
    help = 'Loads content from incremental backups of data content.'

    def add_arguments(self, parser):
        parser.add_argument('--count',
                            nargs='?',
                            type=int,
                            default=10,
                            help='Number of random points in backup file to verify exist in database')

        parser.add_argument('file',
                            nargs='+',
                            type=str,
                            help='Backup containing data points to verify')

    @handle_lock()
    def handle(self, *args, **options): # pylint: disable=too-many-locals
        key = base64.b64decode(settings.PDK_BACKUP_KEY)

        warned = False

        default_tz = timezone.get_default_timezone()

        for encrypted_file in options['file']:
            tested = 0
            seen = 0

            filename = os.path.basename(encrypted_file)

            if os.path.exists(encrypted_file):
                if 'pdk-bundle' in filename:
                    box = SecretBox(key)

                    with open(encrypted_file, 'rb') as backup_file:
                        content = backup_file.read()

                        try:
                            content = box.decrypt(content)
                        except CryptoError:
                            if warned is False:
                                print('Unable to decrypt "' + filename + '", attempting decompression of original (maybe unencrypted) content...')
                                warned = True

                        decompressed = bz2.decompress(content)

                        remaining_count = options['count']

                        data_points = json.loads(decompressed)

                        while remaining_count > 0:
                            random_point = random.choice(data_points) # nosec

                            created = datetime.datetime.fromtimestamp(random_point['passive-data-metadata']['timestamp'], tz=default_tz)

                            source_reference = DataSourceReference.reference_for_source(random_point['passive-data-metadata']['source'])
                            generator_definition = DataGeneratorDefinition.definition_for_identifier(random_point['passive-data-metadata']['generator-id'])

                            if DataPoint.objects.filter(source_reference=source_reference, generator_definition=generator_definition, created=created).count() > 0:
                                seen += 1

                            tested += 1

                            remaining_count -= 1
                else:
                    print('Skipping ' + filename + '. Invalid file type.')
            else:
                raise RuntimeError(filename + ' does not exist.')

            if seen < tested:
                print('Missing points (' + str(seen) + ' / ' + str(tested) + '): ' + filename)
            else:
                print('OK (' + str(seen) + ' / ' + str(tested) + '): ' + filename)
