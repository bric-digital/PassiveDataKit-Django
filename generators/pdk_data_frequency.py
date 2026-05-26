# pylint: disable=line-too-long, no-member

import calendar
import datetime
import io
import json
import os

from django.conf import settings
from django.template.loader import render_to_string
from django.utils import timezone

from ..models import DataSource, DataSourceReference, DataPoint

DEFAULT_INTERVAL = 600
DEFAULT_DAYS = 2

def generator_name(identifier): # pylint: disable=unused-argument
    return 'Data Frequency'

def compile_visualization(identifier, points, folder, source): # pylint: disable=unused-argument, too-many-locals, too-many-statements
    now = timezone.now()

    interval = DEFAULT_INTERVAL

    try:
        interval = settings.PDK_DATA_FREQUENCY_VISUALIZATION_INTERVAL
    except AttributeError:
        pass

    visualize_days = DEFAULT_DAYS

    try:
        visualize_days = settings.PDK_DATA_FREQUENCY_VISUALIZATION_DAYS
    except AttributeError:
        pass

    data_source = DataSource.objects.filter(identifier=source).first()

    if data_source is not None:
        latest = data_source.latest_point()

        if latest is not None:
            now = latest.created

    now = now.replace(second=0, microsecond=0)

    remainder = now.minute % int(interval // 60)

    now = now.replace(minute=(now.minute - remainder))

    now += datetime.timedelta(seconds=interval)

    start = now - datetime.timedelta(days=visualize_days)

    end = start + datetime.timedelta(seconds=interval)

    timestamp_counts = {}

    keys = []

    if source is None:
        source = 'passive-data-kit'

    source_reference = DataSourceReference.reference_for_source(source)

    points = DataPoint.objects.filter(source_reference=source_reference)

    while start < now:
        timestamp = str(calendar.timegm(start.timetuple()))

        keys.append(timestamp)

        timestamp_counts[timestamp] = points.filter(created__lte=end, created__gte=start).count()

        start = end
        end = start + datetime.timedelta(seconds=interval)

    timestamp_counts['keys'] = keys

    with io.open(folder + os.path.sep + 'timestamp-counts.json', 'w', encoding='utf-8') as outfile:
        outfile.write(json.dumps(timestamp_counts, indent=2, ensure_ascii=False))

    # Plot times recorded

    now = timezone.now()

    if data_source is not None:
        latest = data_source.latest_point_recorded()

        if latest is not None:
            now = latest.recorded

    now = now.replace(second=0, microsecond=0)

    remainder = now.minute % int(interval // 60)

    now = now.replace(minute=(now.minute - remainder))

    now += datetime.timedelta(seconds=interval)

    start = now - datetime.timedelta(days=visualize_days)

    end = start + datetime.timedelta(seconds=interval)

    timestamp_counts = {}

    keys = []

    while start < now:
        timestamp = str(calendar.timegm(start.timetuple()))

        keys.append(timestamp)

        timestamp_counts[timestamp] = points.filter(recorded__lte=end, recorded__gte=start).count()

        start = end
        end = start + datetime.timedelta(seconds=interval)

    timestamp_counts['keys'] = keys

    with io.open(folder + os.path.sep + 'timestamp-recorded-counts.json', 'w', encoding='utf-8') as outfile:
        outfile.write(json.dumps(timestamp_counts, indent=2, ensure_ascii=False))

def visualization(source, generator): # pylint: disable=unused-argument
    filename = settings.MEDIA_ROOT + os.path.sep + 'pdk_visualizations' + os.path.sep + source.identifier + os.path.sep + 'pdk-data-frequency' + os.path.sep + 'timestamp-counts.json'

    context = {}

    try:
        with io.open(filename, encoding='utf-8') as infile:
            data = json.load(infile)

            context['data'] = data

            context['updated'] = datetime.datetime.utcfromtimestamp(os.path.getmtime(filename))

            try:
                recorded_file = settings.MEDIA_ROOT + os.path.sep + 'pdk_visualizations' + os.path.sep + source.identifier + os.path.sep + 'pdk-data-frequency' + os.path.sep + 'timestamp-recorded-counts.json'

                with io.open(recorded_file, encoding='utf-8') as infile:
                    recorded_data = json.load(infile)

                    context['recorded'] = recorded_data
            except IOError:
                context['recorded'] = {}
    except IOError:
        context['data'] = {}
        context['recorded'] = {}
        context['updated'] = None

    return render_to_string('pdk_data_frequency_template.html', context)
