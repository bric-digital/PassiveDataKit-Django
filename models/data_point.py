import pytz

class DataPointQuerySet(QuerySet):
    def count(self):
        postgres_engines = ("postgis", "postgresql", "django_postgrespool")
        engine = settings.DATABASES[self.db]["ENGINE"].split(".")[-1]

        is_postgres = engine.startswith(postgres_engines)

        # In Django 1.9 the query.having property was removed and the
        # query.where property will be truthy if either where or having
        # clauses are present. In earlier versions these were two separate
        # properties query.where and query.having

        if Version(django.get_version()) >= Version('1.9'):
            is_filtered = self.query.where
        else:
            is_filtered = self.query.where or self.query.having

        # print('WHERE: ' + str(self.query.where))

        if not is_postgres or is_filtered:
            return super(DataPointQuerySet, self).count()

        data_point_count = DataServerMetadatum.objects.filter(key=TOTAL_DATA_POINT_COUNT_DATUM).first()

        if data_point_count is None:
            data_count = super(DataPointQuerySet, self).count()

            DataServerMetadatum.objects.create(key=TOTAL_DATA_POINT_COUNT_DATUM, value=str(data_count))

            return data_count

        return int(data_point_count.value)

class DataPointManager(models.Manager):
    def get_queryset(self):
        return DataPointQuerySet(self.model, using=self._db)

    def sources(self): # pylint: disable=no-self-use
        sources = []

        for reference in DataSourceReference.objects.all():
            if reference.source.strip():
                sources.append(reference.source)

        return sources

    def generator_identifiers_for_source(self, source, since=None): # pylint: disable=invalid-name, no-self-use
        identifiers = []

        source_reference = DataSourceReference.reference_for_source(source)

        for definition in DataGeneratorDefinition.objects.all():
            if since is not None:
                if DataPoint.objects.filter(source_reference=source_reference, generator_definition=definition, created__gte=since).count() > 0:
                    identifiers.append(definition.generator_identifier)
            else:
                key = LATEST_POINT_DATUM + ': ' + source + '/' + definition.generator_identifier
                latest_point_datum = DataServerMetadatum.objects.filter(key=key).first()

                missing_key = MISSING_POINT_DATUM + ': ' + source + '/' + definition.generator_identifier
                missing_point_datum = DataServerMetadatum.objects.filter(key=missing_key).first()

                if latest_point_datum is not None:
                    identifiers.append(definition.generator_identifier)

                    if missing_point_datum is not None:
                        DataServerMetadatum.objects.filter(key=key).delete()
                else:
                    if missing_point_datum is not None:
                        pass
                    else:
                        if DataPoint.objects.filter(source_reference=source_reference, generator_definition=definition).count() > 0:
                            identifiers.append(definition.generator_identifier)
                        else:
                            missing_point_datum = DataServerMetadatum(key=missing_key, last_updated=timezone.now(), value='Not found')
                            missing_point_datum.save()

        return identifiers

    def generator_identifiers(self): # pylint: disable=invalid-name, no-self-use
        identifiers = []

        for definition in DataGeneratorDefinition.objects.all():
            identifiers.append(definition.generator_identifier)

        return identifiers

    def latest_point(self, source, identifier): # pylint: disable=no-self-use
        key = LATEST_POINT_DATUM + ': ' + source + '/' + identifier

        latest_point_datum = DataServerMetadatum.objects.filter(key=key).first()

        point = None

        if latest_point_datum is not None:
            point = DataPoint.objects.filter(pk=int(latest_point_datum.value)).first()

        if point is None:
            source_reference = DataSourceReference.objects.filter(source=source).first()

            if source_reference is None:
                return None

            if identifier == 'pdk-data-frequency':
                data_source = DataSource.objects.filter(identifier=source).first()

                if data_source is not None:
                    point = data_source.latest_point()

                if point is None:
                    if DataPoint.objects.filter(source_reference=source_reference).count() > 0:
                        point = DataPoint.objects.filter(source_reference=source_reference).order_by('-pk').first()
            else:
                generator_definition = DataGeneratorDefinition.objects.filter(generator_identifier=identifier).first()

                if generator_definition is None:
                    return None

                if DataPoint.objects.filter(source_reference=source_reference, generator_definition=generator_definition).count() > 0:
                    point = DataPoint.objects.filter(source_reference=source_reference, generator_definition=generator_definition).order_by('-pk').first()

            if point is not None:
                latest_point_datum = DataServerMetadatum.objects.filter(key=key).first()

                if latest_point_datum is None:
                    latest_point_datum = DataServerMetadatum(key=key)

                latest_point_datum.value = str(point.pk)
                latest_point_datum.save()

        return point

    def set_latest_point(self, source, identifier, new_point):
        latest_point = self.latest_point(source, identifier)

        if latest_point is None or latest_point.created < new_point.created:
            key = LATEST_POINT_DATUM + ': ' + source + '/' + identifier

            latest_point_datum = DataServerMetadatum.objects.filter(key=key).first()

            if latest_point_datum is None:
                latest_point_datum = DataServerMetadatum(key=key)

            latest_point_datum.value = str(new_point.pk)
            latest_point_datum.save()

    def create_data_point(self, identifier, source, payload, user_agent='Passive Data Kit Server', created=None, skip_save=False, skip_extract_secondary_identifier=False): # pylint: disable=no-self-use, too-many-arguments, invalid-name, too-many-positional-arguments
        now = timezone.now()

        if created is None:
            created = now

        payload['passive-data-metadata'] = {
            'timestamp': calendar.timegm(created.utctimetuple()),
            'generator-id': identifier,
            'generator': identifier + ': ' + user_agent,
            'source': source
        }

        point = DataPoint(source=source, generator=payload['passive-data-metadata']['generator'], generator_identifier=identifier)

        point.properties = payload

        point.user_agent = user_agent
        point.recorded = now

        point.created = created

        point.fetch_generator_definition(skip_save)
        point.fetch_source_reference(skip_save)

        if skip_extract_secondary_identifier is False:
            point.fetch_secondary_identifier()

        if skip_save is False:
            point.save()

            point.fetch_secondary_identifier()

            data_point_count = DataServerMetadatum.objects.filter(key=TOTAL_DATA_POINT_COUNT_DATUM).first()

            if data_point_count is None:
                count = DataPoint.objects.all().count()

                data_point_count = DataServerMetadatum(key=TOTAL_DATA_POINT_COUNT_DATUM)

                data_point_count.value = str(count)
                data_point_count.save()
            else:
                count = int(data_point_count.value)

                count += 1

                data_point_count.value = str(count)
                data_point_count.save()

        return point

    def clean_definition(self, data_point): # pylint: disable=invalid-name
        if data_point is not None:
            point_json = json.dumps(data_point)

            # TODO: Include other checks

            while r'\u0000' in point_json:
                point_json = point_json.replace(r'\u0000', '')

            data_point = json.loads(point_json)

        return data_point

    def is_valid_definition(self, data_point):
        if data_point is None:
            return False

        if isinstance(data_point, dict) is False:
            return False

        pdk_metadata = data_point.get('passive-data-metadata', None)

        if pdk_metadata is None:
            return False

        if pdk_metadata.get('source', None) is None:
            return False

        if pdk_metadata.get('generator', None) is None:
            return False

        return True

    def prepare_definition(self, data_point):
        source = data_point.get('passive-data-metadata', {}).get('source', '')

        if source == '':
            source = 'missing-source'

        try:
            source = settings.PDK_RENAME_SOURCE(source)

            data_point['passive-data-metadata']['source'] = source
        except AttributeError:
            pass

        try:
            settings.PDK_INSPECT_DATA_POINT_AT_INGEST(bundle_point)
        except AttributeError:
            pass

        return bundle_point

    def prepare_object(self, definition, recorded=timezone.now, bundle=None):
        point = DataPoint(recorded=recorded)

        metadata = definition.get('passive-data-metadata', {})

        if bundle is not None:
            metadata['encrypted_transmission'] = bundle.encrypted

        point.source = metadata.get('source', '-')

        point.generator = metadata.get('generator', 'unknown-generator')

        generator_id = metadata.get('generator-id', None)

        if generator_id is not None:
            point.generator_identifier = generator_id

        latitude = metadata.get('latitude', definition.get('latitude', None))
        latitude = metadata.get('longitude', definition.get('longitude', None))

        if latitude is not None and longitude is not None:
            point.generated_at = GEOSGeometry('POINT(%s %s)' % (longitude, latitude))

        point.created = datetime.datetime.fromtimestamp(metadata.get('timestamp', 0), tz=pytz.utc)

        point.properties = definition

        point.fetch_secondary_identifier(skip_save=True, properties=definition)
        point.fetch_user_agent(skip_save=True, properties=definition)
        point.fetch_generator_definition(skip_save=True)
        point.fetch_source_reference(skip_save=True)

        return point

class DataPoint(models.Model): # pylint: disable=too-many-instance-attributes
    class Meta(object): # pylint: disable=old-style-class, no-init, too-few-public-methods, bad-option-value
        indexes = [
            models.Index(fields=['created', 'source_reference']),
            models.Index(fields=['recorded', 'generator_definition']),
        ]

    objects = DataPointManager()

    source = models.CharField(max_length=1024)
    generator = models.CharField(max_length=1024)
    generator_identifier = models.CharField(max_length=1024, db_index=True, default='unknown-generator')
    secondary_identifier = models.CharField(max_length=1024, null=True, blank=True)

    generator_definition = models.ForeignKey(DataGeneratorDefinition, on_delete=models.SET_NULL, related_name='data_points', null=True, blank=True)
    source_reference = models.ForeignKey(DataSourceReference, on_delete=models.SET_NULL, related_name='data_points', null=True, blank=True)

    user_agent = models.CharField(max_length=1024, null=True, blank=True)

    created = models.DateTimeField(db_index=True)
    generated_at = models.PointField(null=True, blank=True)

    server_generated = models.BooleanField(default=False, db_index=True)

    recorded = models.DateTimeField(db_index=True)

    properties = JSONField()

    def fetch_secondary_identifier(self, skip_save=False, properties=None):
        if self.secondary_identifier is not None:
            return self.secondary_identifier

        if properties is None:
            properties = self.fetch_properties()

        generator_name = generator_slugify(self.generator_identifier)

        for app in settings.INSTALLED_APPS:
            try:
                generator = importlib.import_module(app + '.generators.' + generator_name)

                identifier = generator.extract_secondary_identifier(properties)

                if identifier is not None:
                    self.secondary_identifier = identifier

                    if skip_save is False:
                        self.save()

                return self.secondary_identifier
            except ImportError:
                pass
            except AttributeError:
                pass

        return None

    def fetch_properties(self):
        try:
            return self.cached_properties # pylint: disable=access-member-before-definition
        except AttributeError:
            pass

        self.cached_properties = self.properties # pylint: disable=attribute-defined-outside-init

        return self.cached_properties

    def fetch_user_agent(self, skip_save=False, properties=None):
        if self.user_agent is None:
            if properties is None:
                properties = self.fetch_properties()

            if 'passive-data-metadata' in properties:
                if 'generator' in properties['passive-data-metadata']:
                    tokens = properties['passive-data-metadata']['generator'].split(':', 1)

                    self.user_agent = tokens[-1].strip()

                    if skip_save is False:
                        self.save()

        return self.user_agent

    def fetch_generator_definition(self, skip_save=False):
        if self.generator_identifier in CACHED_GENERATOR_DEFINITIONS:
            generator_definition = CACHED_GENERATOR_DEFINITIONS[self.generator_identifier]
        else:
            generator_definition = DataGeneratorDefinition.objects.filter(generator_identifier=self.generator_identifier).first()

            if generator_definition is None:
                generator_definition = DataGeneratorDefinition(generator_identifier=self.generator_identifier, name=self.generator_identifier)
                generator_definition.save()

            CACHED_GENERATOR_DEFINITIONS[self.generator_identifier] = generator_definition

        if self.generator_definition_id is None:
            self.generator_definition = CACHED_GENERATOR_DEFINITIONS[self.generator_identifier]

            if skip_save is False:
                self.save()

        return CACHED_GENERATOR_DEFINITIONS[self.generator_identifier]

    def fetch_source_reference(self, skip_save=False):
        if self.source in CACHED_SOURCE_REFERENCES:
            source_reference = CACHED_SOURCE_REFERENCES[self.source]
        else:
            source_reference = DataSourceReference.objects.filter(source=self.source).order_by('pk').first()

            if source_reference is None:
                source_reference = DataSourceReference(source=self.source)
                source_reference.save()

                source = DataSource.objects.filter(identifier=self.source).first()

                if source is None:
                    source = DataSource.objects.create(identifier=self.source, name=self.source)

            CACHED_SOURCE_REFERENCES[self.source] = source_reference

        if self.source_reference_id is None:
            self.source_reference = CACHED_SOURCE_REFERENCES[self.source]

            if skip_save is False:
                self.save()

        return CACHED_SOURCE_REFERENCES[self.source]

    def attach_files(self, point_property, bundle_files):
        if isinstance(point_property, dict):
            for key, value in point_property.items():
                if isinstance(value, str) and key.endswith('@'):
                    for bundle_file in bundle_files.filter(identifier=value):
                        bundle_file.data_point = self
                        bundle_file.save()
                elif isinstance(value, list) and key.endswith('@'):
                    for identifier in value:
                        for bundle_file in bundle_files.filter(identifier=identifier):
                            bundle_file.data_point = self
                            bundle_file.save()
                else:
                    self.attach_files(value, bundle_files)
        elif isinstance(point_property, list):
            for value in point_property:
                self.attach_files(value, bundle_files)

    def fetch_bundle_files(self, bundle_files):
        properties = self.fetch_properties()

        self.attach_files(properties, bundle_files)

    def save(self, force_insert=False, force_update=False, using=None, update_fields=None): # pylint: disable=arguments-differ
        if self.generator_identifier != 'pdk-virtual-point':
            super(DataPoint, self).save(force_insert=force_insert, force_update=force_update, using=using, update_fields=update_fields)
        else:
            raise TypeError('Attempting to save pdk-virtual-point.')

    def __str__(self):
        return '%s (%s - id:%s)' % (self.generator_identifier, self.source, self.pk)

@receiver(post_save, sender=DataPoint)
def data_point_post_save(sender, instance, *args, **kwargs): # pylint: disable=unused-argument
    try:
        del instance.cached_properties
    except AttributeError:
        pass

