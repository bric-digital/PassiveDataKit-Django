# pylint: disable=no-member,line-too-long

import calendar
import datetime
import json

import pytz

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from passive_data_kit.decorators import handle_lock, log_scheduled_event
from passive_data_kit.models import DataBundle, DataPoint, DataServerMetadatum

class Command(BaseCommand):
    help = 'Compiles updates server health statistics.'

    def add_arguments(self, parser):
        pass

    @handle_lock()
    @log_scheduled_event
    def handle(self, *args, **options): # pylint: disable=too-many-branches
        datum = DataServerMetadatum.objects.filter(key='Server Health').first()

        now = timezone.now().astimezone(pytz.timezone(settings.TIME_ZONE))

        start = now - datetime.timedelta(days=1)

        if datum is None:
            datum = DataServerMetadatum(key='Server Health', value='{}')

        data = json.loads(datum.value)

        if ('bundle_snapshots' in data) is False:
            data['bundle_snapshots'] = []

        bundle_count = DataBundle.objects.all().count()
        unprocessed_count = DataBundle.objects.filter(processed=False).count()

        if ('last_bundle_count' in data) is False:
            data['last_bundle_count'] = bundle_count

        data['bundle_snapshots'].append({
            'time': calendar.timegm(now.utctimetuple()),
            'unprocessed': unprocessed_count,
            'added': bundle_count - data['last_bundle_count']
        })

        data['last_bundle_count'] = bundle_count

        if ('point_snapshots' in data) is False:
            data['point_snapshots'] = []

        # point_count = DataPoint.objects.all().count()

        last_point = DataPoint.objects.all().order_by('-pk').first()

        if last_point is not None:
            point_count = last_point.pk

            if ('last_point_count' in data) is False:
                data['last_point_count'] = point_count

            data['point_snapshots'].append({
                'time': calendar.timegm(now.utctimetuple()),
                'added': point_count - data['last_point_count']
            })

            data['last_point_count'] = point_count

            start_ts = calendar.timegm(start.utctimetuple())

            to_delete = []

            for bundle in data['bundle_snapshots']:
                if bundle['time'] < start_ts:
                    to_delete.append(bundle)

            for bundle in to_delete:
                data['bundle_snapshots'].remove(bundle)

            to_delete = []

            for point in data['point_snapshots']:
                if point['time'] < start_ts:
                    to_delete.append(point)

            for point in to_delete:
                data['point_snapshots'].remove(point)

            datum.value = json.dumps(data, indent=2)
            datum.save()
