# pylint: disable=no-member,line-too-long

import base64
import bz2
import importlib
import os

from nacl.exceptions import CryptoError
from nacl.secret import SecretBox

from django.conf import settings
from django.core.management.base import BaseCommand

from passive_data_kit.decorators import handle_lock

class Command(BaseCommand):
    help = 'Loads content from incremental backups of data content.'

    def add_arguments(self, parser):
        parser.add_argument('file',
                            nargs='+',
                            type=str,
                            help='Backup file to import into local database')


    @handle_lock()
    def handle(self, *args, **options):
        key = base64.b64decode(settings.PDK_BACKUP_KEY)

        warned = False

        for app in settings.INSTALLED_APPS:
            try:
                pdk_api = importlib.import_module(app + '.pdk_api')

                for encrypted_file in options['file']:
                    filename = os.path.basename(encrypted_file)

                    if os.path.exists(encrypted_file):
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

                            pdk_api.load_backup(filename, decompressed)
                    else:
                        raise RuntimeError(filename + ' does not exist.')

            except ImportError:
                pass
            except AttributeError:
                pass
