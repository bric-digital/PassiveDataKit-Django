# pylint: disable=line-too-long, no-member

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from ...decorators import handle_lock

from ...models import DataPoint, DataSource, DataSourceAlert, DataSourceReference, DataGeneratorDefinition

GENERATOR = 'pdk-web-extension'

GENERATOR_EVENTS = (
    'pdk-web-visit',
    'pdk-web-added-blacklist-term',
    'pdk-web-delete-visits',
    'pdk-web-deleted-blacklist-term',
    'pdk-web-opened-extension',
    'pdk-web-search',
    'pdk-web-show-main-tab',
    'pdk-web-show-review-tab',
    'pdk-web-show-settings-tab',
    'pdk-web-upload-visit',
)

WARNING_DAYS = 7
CRITICAL_DAYS = 14

class Command(BaseCommand):
    help = 'Determines if users have successfully installed and used the web extension.'

    @handle_lock()
    def handle(self, *args, **options): # pylint: disable=too-many-branches, too-many-statements, too-many-locals
        try:
            if (GENERATOR in settings.PDK_ENABLED_CHECKS) is False:
                DataSourceAlert.objects.filter(generator_identifier=GENERATOR, active=True).update(active=False)

                return
        except AttributeError:
            print('Did not find PDK_ENABLED_CHECKS in Django settings. Please define with a list of generators with status checks to enable.')
            print('Example: PDK_ENABLED_CHECKS = (\'' + GENERATOR + '\',)')

        event_query = None

        for event in GENERATOR_EVENTS:
            definition = DataGeneratorDefinition.objects.filter(generator_identifier=event).first()

            if definition is not None:
                if event_query is None:
                    event_query = Q(generator_definition=definition)
                else:
                    event_query = event_query | Q(generator_definition=definition) # pylint: disable=unsupported-binary-operation

        for source in DataSource.objects.all(): # pylint: disable=too-many-nested-blocks
            source_reference = DataSourceReference.objects.filter(source=source.identifier).first()

            if source_reference is not None:
                if source.should_suppress_alerts():
                    DataSourceAlert.objects.filter(data_source=source, generator_identifier=GENERATOR, active=True).update(active=False)
                else:
                    last_web_event = None

                    for event in GENERATOR_EVENTS:
                        definition = DataGeneratorDefinition.objects.filter(generator_identifier=event).first()
                        web_event = DataPoint.objects.filter(source_reference=source_reference, generator_definition=definition).order_by('-created').first()

                        if web_event is not None:
                            if last_web_event is None:
                                last_web_event = web_event
                            elif web_event.created > last_web_event.created:
                                last_web_event = web_event

                    last_alert = DataSourceAlert.objects.filter(data_source=source, generator_identifier=GENERATOR, active=True).order_by('-created').first()

                    alert_name = None
                    alert_details = {}
                    alert_level = 'info'

                    if last_web_event is None:
                        alert_name = 'Browser extension not installed'
                        alert_details['message'] = 'There is no evidence that the browser extension was successfully installed.'
                        alert_level = 'critical'
                    else:
                        definition = DataGeneratorDefinition.objects.filter(generator_identifier='pdk-web-upload-visit').first()

                        last_upload = DataPoint.objects.filter(source_reference=source_reference, generator_definition=definition).order_by('-created').first()

                        if last_upload is None:
                            alert_name = 'No Web Visits Uploaded'
                            alert_details['message'] = 'The user has not yet uploaded any web visits from the extension.'
                            alert_level = 'critical'
                        else:
                            days_since = (timezone.now() - last_upload.created).days

                            if days_since > CRITICAL_DAYS:
                                alert_name = 'No Recent Web Visits Uploaded'
                                alert_details['message'] = 'No web visits have been uploaded in the past ' + str(days_since) + ' days.'
                                alert_level = 'critical'
                            elif days_since > WARNING_DAYS:
                                alert_name = 'No Recent Web Visits Uploaded'
                                alert_details['message'] = 'No web visits have been uploaded in the past ' + str(days_since) + ' days.'
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
