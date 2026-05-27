from .data_server import DataServer

class DataSourceManager(models.Manager): # pylint: disable=too-few-public-methods
    cached_urls = {}

    def sources(self): # pylint: disable=no-self-use
        source_list = []

        for source in DataSource.objects.all():
            if (source.identifier in source_list) is False:
                source_list.append(source.identifier)

        return source_list

    def url_for_identifier(self, source):
        server_url = self.cached_urls.get(source, None)

        if server_url is not None:
            return server_url

        source_obj = self.filter(identifier=source).first()

        if source_obj is not None:
            if source_obj.server is not None:
                server_url = source_obj.server.upload_url
        else:
            if source is not None:
                source_obj = DataSource.objects.create_new_source(source)

        self.sources[source] = server_url

        return server_url

    def create_new_source(self, identifier):
        source_obj = self.create(identifier=identifier, name=identifier)
        source_obj.join_default_group()
        source_obj.set_default_server()

        return source_obj

class DataSource(models.Model):
    objects = DataSourceManager()

    identifier = models.CharField(max_length=1024, db_index=True)
    name = models.CharField(max_length=1024, db_index=True, unique=True)

    group = models.ForeignKey(DataSourceGroup, related_name='sources', blank=True, null=True, on_delete=models.SET_NULL)

    suppress_alerts = models.BooleanField(default=False)

    performance_metadata = JSONField(null=True, blank=True)

    performance_metadata_updated = models.DateTimeField(db_index=True, null=True, blank=True)

    server = models.ForeignKey(DataServer, related_name='sources', null=True, blank=True, on_delete=models.SET_NULL)

    configuration = models.ForeignKey(AppConfiguration, related_name='sources', null=True, blank=True, on_delete=models.SET_NULL)

    def __str__(self):
        return self.name + ' (' + self.identifier + ')'

    def details_url(self):
        url = reverse('pdk_source', args=[self.identifier])

        if self.server is None:
            return url

        components = urlparse(self.server.upload_url)

        return urlunsplit((components.scheme, components.netloc, url, '', ''))

    def fetch_definition(self):
        definition = {
            'name': self.name,
            'identifier': self.identifier,
            'latest_user_agent': self.latest_user_agent(),
            'suppresses_alerts': self.should_suppress_alerts(),
            'point_count': self.point_count(),
        }

        if self.group is not None:
            definition['group'] = self.group.name
        else:
            definition['group'] = None

        for app in settings.INSTALLED_APPS:
            try:
                pdk_api = importlib.import_module(app + '.pdk_api')

                definition = pdk_api.annotate_source_definition(self, definition)
            except ImportError:
                pass
            except AttributeError:
                pass

        return definition

    def fetch_performance_metadata(self):
        if self.performance_metadata is not None:
            return self.performance_metadata

        return {}

    def should_suppress_alerts(self, skip_server_check=False):
        if self.suppress_alerts:
            return True

        if skip_server_check is False:
            if self.server is not None:
                return True

        if self.group and self.group.suppress_alerts:
            return True

        return False

    def fetch_source_reference(self):
        source_reference = DataSourceReference.objects.filter(source=self.identifier).first()

        if source_reference is None:
            source_reference = DataSourceReference(source=self.identifier)
            source_reference.save()

        return source_reference

    def update_performance_metadata(self): # pylint: disable=too-many-branches, too-many-statements, too-many-locals
        if self.server is None:
            source_reference = self.fetch_source_reference()

            metadata = self.fetch_performance_metadata()

            now = timezone.now()

            window_start = now - datetime.timedelta(days=METADATA_WINDOW_DAYS)

            day_ago = timezone.now() - datetime.timedelta(days=1)

            DataPoint.objects.filter(source_reference=source_reference, server_generated=False, user_agent__icontains='Passive Data Kit Server', created__gte=day_ago).update(server_generated=True)

            # Update latest_point

            latest_point = self.latest_point()

            query = Q(source_reference=source_reference)

            if latest_point is not None:
                query = query & Q(created__gt=latest_point.created)
            else:
                latest_point = DataPoint.objects.filter(source_reference=source_reference).order_by('-created').first()

            latest_count = DataPoint.objects.filter(query).count()

            latest_index = 0

            point = None

            while latest_index < latest_count:
                for late_point in DataPoint.objects.filter(query).order_by('-created')[latest_index:(latest_index + 500)]:
                    if late_point.server_generated is False:
                        user_agent = late_point.fetch_user_agent()

                        if ('Passive Data Kit Server' in user_agent) is False:
                            point = late_point

                            break

                if point is not None:
                    break

                latest_index += 500

            while point is not None:
                user_agent = point.fetch_user_agent()

                if ('Passive Data Kit Server' in user_agent) is False:
                    metadata['latest_point'] = point.pk

                    latest_point = point

                    point = None
                else:
                    point = DataPoint.objects.filter(source_reference=source_reference, server_generated=False, created__lt=point.created).order_by('-created').first()

                    if point is not None:
                        metadata['latest_point'] = point.pk

            if latest_point is not None:
                metadata['user_agent'] = latest_point.fetch_user_agent()
                metadata['latest_point_created'] = calendar.timegm(latest_point.created.timetuple())

            latest_point_recorded = self.latest_point_recorded()

            query = Q(source_reference=source_reference)

            if latest_point_recorded is not None:
                query = query & Q(recorded__gt=latest_point_recorded.recorded)

            point = None

            user_count = DataPoint.objects.filter(query).count()

            user_index = 0

            while user_index < user_count:
                for user_point in DataPoint.objects.filter(query).order_by('-recorded')[user_index:(user_index + 500)]:
                    if user_point.server_generated is False:
                        user_agent = user_point.fetch_user_agent()

                        if ('Passive Data Kit Server' in user_agent) is False:
                            point = user_point

                            break

                if point is not None:
                    break

                user_index += 500

            while point is not None:
                user_agent = point.fetch_user_agent()

                if ('Passive Data Kit Server' in user_agent) is False:
                    metadata['latest_point_recorded'] = point.pk

                    latest_point_recorded = point

                    point = None
                else:
                    point = DataPoint.objects.filter(source_reference=source_reference, server_generated=False, recorded__lt=point.recorded).order_by('-recorded').first()

                    if point is not None:
                        metadata['latest_point_recorded'] = point.pk

            if latest_point_recorded is not None:
                metadata['latest_point_recorded_time'] = calendar.timegm(latest_point_recorded.recorded.timetuple())

            # Update point_count

            metadata['point_count'] = DataPoint.objects.filter(source_reference=source_reference, created__gte=window_start).count()

            # Update point_frequency

            metadata['point_frequency'] = 0

            if metadata['point_count'] > 1:
                earliest_point = DataPoint.objects.filter(source_reference=source_reference, created__gte=window_start).order_by('created').first()

                seconds = (latest_point.created - earliest_point.created).total_seconds()

                if seconds > 0:
                    metadata['point_frequency'] =metadata['point_count'] // seconds

            generators = []

            identifiers = DataPoint.objects.generator_identifiers_for_source(self.identifier, since=window_start)

            for identifier in identifiers:
                definition = DataGeneratorDefinition.definition_for_identifier(identifier)

                generator = {}

                generator['identifier'] = identifier
                generator['source'] = self.identifier
                generator['label'] = generator_label(identifier)

                generator['points_count'] = DataPoint.objects.filter(source_reference=source_reference, created__gte=window_start, generator_definition=definition).count()

                last_recorded = DataPoint.objects.filter(source_reference=source_reference, generator_definition=definition, created__gte=window_start).order_by('-recorded').first()

                if last_recorded is not None:
                    first_point = DataPoint.objects.filter(source_reference=source_reference, generator_definition=definition, created__gte=window_start).order_by('created').first()

                    last_point = DataPoint.objects.filter(source_reference=source_reference, generator_definition=definition, created__gte=window_start).order_by('-created').first()

                    generator['last_recorded'] = calendar.timegm(last_recorded.recorded.timetuple())
                    generator['first_created'] = calendar.timegm(first_point.created.timetuple())
                    generator['last_created'] = calendar.timegm(last_point.created.timetuple())

                    duration = (last_point.created - first_point.created).total_seconds()

                    if generator['points_count'] > 1 and duration > 0:
                        generator['frequency'] = float(generator['points_count']) / duration
                    else:
                        generator['frequency'] = 0

                    generators.append(generator)

            metadata['generator_statistics'] = generators

            self.performance_metadata = metadata

            self.performance_metadata_updated = timezone.now()

            self.save()

        elif self.server.source_metadata_url is not None:
            payload = {
                'identifier': self.identifier,
                'request-key': self.server.request_key
            }

            identifier_post = requests.post(self.server.source_metadata_url, data=payload, timeout=120)

            if identifier_post.status_code >= 200 and identifier_post.status_code < 300:
                metadata = identifier_post.json()

                self.performance_metadata = metadata

                for app in settings.INSTALLED_APPS:
                    try:
                        pdk_api = importlib.import_module(app + '.pdk_api')

                        pdk_api.process_remote_metadata(self.identifier, metadata)
                    except ImportError:
                        pass
                    except AttributeError:
                        pass
            else:
                print('Server code ' + str(identifier_post.status_code) + ' received for request for ' + self.identifier + ' metadata from ' + self.server.source_metadata_url)

            self.performance_metadata_updated = timezone.now()

            self.save()

    def refresh_performance_metadata(self):
        self.performance_metadata_updated = None

        self.save()

    def latest_point(self):
        metadata = self.fetch_performance_metadata()

        if self.server is None:
            if 'latest_point' in metadata:
                return DataPoint.objects.filter(pk=metadata['latest_point']).first()

            source_reference = DataSourceReference.reference_for_source(self.identifier)

            if DataPoint.objects.filter(source_reference=source_reference).count() > 0: # Added for no-data condition scans of whole table for non-existent data...
                point = DataPoint.objects.filter(source_reference=source_reference).order_by('-created').first()

                if point is not None:
                    metadata['latest_point'] = point.pk

                    self.performance_metadata = metadata

                    self.save()

                    return point
        elif 'latest_point' in metadata and 'latest_point_created' in metadata:
            virtual_point = DataPoint(generator_identifier='pdk-virtual-point')
            virtual_point.pk = metadata['latest_point'] # pylint: disable=invalid-name
            virtual_point.created = arrow.get(metadata['latest_point_created']).datetime
            virtual_point.recorded = virtual_point.created

            return virtual_point

        return None

    def latest_point_recorded(self):
        metadata = self.fetch_performance_metadata()

        if self.server is None:
            if 'latest_point_recorded' in metadata:
                return DataPoint.objects.filter(pk=metadata['latest_point_recorded']).first()

            source_reference = DataSourceReference.reference_for_source(self.identifier)

            if DataPoint.objects.filter(source_reference=source_reference).count() > 0: # Added for no-data condition scans of whole table for non-existent data...
                point = DataPoint.objects.filter(source_reference=source_reference).order_by('-recorded').first()

                if point is not None:
                    metadata['latest_point_recorded'] = point.pk

                    self.performance_metadata = metadata

                    self.save()

                    return point
        elif 'latest_point_recorded' in metadata and 'latest_point_recorded_created' in metadata:
            virtual_point = DataPoint(generator_identifier='pdk-virtual-point')
            virtual_point.pk = metadata['latest_point_recorded'] # pylint: disable=invalid-name
            virtual_point.created = arrow.get(metadata['latest_point_recorded_created']).datetime
            virtual_point.recorded = virtual_point.created

            return virtual_point

        return None

    def earliest_point(self):
        metadata = self.fetch_performance_metadata()

        if self.server is None:
            if 'earliest_point' in metadata:
                return DataPoint.objects.filter(pk=metadata['earliest_point']).first()

            source_reference = DataSourceReference.reference_for_source(self.identifier)

            if DataPoint.objects.filter(source_reference=source_reference).count() > 0: # Added for no-data condition scans of whole table for non-existent data...
                point = DataPoint.objects.filter(source_reference=source_reference).order_by('created').first()

                if point is not None:
                    metadata['earliest_point'] = point.pk

                    self.performance_metadata = metadata

                    self.save()

                    return point
        elif 'earliest_point' in metadata and 'earliest_point_created' in metadata:
            virtual_point = DataPoint(generator_identifier='pdk-virtual-point')
            virtual_point.pk = metadata['earliest_point'] # pylint: disable=invalid-name
            virtual_point.created = arrow.get(metadata['earliest_point_created']).datetime
            virtual_point.recorded = virtual_point.created

            return virtual_point

        return None

    def point_count(self):
        metadata = self.fetch_performance_metadata()

        if 'point_count' in metadata:
            return metadata['point_count']

        return None

    def point_frequency(self):
        metadata = self.fetch_performance_metadata()

        if 'point_frequency' in metadata:
            return metadata['point_frequency']

        return None

    def generator_statistics(self):
        metadata = self.fetch_performance_metadata()

        if 'generator_statistics' in metadata:
            return metadata['generator_statistics']

        return []

    def latest_user_agent(self):
        if self.server is None:
            latest_point = self.latest_point()

            if latest_point is not None:
                properties = latest_point.fetch_properties()

                if 'passive-data-metadata' in properties:
                    if 'generator' in properties['passive-data-metadata']:
                        tokens = properties['passive-data-metadata']['generator'].split(':')

                        return tokens[-1].strip()
        else:
            metadata = self.fetch_performance_metadata()

            if 'user_agent' in metadata:
                return metadata['user_agent']

        return None

    def latest_point_created(self):
        if self.server is None:
            latest_point = self.latest_point()

            if latest_point is not None:
                return latest_point.created

        metadata = self.fetch_performance_metadata()

        if 'latest_point_created' in metadata:
            return datetime.datetime.utcfromtimestamp(metadata['latest_point_created'])

        return None

    def set_default_server(self, override=False):
        if self.server is None or override is True:
            self.server = DataServer.objects.default_server()
            self.save()

    def join_default_group(self):
        try:
            if settings.PDK_DEFAULT_GROUP_NAME is not None:
                group = DataSourceGroup.objects.filter(name=settings.PDK_DEFAULT_GROUP_NAME).first()

                if group is None:
                    group = DataSourceGroup(name=settings.PDK_DEFAULT_GROUP_NAME)
                    group.save()

                self.group = group

                self.save()
        except AttributeError:
            pass

class DataSourceReference(models.Model):
    source = models.CharField(max_length=1024)

    def __str__(self):
        return str(self.source)

    @classmethod
    def reference_for_source(cls, source):
        try:
            return DataSourceReference.objects.get(source=source)
        except MultipleObjectsReturned:
            first_source = DataSourceReference.objects.filter(source=source).order_by('pk').first()

            other_sources = DataSourceReference.objects.filter(source=source).order_by('pk')[1:]

            to_delete = []

            for reference in other_sources:
                DataPoint.objects.filter(source_reference=reference).update(source_reference=first_source)

                to_delete.append(reference)

            for reference in to_delete:
                reference.delete()

            return first_source
        except ObjectDoesNotExist:
            reference = DataSourceReference(source=source)
            reference.save()

            return reference
