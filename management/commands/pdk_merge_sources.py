# pylint: disable=no-member,line-too-long

from django.core.management.base import BaseCommand

from passive_data_kit.decorators import handle_lock
from passive_data_kit.models import DataPoint, DataSourceReference

class Command(BaseCommand):
    help = 'Loads content from incremental backups of data content.'

    def add_arguments(self, parser):
        parser.add_argument('origin',
                            type=str,
                            help='Source ID to merge (that will be deleted)')

        parser.add_argument('destination',
                            type=str,
                            help='Destination ID merged to (that will remain)')

    @handle_lock()
    def handle(self, *args, **options): # pylint: disable=too-many-locals
        origin_reference = DataSourceReference.reference_for_source(options['origin'])
        destination_reference = DataSourceReference.reference_for_source(options['destination'])

        ref_updated = DataPoint.objects.filter(source_reference=origin_reference).update(source_reference=destination_reference, source=options['destination'])

        print('Reference updates: %s' % ref_updated)

        source_updated = DataPoint.objects.filter(source=options['origin']).update(source_reference=destination_reference, source=options['destination'])

        print('Source updates: %s' % source_updated)
