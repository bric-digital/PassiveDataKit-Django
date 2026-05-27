from django.core.management import call_command, get_commands
from django.core.management.base import BaseCommand

from ...decorators import handle_lock, log_scheduled_event

class Command(BaseCommand):
    help = 'Runs data sanity checks to generate any alerts for potential data issues.'

    @handle_lock()
    @log_scheduled_event
    def handle(self, *args, **options):
        command_names = list(get_commands().keys())

        for command_name in command_names:
            if command_name.startswith('pdk_status_check_'):
                call_command(command_name)
