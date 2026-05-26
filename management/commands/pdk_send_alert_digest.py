# pylint: disable=no-member,line-too-long

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.core.management.base import BaseCommand
from django.template.loader import render_to_string

from ...decorators import handle_lock
from ...models import DataSource

class Command(BaseCommand):
    help = 'Sends an e-mail of current alerts to site monitors.'

    def add_arguments(self, parser):
        pass

    @handle_lock()
    def handle(self, *args, **options):
        recipients = []

        try:
            recipients = settings.PDK_ALERT_DIGEST_RECIPIENTS
        except AttributeError:
            pass

        if recipients:
            context = {}

            context['sources'] = {}

            for source in DataSource.objects.all():
                if source.alerts.filter(active=True).count() > 0:
                    context['sources'][source.identifier] = list(source.alerts.filter(active=True))

            subject = render_to_string('mail/pdk_alert_digest_mail_subject.txt', context)
            body = render_to_string('mail/pdk_alert_digest_mail_body.txt', context)

            while '\n\n\n' in body:
                body = body.replace('\n\n\n', '\n\n')

            message = EmailMultiAlternatives(subject, body, settings.AUTOMATED_EMAIL_FROM_ADDRESS, recipients)
            message.send()
