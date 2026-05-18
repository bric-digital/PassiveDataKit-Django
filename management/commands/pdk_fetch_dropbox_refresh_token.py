# pylint: disable=no-member,line-too-long

import json

import requests

from django.core.management.base import BaseCommand

class Command(BaseCommand):
    help = 'Remove data associated with a specific source identifier.'

    def add_arguments(self, parser):
        pass

    def handle(self, *args, **options): # pylint: disable=too-many-locals, too-many-branches, too-many-statements
        app_key = input('Enter app key: ')
        app_secret = input('Enter app secret: ')

        print('Open https://www.dropbox.com/oauth2/authorize?client_id=%s&token_access_type=offline&response_type=code in your browser.' % app_key)

        auth_code = input('Enter authorization code: ')

        session = requests.Session()
        session.auth = (app_key, app_secret)

        payload = {
            'code': auth_code,
            'grant_type': 'authorization_code',
        }

        response = session.post('https://api.dropboxapi.com/oauth2/token', data=payload)

        print(json.dumps(response.json(), indent=2))
