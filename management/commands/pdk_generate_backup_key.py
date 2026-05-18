# -*- coding: utf-8 -*-
# pylint: disable=no-member,line-too-long

import base64

import nacl.secret
import nacl.utils

from django.core.management.base import BaseCommand

class Command(BaseCommand):
    help = 'Generates a NaCl keypair for use with public key encryption.'

    def add_arguments(self, parser):
        pass

    def handle(self, *args, **options): # pylint: disable=too-many-locals,too-many-branches,too-many-statements
        key = nacl.utils.random(nacl.secret.SecretBox.KEY_SIZE)

        print('BACKUP KEY: ' + base64.b64encode(key).decode('utf-8'))
