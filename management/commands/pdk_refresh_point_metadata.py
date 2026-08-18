# pylint: disable=no-member,line-too-long

import sys

from django.core.management.base import BaseCommand

from ...decorators import handle_lock
from ...models import DataSource

class Command(BaseCommand):
    help = 'Populates earliest_point and latest_point caches if needed.'

    def add_arguments(self, parser):
        pass

    @handle_lock
    def handle(self, *args, **options): # pylint: disable=too-many-locals, too-many-branches, too-many-statements
        for source in DataSource.objects.all().order_by('server', 'identifier'):
            print(str(source.identifier) + ' -- ' + str(source.server))
            sys.stdout.flush()
            print('E: ' + str(source.earliest_point()))
            sys.stdout.flush()
            print('L: ' + str(source.latest_point()))
            sys.stdout.flush()
