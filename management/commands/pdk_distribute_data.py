# pylint: disable=no-member,line-too-long

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from ...decorators import handle_lock, log_scheduled_event
from ...models import  DataPoint, DataSource, DataSourceReference, DataBundle

class Command(BaseCommand):
    help = 'Convert unprocessed DataBundle instances into DataPoint instances.'

    def add_arguments(self, parser):
        parser.add_argument('--count',
                            type=int,
                            dest='point_count',
                            default=100,
                            help='Number of points to include in a a bundle')

        parser.add_argument('--source',
                            type=str,
                            dest='source',
                            default='any',
                            help='Specific source to update')

        parser.add_argument('--bundle-count',
                            type=int,
                            dest='bundle_count',
                            default=100,
                            help='Number of bundles to generate for each source before moving on to next source')

        parser.add_argument('--server-pk',
                            type=int,
                            dest='server_pk',
                            default=None,
                            help='Select sources pointing to this server')

    @handle_lock
    @log_scheduled_event
    def handle(self, *args, **options): # pylint: disable=too-many-locals, too-many-branches, too-many-statements
        source_query = DataSource.objects.exclude(server=None)

        if options['server_pk'] is not None:
            source_query = source_query.filter(server=options['server_pk'])

        if options['source'] != 'any':
            source_query = source_query.filter(identifier=options['source'])
        else:
            source_query = source_query.order_by('identifier')

        for source in source_query:
            source_reference = DataSourceReference.reference_for_source(source.identifier)

            point_count = DataPoint.objects.filter(source_reference=source_reference).count()

            if point_count > 0:
                print('---- ----')

            if options['source'] != 'any':
                print(source.identifier + ': ' + str(point_count) + ' -> ' + str(source.server))

            bundle_count = 0

            while point_count > 0 and bundle_count < options['bundle_count']:
                with transaction.atomic():
                    clear_pks = []

                    points = DataPoint.objects.filter(source_reference=source_reference)[:options['point_count']]

                    bundle = []

                    for point in points:
                        bundle.append(point.fetch_properties())

                        clear_pks.append(point.pk)

                    data_bundle = DataBundle(recorded=timezone.now())

                    data_bundle.properties = bundle

                    data_bundle.save()

                    bundle_count += 1

                    for clear_pk in clear_pks:
                        DataPoint.objects.get(pk=clear_pk).delete()

                point_count = DataPoint.objects.filter(source_reference=source_reference).count()

                print(source.identifier + ': ' + str(point_count) + ' -> ' + str(source.server))
