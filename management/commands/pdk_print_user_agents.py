# pylint: disable=no-member,line-too-long

from django.core.management.base import BaseCommand

from ...decorators import handle_lock
from ...models import DataSourceGroup, DataSourceReference, DataPoint

class Command(BaseCommand):
    help = 'Displays latest user-agent for each data source.'

    @handle_lock
    def handle(self, *args, **options): # pylint: disable=too-many-locals, too-many-branches, too-many-statements
        for group in DataSourceGroup.objects.all().order_by('name'):
            print(group.name)

            for source in group.sources.all().order_by('identifier'):
                source_reference = DataSourceReference.reference_for_source(source.identifier)

                latest_point = DataPoint.objects.filter(source_reference=source_reference).exclude(user_agent__icontains='Web Dashboard').order_by('-created').first()

                if latest_point is not None:
                    print(source.identifier + ': ' + latest_point.user_agent)
                else:
                    print(source.identifier + ': No data points logged')
