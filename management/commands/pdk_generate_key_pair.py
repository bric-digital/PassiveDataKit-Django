# -*- coding: utf-8 -*-
# pylint: disable=no-member,line-too-long

import base64

from nacl.public import PrivateKey

from django.core.management.base import BaseCommand

class Command(BaseCommand):
    help = 'Generates a NaCl keypair for use with public key encryption.'

    def add_arguments(self, parser):
        pass

    def handle(self, *args, **options): # pylint: disable=too-many-locals,too-many-branches,too-many-statements
        key = PrivateKey.generate()

        print('PRIVATE: %s' % base64.b64encode(key.encode()).decode('utf-8'))
        print('PUBLIC:  %s' % base64.b64encode(key.public_key.encode()).decode('utf-8'))
