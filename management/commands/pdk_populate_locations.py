# -*- coding: utf-8 -*-
# pylint: disable=no-member,line-too-long

import importlib
import os

from django.conf import settings
from django.core.management.base import BaseCommand

from ...decorators import handle_lock
from ...models import DataPoint

class Command(BaseCommand):
    help = 'Populates empty DataPoint.generated_at field with location for points containing location data.'

    def add_arguments(self, parser):
        pass

    @handle_lock()
    def handle(self, *args, **options): # pylint: disable=too-many-locals,too-many-branches,too-many-statements
        os.umask(000)

        can_populate = {}

        pending = DataPoint.objects.filter(generated_at=None)

        for point in pending:
            identifier = point.generator_identifier

            extract_method = can_populate.get(identifier, None)

            if extract_method is None:
                for app in settings.INSTALLED_APPS:
                    try:
                        pdk_api = importlib.import_module(app + '.pdk_api')

                        extract_method = pdk_api.extract_location_method(identifier)

                        if extract_method is not None:
                            extract_method(point)

                            can_populate[identifier] = extract_method
                    except ImportError:
                        pass
                    except AttributeError:
                        pass
                if extract_method is None:
                    can_populate[identifier] = False
            elif extract_method is not False:
                extract_method(point)
