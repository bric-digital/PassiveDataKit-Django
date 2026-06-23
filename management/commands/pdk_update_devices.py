# pylint: disable=no-member,line-too-long

from django.core.management.base import BaseCommand

from ...decorators import handle_lock
from ...models import DataSource, Device

class Command(BaseCommand):
    help = 'Create device records for data sources.'

    @handle_lock()
    def handle(self, *args, **options): # pylint: disable=too-many-locals, too-many-branches, too-many-statements
        for source in DataSource.objects.all():
            device = source.devices.all().first()

            if device is None:
                device = Device(source=source)
                device.populate_device()
            else:
                device.populate_device()
