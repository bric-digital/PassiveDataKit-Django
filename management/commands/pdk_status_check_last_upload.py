# pylint: disable=line-too-long, no-member

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from passive_data_kit.decorators import handle_lock

from passive_data_kit.models import DataPoint, DataSource, DataSourceAlert, DataSourceReference

DATA_CHECK = 'pdk-data-upload'

CRITICAL_HOURS = 24
WARNING_HOURS = 4

class Command(BaseCommand):
    help = 'Generates an alert if time has elapsed without an upload.'


    @handle_lock
    def handle(self, *args, **options): # pylint: disable=too-many-branches, too-many-statements, too-many-locals
        try:
            if (DATA_CHECK in settings.PDK_ENABLED_CHECKS) is False:
                DataSourceAlert.objects.filter(generator_identifier=DATA_CHECK, active=True).update(active=False)

                return
        except AttributeError:
            print('Did not find PDK_ENABLED_CHECKS in Django settings. Please define with a list of generators with status checks to enable.')
            print('Example: PDK_ENABLED_CHECKS = (\'' + DATA_CHECK + '\',)')

        now = timezone.now()

        for source in DataSource.objects.all(): # pylint: disable=too-many-nested-blocks
            if source.should_suppress_alerts():
                DataSourceAlert.objects.filter(data_source=source, generator_identifier=DATA_CHECK, active=True).update(active=False)
            else:
                source_reference = DataSourceReference.reference_for_source(source.identifier)

                last_alert = DataSourceAlert.objects.filter(data_source=source, generator_identifier=DATA_CHECK, active=True).order_by('-created').first()

                last_upload = DataPoint.objects.filter(source_reference=source_reference).order_by('-created').first()

                alert_name = None
                alert_details = {}
                alert_level = 'info'

                if last_upload is not None:
                    delta = now - last_upload.created

                    if delta.total_seconds() >= CRITICAL_HOURS * 3600:
                        alert_name = 'Data upload is critically overdue'

                        hours = delta.total_seconds() // 3600

                        if hours < 24:
                            alert_details['message'] = 'Latest data was uploaded ' + "{0:.2f}".format(hours) + ' hours ago.'
                        else:
                            days = hours // 24

                            alert_details['message'] = 'Latest data was uploaded ' + "{0:.2f}".format(days) + ' days ago.'
                        alert_level = 'critical'
                    elif delta.total_seconds() >= WARNING_HOURS * 3600:
                        alert_name = 'Data upload is overdue'

                        hours = delta.total_seconds() // 3600

                        if hours < 24:
                            alert_details['message'] = 'Latest data was uploaded ' + "{0:.2f}".format(hours) + ' hours ago.'
                        else:
                            days = hours // 24\

                            alert_details['message'] = 'Latest data was uploaded ' + "{0:.2f}".format(days) + ' days ago.'

                        alert_level = 'warning'

                    if alert_name is not None:
                        if last_alert is None or last_alert.alert_name != alert_name or last_alert.alert_level != alert_level:
                            if last_alert is not None:
                                last_alert.active = False
                                last_alert.updated = timezone.now()
                                last_alert.save()

                            new_alert = DataSourceAlert(alert_name=alert_name, data_source=source, generator_identifier=DATA_CHECK)
                            new_alert.alert_level = alert_level
                            new_alert.update_alert_details(alert_details)
                            new_alert.created = timezone.now()
                            new_alert.updated = timezone.now()
                            new_alert.active = True

                            new_alert.save()
                        else:
                            last_alert.alert_name = alert_name
                            last_alert.updated = timezone.now()
                            last_alert.update_alert_details(alert_details)

                            last_alert.save()
                    elif last_alert is not None:
                        last_alert.updated = timezone.now()
                        last_alert.active = False

                        last_alert.save()
                else:
                    alert_name = 'Data never uploaded'
                    alert_level = 'critical'
                    alert_details['message'] = 'No data has been uploaded from this user.'

                    if last_alert is None or last_alert.alert_name != alert_name or last_alert.alert_level != alert_level:
                        if last_alert is not None:
                            last_alert.active = False
                            last_alert.updated = timezone.now()
                            last_alert.save()

                        new_alert = DataSourceAlert(alert_name=alert_name, data_source=source, generator_identifier=DATA_CHECK)
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
