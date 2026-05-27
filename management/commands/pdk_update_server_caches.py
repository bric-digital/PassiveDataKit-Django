# pylint: disable=no-member

import json

from django.core.management.base import BaseCommand

from ...decorators import handle_lock
from ...models import DataServerMetadatum, DataGeneratorDefinition, DataSourceReference, \
                      GENERATORS_DATUM, SOURCES_DATUM

class Command(BaseCommand):
    help = 'Updates server caches to speed up operations'

    @handle_lock()
    def handle(self, *args, **options):
        identifiers = DataServerMetadatum.objects.filter(key=GENERATORS_DATUM).first()

        if identifiers is None:
            identifiers = DataServerMetadatum(key=GENERATORS_DATUM)

        seen_identifiers = []

        for definition in DataGeneratorDefinition.objects.all():
            seen_identifiers.append(definition.generator_identifier)

        identifiers.value = json.dumps(seen_identifiers, indent=2)

        identifiers.save()

        sources = DataServerMetadatum.objects.filter(key=SOURCES_DATUM).first()

        if sources is None:
            sources = DataServerMetadatum(key=SOURCES_DATUM)

        seen_sources = []

        for source in DataSourceReference.objects.all():
            seen_sources.append(source.source)

        sources.value = json.dumps(seen_sources, indent=2)

        sources.save()
