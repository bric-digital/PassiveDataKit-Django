# pylint: disable=line-too-long, no-member

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from ...decorators import handle_lock

from ...models import DataPoint, DataSource, DataSourceAlert, DataSourceReference, DataGeneratorDefinition

GENERATOR = 'pdk-device-free-space'
CRITICAL_LEVEL = 256 * 1024 * 1024
WARNING_LEVEL = 1024 * 1024 * 1024

class Command(BaseCommand):
    help = 'Runs the battery level status check to alert when battery level is low.'

    @handle_lock
    def handle(self, *args, **options): # pylint: disable=too-many-branches, too-many-statements
        try:
            if (GENERATOR in settings.PDK_ENABLED_CHECKS) is False:
                DataSourceAlert.objects.filter(generator_identifier=GENERATOR, active=True).update(active=False)

                return
        except AttributeError:
            print('Did not find PDK_ENABLED_CHECKS in Django settings. Please define with a list of generators with status checks to enable.')
            print('Example: PDK_ENABLED_CHECKS = (\'' + GENERATOR + '\',)')

        for source in DataSource.objects.all(): # pylint: disable=too-many-nested-blocks
            if source.should_suppress_alerts():
                DataSourceAlert.objects.filter(data_source=source, generator_identifier=GENERATOR, active=True).update(active=False)
            else:
                source_reference = DataSourceReference.reference_for_source(source.identifier)
                generator_definition = DataGeneratorDefinition.definition_for_identifier('pdk-system-status')

                last_status = DataPoint.objects.filter(source_reference=source_reference, generator_definition=generator_definition).order_by('-created').first()
                last_alert = DataSourceAlert.objects.filter(data_source=source, generator_identifier=GENERATOR, active=True).order_by('-created').first()

                alert_name = None
                alert_details = {}
                alert_level = 'info'

                if last_status is not None:
                    properties = last_status.fetch_properties()

                    if 'storage_available' in properties:
                        if properties['storage_available'] < CRITICAL_LEVEL:
                            alert_name = 'Available Space Critical'
                            alert_details['message'] = 'Device only has ' + '{:,}'.format(int(properties['storage_available'] // (1024 * 1024))) + ' MB free.'
                            alert_level = 'critical'
                        elif properties['storage_available'] < WARNING_LEVEL:
                            alert_name = 'Available Space Low'
                            alert_details['message'] = 'Device only has ' + '{:,}'.format(int(properties['storage_available'] // (1024 * 1024))) + ' MB free.'
                            alert_level = 'warning'

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
                    else:
                        alert_name = 'No Disk Usage Logged'
                        alert_details['message'] = 'No disk usage has been logged for this device yet.'

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
                else:
                    alert_name = 'No Disk Usage Logged'
                    alert_details['message'] = 'No disk usage has been logged for this device yet.'

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
