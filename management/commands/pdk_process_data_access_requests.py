# pylint: disable=no-member,line-too-long

from django.core.management.base import BaseCommand

from ...decorators import handle_lock
from ...models import DataServerAccessRequestPending

class Command(BaseCommand):
    help = 'Convert pending DataServerAccessRequestPending items to archived records.'

    @handle_lock()
    def handle(self, *args, **options): # pylint: disable=too-many-locals, too-many-branches, too-many-statements
        for request in DataServerAccessRequestPending.objects.filter(processed=False):
            request.process()

        DataServerAccessRequestPending.objects.filter(processed=True).delete()
