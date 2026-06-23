# pylint: disable=no-member,line-too-long

import datetime
import importlib
import json
import os
import traceback

import pytz

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from passive_data_kit.decorators import handle_lock, log_scheduled_event
from passive_data_kit.models import DataPoint, DataPointVisualization, DataSource, DataSourceReference, DataGeneratorDefinition

class Command(BaseCommand):
    help = 'Compiles support files and other resources used for data inspection and visualization.'

    def add_arguments(self, parser):
        parser.add_argument('--source',
                            type=str,
                            dest='source',
                            default='all',
                            help='Specific source to regenerate')

        parser.add_argument('--generator',
                            type=str,
                            dest='generator',
                            default='all',
                            help='Specific generator to regenerate')

        parser.add_argument('--repeat',
                            type=int,
                            dest='repeat',
                            default=10,
                            help='Number of times to repeat in a single run')

        parser.add_argument('--mode',
                            type=str,
                            dest='mode',
                            default='intelligent',
                            help='Only update when new data is available ("intelligent", default), update oldest visualizations first ("oldest")')

    @handle_lock()
    @log_scheduled_event
    def handle(self, *args, **options): # pylint: disable=too-many-branches, too-many-locals, too-many-statements
        repeat = options['repeat']

        if options['source'] != 'all':
            DataPointVisualization.objects.filter(source=options['source']).delete()

        sources = []

        if options['source'] != 'all':
            sources = [options['source']]
        else:
            sources = sorted(DataSource.objects.sources())

        deltas = []

        if options['mode'] == 'intelligent':
            for source in sources:
                source_identifiers = ['pdk-data-frequency']

                if options['generator'] == 'all':
                    for identifier in DataPoint.objects.generator_identifiers_for_source(source):
                        source_identifiers.append(identifier)
                else:
                    source_identifiers.append(options['generator'])

                for identifier in source_identifiers:
                    if DataPointVisualization.objects.filter(source=source, generator_identifier=identifier).count() == 0:
                        new_visualization = DataPointVisualization(source=source, generator_identifier=identifier)

                        new_visualization.last_updated = pytz.timezone('UTC').localize(datetime.datetime.min + datetime.timedelta(days=1))
                        new_visualization.save()

                    visualizations = DataPointVisualization.objects.filter(source=source, generator_identifier=identifier).order_by('last_updated')

                    if visualizations.count() > 1:
                        print('Removing extra ' + source + '@' + identifier + ' visualizations...')

                        first = visualizations.order_by('pk').first()

                        visualizations.exclude(pk=first.pk).delete()

                    delta = {
                        'visualization': visualizations.first()
                    }

                    if delta['visualization'].last_updated > timezone.now():
                        delta['visualization'].last_updated = timezone.now()
                        delta['visualization'].save()

                    # last_point = DataPoint.objects.latest_point(source, identifier)

                    # if last_point is not None:
                    #    delta['elapsed'] = (last_point.recorded - delta['visualization'].last_updated).total_seconds()

                    #    deltas.append(delta)
                    # elif identifier == 'pdk-data-frequency':
                    #    delta['elapsed'] = (timezone.now() - delta['visualization'].last_updated).total_seconds()

                    #    deltas.append(delta)

                    delta['elapsed'] = (timezone.now() - delta['visualization'].last_updated).total_seconds()

                    deltas.append(delta)
        elif options['mode'] == 'oldest':
            for visualization in DataPointVisualization.objects.all().order_by('last_updated')[:repeat]:
                delta = {
                    'visualization': visualization,
                    'elapsed': (timezone.now() - visualization.last_updated).total_seconds()
                }

                deltas.append(delta)

        deltas.sort(key=lambda delta: delta['elapsed'], reverse=True)

        start_time = timezone.now()
        time_spent = {}

        loop_times = []

        for delta in deltas[:repeat]:
            repeat_start = timezone.now()

            visualization = delta['visualization']

            points = None

            computed_id = visualization.generator_identifier + '@' + visualization.source

            time_spent[computed_id] = {
                'start': timezone.now()
            }

            source_reference = DataSourceReference.reference_for_source(visualization.source)

            if visualization.generator_identifier == 'pdk-data-frequency':
                points = DataPoint.objects.filter(source_reference=source_reference)
            else:
                definition = DataGeneratorDefinition.definition_for_identifier(visualization.generator_identifier)
                points = DataPoint.objects.filter(source_reference=source_reference, generator_definition=definition)

            folder = settings.MEDIA_ROOT + '/pdk_visualizations/' + visualization.source + '/' + visualization.generator_identifier

            if os.path.exists(folder) is False:
                os.makedirs(folder)

            time_spent[computed_id]['query_end'] = timezone.now()

            for app in settings.INSTALLED_APPS:
                try:
                    pdk_api = importlib.import_module(app + '.pdk_api')

                    completed = False

                    try:
                        pdk_api.compile_visualization(visualization.generator_identifier, points, folder, visualization.source)

                        time_spent[computed_id]['app'] = app

                        completed = True
                    except TypeError:
                        print('App with broken viz endpoint: ' + app)
                        traceback.print_exc()
                        pdk_api.compile_visualization(visualization.generator_identifier, points, folder)

                        time_spent[computed_id]['app'] = app

                        completed = True

                    if completed:
                        break
                except ImportError:
                    pass
                except AttributeError:
                    pass
                except NotImplementedError:
                    pass

            time_spent[computed_id]['end'] = timezone.now()

            visualization.last_updated = timezone.now()
            visualization.save()

            repeat_end = timezone.now()

            loop_times.append(computed_id + ': ' + str((repeat_end - repeat_start).total_seconds()))

        end_time = timezone.now()

        excessive_time = 15

        try:
            excessive_time = settings.PDK_EXCESSIVE_VISUALIZATION_TIME
        except AttributeError:
            pass

        if (end_time - start_time).total_seconds() > excessive_time:
            print('Excessive visualization compilation time: ' + str((end_time - start_time).total_seconds()) + ' seconds:')

            for key, times in list(time_spent.items()):
                query = times['query_end'] - times['start']
                spent = times['end'] - times['start']

                print('  ' + key + ': Q->' + str(query.total_seconds()) + 's; T->' + str(spent.total_seconds()) + 's (' + times['app'] + ')')

            print('Loop Times: ' + str(json.dumps(loop_times, indent=2)))

            try:
                excessive_time = settings.PDK_EXCESSIVE_VISUALIZATION_TIME
            except AttributeError:
                print('PDK_EXCESSIVE_VISUALIZATION_TIME not configured in site settings. Set to number of desired seconds to suppress this message.')
