# pylint: disable=no-member,line-too-long

import base64

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
                            help='Backup file to decompress and decrypt')


    @handle_lock()
    def handle(self, *args, **options):
        key = base64.b64decode(settings.PDK_BACKUP_KEY) # getpass.getpass('Enter secret backup key: ')

        encrypted_file = options['file'][0]

        box = SecretBox(key)

        with open(encrypted_file, 'rb') as backup_file:
            encrypted_content = backup_file.read()

            content = box.decrypt(encrypted_content)

            with open(encrypted_file.replace('.encrypted', ''), 'wb') as output:
                output.write(content)
