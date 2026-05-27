# pylint: disable=no-member, line-too-long

from django.core.management.base import BaseCommand

from ...decorators import handle_lock, log_scheduled_event
from ...models import DataSource, DataServer

class Command(BaseCommand):
    help = 'Updates each user performance metadata measurements on a round-robin basis'

    def add_arguments(self, parser):
        parser.add_argument('--source',
                            type=str,
                            dest='source',
                            default='any',
                            help='Specific source to update')

    @handle_lock()
    @log_scheduled_event
    def handle(self, *args, **options):
        servers = []

        for server in DataServer.objects.all():
            servers.append(server)

        servers.append(None)

        for server in servers:
            source = None

            if options['source'] != 'any':
                source = DataSource.objects.filter(identifier=options['source']).first()

            if source is None:
                source = DataSource.objects.filter(server=server, performance_metadata_updated=None, suppress_alerts=False).first()

            if source is None:
                source = DataSource.objects.filter(server=server, suppress_alerts=False).order_by('performance_metadata_updated').first()

            if source is not None:
                source.update_performance_metadata()
