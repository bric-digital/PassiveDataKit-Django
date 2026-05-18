# pylint: disable=line-too-long, no-member

import pytz

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from ...decorators import handle_lock

from ...models import DataPoint, DataSource, DataSourceAlert, DataSourceReference, DataGeneratorDefinition

GENERATOR = 'pdk-remote-nudge'
CRITICAL_LEVEL = 12 * 60 * 60
WARNING_LEVEL = 6 * 60 * 60

class Command(BaseCommand):
    help = 'Determines if mobile devices are receiving silent push notifications.'

    @handle_lock
    def handle(self, *args, **options): # pylint: disable=too-many-branches, too-many-statements, too-many-locals
        try:
            if (GENERATOR in settings.PDK_ENABLED_CHECKS) is False:
                DataSourceAlert.objects.filter(generator_identifier=GENERATOR, active=True).update(active=False)

                return
        except AttributeError:
            print('Did not find PDK_ENABLED_CHECKS in Django settings. Please define with a list of generators with status checks to enable.')
            print('Example: PDK_ENABLED_CHECKS = (\'' + GENERATOR + '\',)')

        here_tz = pytz.timezone(settings.TIME_ZONE)

        for source in DataSource.objects.all(): # pylint: disable=too-many-nested-blocks
            now = timezone.now()

            source_reference = DataSourceReference.reference_for_source(source.identifier)
            generator_definition = DataGeneratorDefinition.definition_for_identifier('pdk-app-event')

            if source.should_suppress_alerts():
                DataSourceAlert.objects.filter(data_source=source, generator_identifier=GENERATOR, active=True).update(active=False)
            else:
                secondary_query = Q(secondary_identifier='app_recv_remote_notification') | Q(secondary_identifier='pdk-received-firebase-message')

                last_event = DataPoint.objects.filter(source_reference=source_reference, generator_definition=generator_definition).filter(secondary_query).order_by('-created').first()
                last_alert = DataSourceAlert.objects.filter(data_source=source, generator_identifier=GENERATOR, active=True).order_by('-created').first()

                alert_name = None
                alert_details = {}
                alert_level = 'info'

                if last_event is not None:
                    delta = now - last_event.created

                    when = last_event.created.astimezone(here_tz)

                    if delta.total_seconds() > CRITICAL_LEVEL:
                        alert_name = 'Push Notifications Delayed'
                        alert_details['message'] = 'Device not received push notifications since ' + when.strftime('%H:%M on %b %d, %Y') + '.'
                        alert_level = 'critical'
                    elif delta.total_seconds() > WARNING_LEVEL:
                        alert_name = 'Push Notifications Delayed'
                        alert_details['message'] = 'Device not received push notifications since ' + when.strftime('%H:%M on %b %d, %Y') + '.'
                        alert_level = 'warning'
                else:
                    alert_name = 'Push Notifications Never Received'
                    alert_details['message'] = 'Device has never received push notifications.'

                if alert_name is not None:
                    if last_alert is None or last_alert.alert_name != alert_name or last_alert.alert_level != alert_level:
                        if last_alert is not None:
                            last_alert.active = False
                            last_alert.updated = timezone.now()
                            last_alert.save()

                        new_alert = DataSourceAlert(alert_name=alert_name, data_source=source, generator_identifier=GENERATOR)
                        new_alert.alert_level = alert_level
                        new_alert.update_alert_details(alert_details)
                        new_alert.created = timezone.now()
                        new_alert.updated = timezone.now()
                        new_alert.active = True

                        new_alert.save()
                    else:
                        last_alert.updated = timezone.now()
                        last_alert.update_alert_details(alert_details)

                        last_alert.save()
                elif last_alert is not None:
                    last_alert.updated = timezone.now()
                    last_alert.active = False

                    last_alert.save()
