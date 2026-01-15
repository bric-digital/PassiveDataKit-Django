# pylint: disable=no-member, line-too-long, too-many-lines, super-with-arguments, useless-object-inheritance, bad-option-value, invalid-name

from __future__ import print_function
from __future__ import division

from builtins import str # pylint: disable=redefined-builtin
from builtins import range # pylint: disable=redefined-builtin
from builtins import object # pylint: disable=redefined-builtin

import calendar
import datetime
import inspect
import json
import random
import string
import sys

import importlib

from packaging.version import Version
from future import standard_library
from past.utils import old_div

import arrow
import requests

from six import python_2_unicode_compatible

import django

from django.conf import settings
from django.core.checks import Warning, register # pylint: disable=redefined-builtin
from django.core.exceptions import MultipleObjectsReturned, ObjectDoesNotExist
from django.db import connection
from django.db.models import Q, QuerySet
from django.db.models.signals import post_delete, pre_save, post_save
from django.dispatch.dispatcher import receiver
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify

from django.contrib.auth import get_user_model
from django.contrib.gis.db import models

try:
    from urllib.parse import urlparse, urlunsplit
except ImportError:
    from urlparse import urlparse, urlunsplit

if sys.version_info[0] > 2:
    from django.db.models import JSONField # pylint: disable=no-name-in-module
else:
    from django.contrib.postgres.fields import JSONField

standard_library.install_aliases()

DB_SUPPORTS_JSON = None
TOTAL_DATA_POINT_COUNT_DATUM = 'Total Data Point Count'
SOURCES_DATUM = 'Data Point Sources'
SOURCE_GENERATORS_DATUM = 'Data Point Source Generator Identifiers'
LATEST_POINT_DATUM = 'Latest Data Point'
MISSING_POINT_DATUM = 'Missing Data Point'
GENERATORS_DATUM = 'Data Point Generators'

ALERT_LEVEL_CHOICES = (
    ('info', 'Informative'),
    ('warning', 'Warning'),
    ('critical', 'Critical'),
)

DEVICE_ISSUE_STATE_CHOICES = (
    ('opened', 'Opened'),
    ('in-progress', 'In Progress'),
    ('resolved', 'Resolved'),
    ('wont-fix', 'Won\'t Fix'),
)

METADATA_WINDOW_DAYS = 60

try:
    METADATA_WINDOW_DAYS = settings.PDK_METADATA_WINDOW_DAYS
except AttributeError:
    pass

CACHED_GENERATOR_DEFINITIONS = {}
CACHED_SOURCE_REFERENCES = {}

COMPRESSION_CHOICES = (
    ('none', 'None'),
    ('gzip', 'Gzip'),
)

def get_requested_user():
    for frame_record in inspect.stack():
        if frame_record[3] == 'get_response':
            request = frame_record[0].f_locals['request']
            return request.user

    return None

def generator_label(identifier):
    for app in settings.INSTALLED_APPS:
        try:
            pdk_api = importlib.import_module(app + '.pdk_api')

            name = pdk_api.name_for_generator(identifier)

            if name is not None:
                return name
        except ImportError:
            pass
        except AttributeError:
            pass

    return identifier


def generator_slugify(str_obj):
    return slugify(str_obj.replace('.', ' ')).replace('-', '_')


def install_supports_jsonfield():
    global DB_SUPPORTS_JSON # pylint: disable=global-statement

    if DB_SUPPORTS_JSON is None:
        try:
            DB_SUPPORTS_JSON = connection.pg_version >= 90400
        except AttributeError:
            DB_SUPPORTS_JSON = False

        try:
            DB_SUPPORTS_JSON = (settings.PDK_DISABLE_NATIVE_JSON_FIELDS is False)
        except AttributeError:
            pass

    return DB_SUPPORTS_JSON

@register()
def check_prettyjson_installed(app_configs, **kwargs): # pylint: disable=unused-argument
    errors = []

    if ('prettyjson' in settings.INSTALLED_APPS) is False:
        error = Warning('"prettyjson" not found in settings.INSTALLED_APPS', hint='Add "prettyjson" to settings.INSTALLED_APPS.', obj=None, id='passive_data_kit.W001')
        errors.append(error)

    return errors

@python_2_unicode_compatible
class AppConfiguration(models.Model):
    class Meta(object): # pylint: disable=old-style-class, no-init, too-few-public-methods, bad-option-value
        indexes = [
            models.Index(fields=['is_valid', 'is_enabled']),
            models.Index(fields=['is_valid', 'is_enabled', 'evaluate_order']),
        ]

        ordering = ['name']

    name = models.CharField(max_length=1024)
    id_pattern = models.CharField(max_length=1024, db_index=True)
    context_pattern = models.CharField(max_length=1024, default='.*', db_index=True)

    if install_supports_jsonfield():
        configuration_json = JSONField()
    else:
        configuration_json = models.TextField(max_length=(32 * 1024 * 1024 * 1024))

    evaluate_order = models.IntegerField(default=1)

    is_valid = models.BooleanField(default=False)
    is_enabled = models.BooleanField(default=True)

    def configuration(self):
        if install_supports_jsonfield():
            return self.configuration_json

        return json.loads(self.configuration_json)

    def __str__(self):
        return str(self.name)

@python_2_unicode_compatible
class AppConfigurationVersion(models.Model):
    class Meta: # pylint: disable=too-few-public-methods, old-style-class, no-init
        ordering = ['-updated',]

    configuration = models.ForeignKey(AppConfiguration, null=True, related_name='versions', on_delete=models.SET_NULL)
    creator = models.ForeignKey(get_user_model(), null=True, blank=True, on_delete=models.SET_NULL)

    name = models.CharField(max_length=1024)
    id_pattern = models.CharField(max_length=1024, db_index=True)
    context_pattern = models.CharField(max_length=1024, default='.*', db_index=True)

    if install_supports_jsonfield():
        configuration_json = JSONField()
    else:
        configuration_json = models.TextField(max_length=(32 * 1024 * 1024 * 1024))

    evaluate_order = models.IntegerField(default=1)

    is_valid = models.BooleanField(default=False)
    is_enabled = models.BooleanField(default=True)

    created = models.DateTimeField(null=True, blank=True)
    updated = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return '%s - %s (%s)' % (self.configuration, self.created, self.creator)

    def get_absolute_url(self):
        return '/admin/passive_data_kit/appconfigurationversion/%s/change' % self.pk

    def restore_version(self):
        self.configuration.name = self.name
        self.configuration.configuration = self.configuration
        self.configuration.id_pattern = self.id_pattern
        self.configuration.context_pattern = self.context_pattern
        self.configuration.configuration_json = self.configuration_json
        self.configuration.evaluate_order = self.evaluate_order
        self.configuration.is_valid = self.is_valid
        self.configuration.is_enabled = self.is_enabled
        self.configuration.created = self.created
        self.configuration.updated = self.updated

        self.configuration.save()

@receiver(pre_save, sender=AppConfiguration)
def create_version_update_updated(sender, instance, **kwargs): # pylint: disable=unused-argument
    instance.updated = timezone.now()

    new_version = AppConfigurationVersion()

    new_version.configuration = instance.configuration
    new_version.name = instance.name
    new_version.id_pattern = instance.id_pattern
    new_version.context_pattern = instance.context_pattern
    new_version.configuration_json = instance.configuration_json
    new_version.evaluate_order = instance.evaluate_order
    new_version.is_valid = instance.is_valid
    new_version.is_enabled = instance.is_enabled
    new_version.created = instance.created
    new_version.updated = instance.updated
    new_version.updated = get_requested_user()

    new_version.save()

@receiver(post_save, sender=AppConfiguration) # Added to attach version that could not be attached due to unsaved DialogScript in pre_save signal.
def attach_version_update_updated(sender, instance, **kwargs): # pylint: disable=unused-argument
    config_versions = AppConfigurationVersion.objects.filter(configuration=None, name=instance.name, configuration_json=instance.configuration_json)

    for config_version in config_versions:
        config_version.configuration = instance
        config_version.save()

@python_2_unicode_compatible
class DataGeneratorDefinition(models.Model):
    generator_identifier = models.CharField(max_length=1024)

    name = models.CharField(max_length=1024)
    description = models.TextField(max_length=(1024 * 1024), null=True, blank=True)

    def __str__(self):
        return str(self.generator_identifier)

    @classmethod
    def definition_for_identifier(cls, generator_identifier):
        try:
            return DataGeneratorDefinition.objects.get(generator_identifier=generator_identifier)
        except MultipleObjectsReturned:
            first_definition = DataGeneratorDefinition.objects.filter(generator_identifier=generator_identifier).order_by('pk').first()

            other_definitions = DataGeneratorDefinition.objects.filter(generator_identifier=generator_identifier).order_by('pk')[1:]

            to_delete = []

            for definition in other_definitions:
                DataPoint.objects.filter(generator_definition=definition).update(generator_definition=first_definition)

                to_delete.append(definition)

            for definition in to_delete:
                definition.delete()

            return first_definition
        except ObjectDoesNotExist:
            definition = DataGeneratorDefinition(generator_identifier=generator_identifier)
            definition.save()

            return definition


@python_2_unicode_compatible
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

        if install_supports_jsonfield():
            point.properties = payload
        else:
            point.properties = json.dumps(payload, indent=2)

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


@python_2_unicode_compatible # pylint: disable=too-many-instance-attributes
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

    if install_supports_jsonfield():
        properties = JSONField()
    else:
        properties = models.TextField(max_length=(32 * 1024 * 1024 * 1024))

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

        if install_supports_jsonfield():
            self.cached_properties = self.properties # pylint: disable=attribute-defined-outside-init
        else:
            self.cached_properties = json.loads(self.properties) # pylint: disable=attribute-defined-outside-init

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

class DataServerMetadatum(models.Model):
    class Meta(object): # pylint: disable=old-style-class, no-init, too-few-public-methods, bad-option-value
        verbose_name_plural = "data server metadata"

    key = models.CharField(max_length=1024, db_index=True)
    value = models.TextField(max_length=1048576)
    last_updated = models.DateTimeField(null=True, blank=True)

    def formatted_value(self): # pylint: disable=no-self-use
        return '%s = %s' % (self.key, self.value)

@receiver(pre_save, sender=DataServerMetadatum)
def data_server_metadatum_pre_save(sender, instance, *args, **kwargs): # pylint: disable=unused-argument
    instance.last_updated = timezone.now()


class DataBundle(models.Model):
    recorded = models.DateTimeField()

    errored = models.DateTimeField(null=True, blank=True)

    if install_supports_jsonfield():
        properties = JSONField()
    else:
        properties = models.TextField(max_length=(32 * 1024 * 1024 * 1024))

    processed = models.BooleanField(default=False, db_index=True)
    encrypted = models.BooleanField(default=False)
    compression = models.CharField(max_length=128, choices=COMPRESSION_CHOICES, default='none')


class DataFile(models.Model):
    data_point = models.ForeignKey(DataPoint, related_name='data_files', null=True, blank=True, on_delete=models.CASCADE)
    data_bundle = models.ForeignKey(DataBundle, related_name='data_files', null=True, blank=True, on_delete=models.SET_NULL)

    identifier = models.CharField(max_length=256, db_index=True)
    content_type = models.CharField(max_length=256, db_index=True)
    content_file = models.FileField(upload_to='data_files')


@python_2_unicode_compatible
class DataSourceGroup(models.Model):
    name = models.CharField(max_length=1024, db_index=True)

    suppress_alerts = models.BooleanField(default=False)

    def __str__(self):
        return str(self.name)

    def refresh_performance_metadata(self):
        for member in self.sources.all():
            member.refresh_performance_metadata()

@python_2_unicode_compatible
class DataServer(models.Model):
    name = models.CharField(max_length=1024, unique=True)
    upload_url = models.URLField(max_length=1024, unique=True)
    source_metadata_url = models.URLField(max_length=1024, null=True, blank=True)

    request_key = models.CharField(max_length=1024, default='', null=True, blank=True)

    def __str__(self):
        return str(self.name)

class DataSourceManager(models.Manager): # pylint: disable=too-few-public-methods
    def sources(self): # pylint: disable=no-self-use
        source_list = []

        for source in DataSource.objects.all():
            if (source.identifier in source_list) is False:
                source_list.append(source.identifier)

        return source_list


@python_2_unicode_compatible
class DataSource(models.Model):
    objects = DataSourceManager()

    identifier = models.CharField(max_length=1024, db_index=True)
    name = models.CharField(max_length=1024, db_index=True, unique=True)

    group = models.ForeignKey(DataSourceGroup, related_name='sources', blank=True, null=True, on_delete=models.SET_NULL)

    suppress_alerts = models.BooleanField(default=False)

    if install_supports_jsonfield():
        performance_metadata = JSONField(null=True, blank=True)
    else:
        performance_metadata = models.TextField(max_length=(32 * 1024 * 1024 * 1024), null=True, blank=True)

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
            if install_supports_jsonfield():
                return self.performance_metadata

            if self.performance_metadata.strip():
                return json.loads(self.performance_metadata)

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
                    metadata['point_frequency'] = old_div(metadata['point_count'], seconds)

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

            if install_supports_jsonfield():
                self.performance_metadata = metadata
            else:
                self.performance_metadata = json.dumps(metadata, indent=2)

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

                if install_supports_jsonfield():
                    self.performance_metadata = metadata
                else:
                    self.performance_metadata = json.dumps(metadata, indent=2)

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

                    if install_supports_jsonfield():
                        self.performance_metadata = metadata
                    else:
                        self.performance_metadata = json.dumps(metadata, indent=2)

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

                    if install_supports_jsonfield():
                        self.performance_metadata = metadata
                    else:
                        self.performance_metadata = json.dumps(metadata, indent=2)

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

                    if install_supports_jsonfield():
                        self.performance_metadata = metadata
                    else:
                        self.performance_metadata = json.dumps(metadata, indent=2)

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


class DataSourceAlert(models.Model):
    alert_name = models.CharField(max_length=1024)
    alert_level = models.CharField(max_length=64, choices=ALERT_LEVEL_CHOICES, default='info', db_index=True)

    if install_supports_jsonfield():
        alert_details = JSONField()
    else:
        alert_details = models.TextField(max_length=(32 * 1024 * 1024 * 1024))

    data_source = models.ForeignKey(DataSource, related_name='alerts', on_delete=models.CASCADE)
    generator_identifier = models.CharField(max_length=1024, null=True, blank=True)

    created = models.DateTimeField(db_index=True)
    updated = models.DateTimeField(null=True, blank=True, db_index=True)

    active = models.BooleanField(default=True, db_index=True)

    def fetch_alert_details(self):
        if install_supports_jsonfield():
            return self.alert_details

        return json.loads(self.alert_details)

    def update_alert_details(self, details):
        if install_supports_jsonfield():
            self.alert_details = details
        else:
            self.alert_details = json.dumps(details, indent=2)

    def fetch_definition(self):
        definition = {
            'name': self.alert_name,
            'level': self.alert_level,
            'source': self.data_source.identifier,
            'generator': self.generator_identifier,
            'created': self.created.isoformat(),
            'updated': self.updated.isoformat(),
            'active': self.active
        }

        definition['details'] = self.fetch_alert_details()

        return definition

@receiver(pre_save, sender=DataSourceAlert)
def data_source_alert_pre_save_handler(sender, **kwargs): # pylint: disable=unused-argument, invalid-name
    alert = kwargs['instance']

    alert_details = alert.alert_details

    while isinstance(alert_details, dict) is False:
        alert_details = json.loads(alert_details)

    if install_supports_jsonfield():
        alert.alert_details = alert_details
    else:
        alert.alert_details = json.dumps(alert_details, indent=2)

class DataPointVisualization(models.Model):
    source = models.CharField(max_length=1024, db_index=True)
    generator_identifier = models.CharField(max_length=1024, db_index=True)
    last_updated = models.DateTimeField(db_index=True)


class ReportJobManager(models.Manager): # pylint: disable=too-few-public-methods
    def create_jobs(self, user, sources, generators, export_raw=False, data_start=None, data_end=None, date_type='created'): # pylint: disable=too-many-locals, too-many-branches, too-many-statements, no-self-use, too-many-arguments, too-many-positional-arguments
        batch_request = ReportJobBatchRequest(requester=user, requested=timezone.now())

        params = {}

        params['sources'] = sources
        params['generators'] = list(set(generators))
        params['export_raw'] = export_raw
        params['data_start'] = data_start
        params['data_end'] = data_end
        params['date_type'] = date_type

        if install_supports_jsonfield():
            batch_request.parameters = params
        else:
            batch_request.parameters = json.dumps(params, indent=2)

        batch_request.save()

class ReportJob(models.Model):
    objects = ReportJobManager()

    requester = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)

    requested = models.DateTimeField(db_index=True)
    started = models.DateTimeField(db_index=True, null=True, blank=True)
    completed = models.DateTimeField(db_index=True, null=True, blank=True)

    sequence_index = models.IntegerField(default=1)
    sequence_count = models.IntegerField(default=1)

    priority = models.IntegerField(default=0)

    if install_supports_jsonfield():
        parameters = JSONField()
    else:
        parameters = models.TextField(max_length=(32 * 1024 * 1024 * 1024))

    report = models.FileField(upload_to='pdk_reports', null=True, blank=True)

    def get_absolute_url(self):
        return reverse('pdk_download_report', args=[self.pk])

    def fetch_parameters(self):
        if install_supports_jsonfield():
            return self.parameters

        return json.loads(self.parameters)

@receiver(post_delete, sender=ReportJob)
def report_job_post_delete_handler(sender, **kwargs): # pylint: disable=unused-argument
    job = kwargs['instance']

    try:
        storage, path = job.report.storage, job.report.path
        storage.delete(path)
    except ValueError:
        pass


class ReportDestination(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, related_name='pdk_report_destinations', on_delete=models.CASCADE)

    destination = models.CharField(max_length=4096)
    description = models.CharField(max_length=4096, null=True, blank=True)

    if install_supports_jsonfield():
        parameters = JSONField()
    else:
        parameters = models.TextField(max_length=(32 * 1024 * 1024 * 1024))

    def fetch_parameters(self):
        if install_supports_jsonfield():
            return self.parameters

        return json.loads(self.parameters)

    def transmit(self, report, report_file):
        for app in settings.INSTALLED_APPS:
            try:
                pdk_api = importlib.import_module(app + '.pdk_api')

                pdk_api.send_to_destination(self, report, report_file)
            except ImportError:
                pass
            except AttributeError:
                pass

    def upload_file_contents(self, path, contents):
        for app in settings.INSTALLED_APPS:
            try:
                pdk_api = importlib.import_module(app + '.pdk_api')

                pdk_api.upload_file_contents(self, path, contents)
            except ImportError:
                pass
            except AttributeError:
                pass

@receiver(pre_save, sender=ReportDestination)
def report_destination_pre_save_handler(sender, **kwargs): # pylint: disable=unused-argument, invalid-name
    destination = kwargs['instance']

    parameters = destination.parameters

    while isinstance(parameters, dict) is False:
        parameters = json.loads(parameters)

    if install_supports_jsonfield():
        destination.parameters = parameters
    else:
        destination.parameters = json.dumps(parameters, indent=2)

class ReportJobBatchRequest(models.Model):
    requester = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)

    requested = models.DateTimeField(db_index=True)
    started = models.DateTimeField(db_index=True, null=True, blank=True)
    completed = models.DateTimeField(db_index=True, null=True, blank=True)

    priority = models.IntegerField(default=0)

    if install_supports_jsonfield():
        parameters = JSONField()
    else:
        parameters = models.TextField(max_length=(32 * 1024 * 1024 * 1024))

    def process(self): # pylint: disable=too-many-locals, too-many-branches, too-many-statements
        self.started = timezone.now()
        self.save()

        target_size = 5000000

        try:
            target_size = settings.PDK_TARGET_SIZE
        except AttributeError:
            pass

        params = None

        if install_supports_jsonfield():
            params = self.parameters
        else:
            params = json.loads(self.parameters)

        if ('sources' in params) is False:
            params['sources'] = sorted(DataPoint.objects.sources())

        sources = sorted(params['sources'], reverse=True)

        pending_jobs = []
        requested = timezone.now()

        try:
            sources_per_job = settings.PDK_SOURCES_PER_REPORT_JOB

            page = 0

            while page < len(sources):
                pending_sources = sources[page:(page + sources_per_job)]

                job = ReportJob(requester=self.requester, requested=requested, priority=self.priority)

                job_params = {}

                job_params['sources'] = sorted(pending_sources)
                job_params['generators'] = params['generators']
                job_params['raw_data'] = params['export_raw']
                job_params['data_start'] = params['data_start']
                job_params['data_end'] = params['data_end']
                job_params['date_type'] = params['date_type']

                if 'prefix' in params:
                    job_params['prefix'] = params['prefix']

                if 'suffix' in params:
                    job_params['suffix'] = params['suffix']

                if 'email_subject' in params:
                    job_params['email_subject'] = params['email_subject']

                if 'path' in params:
                    job_params['path'] = params['path']

                if install_supports_jsonfield():
                    job.parameters = job_params
                else:
                    job.parameters = json.dumps(job_params, indent=2)

                pending_jobs.append(job)

                page += sources_per_job
        except AttributeError:
            generator_query = None

            for generator in params['generators']: # pylint: disable=too-many-nested-blocks
                had_extras = False

                for app in settings.INSTALLED_APPS:
                    try:
                        pdk_api = importlib.import_module(app + '.pdk_api')

                        try:
                            other_generators = pdk_api.generators_for_extra_generator(generator)

                            for other_generator in other_generators:
                                definition = DataGeneratorDefinition.objects.filter(generator_identifier=other_generator).first()

                                if definition is not None:
                                    if generator_query is None:
                                        generator_query = Q(generator_definition=definition)
                                    else:
                                        generator_query = generator_query |  Q(generator_definition=definition) # pylint: disable=unsupported-binary-operation

                                had_extras = True
                        except TypeError as exception:
                            print('Verify that ' + app + '.' + generator + ' implements all generators_for_extra_generator arguments!')
                            raise exception
                    except ImportError:
                        pass
                    except AttributeError:
                        pass

                if had_extras is False:
                    definition = DataGeneratorDefinition.objects.filter(generator_identifier=generator).first()

                    if generator_query is None:
                        generator_query = Q(generator_definition=definition)
                    else:
                        generator_query = generator_query | Q(generator_definition=definition) # pylint: disable=unsupported-binary-operation

            report_size = 0

            report_sources = []

            while sources:
                source = sources.pop()

                query_size = 0

                source_reference = DataSourceReference.objects.filter(source=source).first()

                if source_reference is not None:
                    source_query = Q(source_reference=source_reference) & generator_query

                    query_size = DataPoint.objects.filter(source_query).count()
                if report_size == 0 or (report_size + query_size) < target_size:
                    report_sources.append(source)

                    report_size += query_size
                else:
                    job = ReportJob(requester=self.requester, requested=requested, priority=self.priority)

                    job_params = {}

                    job_params['sources'] = report_sources
                    job_params['generators'] = params['generators']
                    job_params['raw_data'] = params['export_raw']
                    job_params['data_start'] = params['data_start']
                    job_params['data_end'] = params['data_end']

                    if 'prefix' in params:
                        job_params['prefix'] = params['prefix']

                    if 'suffix' in params:
                        job_params['suffix'] = params['suffix']

                    if 'email_subject' in params:
                        job_params['email_subject'] = params['email_subject']

                    if install_supports_jsonfield():
                        job.parameters = job_params
                    else:
                        job.parameters = json.dumps(job_params, indent=2)

                    pending_jobs.append(job)

                    report_size = query_size
                    report_sources = [source]

            if report_sources:
                job = ReportJob(requester=self.requester, requested=requested, priority=self.priority)

                job_params = {}

                job_params['sources'] = report_sources
                job_params['generators'] = params['generators']
                job_params['raw_data'] = params['export_raw']
                job_params['data_start'] = params['data_start']
                job_params['data_end'] = params['data_end']

                if 'prefix' in params:
                    job_params['prefix'] = params['prefix']

                if 'suffix' in params:
                    job_params['suffix'] = params['suffix']

                if 'email_subject' in params:
                    job_params['email_subject'] = params['email_subject']

                if install_supports_jsonfield():
                    job.parameters = job_params
                else:
                    job.parameters = json.dumps(job_params, indent=2)

                pending_jobs.append(job)

                source_query = None
                report_size = 0
                report_sources = []

        index = 1

        for job in pending_jobs:
            job.sequence_index = index
            job.sequence_count = len(pending_jobs)
            job.save()

            index += 1

        self.completed = timezone.now()
        self.save()

@receiver(pre_save, sender=ReportJobBatchRequest)
def report_job_batch_request_pre_save_handler(sender, **kwargs): # pylint: disable=unused-argument, invalid-name
    job = kwargs['instance']

    parameters = job.parameters

    while isinstance(parameters, dict) is False:
        parameters = json.loads(parameters)

    if install_supports_jsonfield():
        job.parameters = parameters
    else:
        job.parameters = json.dumps(parameters, indent=2)

class DataServerApiToken(models.Model):
    class Meta(object): # pylint: disable=old-style-class, no-init, too-few-public-methods, bad-option-value
        verbose_name = "data server API token"
        verbose_name_plural = "data server API tokens"

    user = models.ForeignKey(get_user_model(), related_name='pdk_api_tokens', on_delete=models.CASCADE)
    token = models.CharField(max_length=1024, null=True, blank=True)
    expires = models.DateTimeField(null=True, blank=True)

    def fetch_token(self):
        if (self.token is not None) and (self.token.strip() != ''):
            return self.token

        self.token = ''.join(random.SystemRandom().choice(string.ascii_letters + string.digits) for _ in range(64))
        self.save()

        return self.token

class DataServerAccessRequest(models.Model):
    user_identifier = models.CharField(max_length=4096, db_index=True)
    request_type = models.CharField(max_length=4096, db_index=True)
    request_time = models.DateTimeField(db_index=True)
    request_metadata = models.TextField(max_length=(32 * 1024 * 1024 * 1024))
    successful = models.BooleanField(default=True, db_index=True)

class DataServerAccessRequestPending(models.Model):
    user_identifier = models.CharField(max_length=4096)
    request_type = models.CharField(max_length=4096)
    request_time = models.DateTimeField()
    request_metadata = models.TextField(max_length=(32 * 1024 * 1024 * 1024))
    successful = models.BooleanField(default=True)

    processed = models.BooleanField(default=False)

    def process(self):
        request = DataServerAccessRequest()

        request.user_identifier = self.user_identifier
        request.request_type = self.request_type
        request.request_type = self.request_type
        request.request_time = self.request_time
        request.request_metadata = self.request_metadata
        request.successful = self.successful

        request.save()

        self.processed = True
        self.save()

@python_2_unicode_compatible
class DeviceModel(models.Model):
    model = models.CharField(max_length=1024, unique=True)
    manufacturer = models.CharField(max_length=1024)

    reference = models.URLField(max_length=(1024 * 1024), null=True, blank=True)

    notes = models.TextField(max_length=(1024 * 1024), null=True, blank=True)

    def __str__(self):
        return str(self.model + ' (' + self.manufacturer + ')')

@python_2_unicode_compatible
class Device(models.Model):
    source = models.ForeignKey(DataSource, related_name='devices', on_delete=models.CASCADE)

    model = models.ForeignKey(DeviceModel, related_name='devices', on_delete=models.CASCADE)
    platform = models.CharField(max_length=(1024 * 1024), null=True, blank=True)

    notes = models.TextField(max_length=(1024 * 1024), null=True, blank=True)

    def __str__(self):
        return str(str(self.source.identifier) + ': ' + str(self.model.model) + ' (' + str(self.platform) + ')')

    def populate_device(self):
        user_agent = self.source.latest_user_agent()

        if user_agent is not None:
            tokens = user_agent.split('(')[1].split(';')

            self.platform = tokens[0]

            model_name = tokens[1][1:-1]

            model = DeviceModel.objects.filter(model=model_name).first()

            if model is None:
                model = DeviceModel(model=model_name, manufacturer='Unknown')
                model.save()

            self.model = model
        else:
            model = DeviceModel.objects.filter(model='Unknown').first()

            if model is None:
                model = DeviceModel(model='Unknown', manufacturer='Unknown')
                model.save()

            self.model = model

        self.save()

class DeviceIssue(models.Model): # pylint: disable=too-many-instance-attributes
    device = models.ForeignKey(Device, related_name='issues', on_delete=models.CASCADE)

    state = models.CharField(max_length=1024, choices=DEVICE_ISSUE_STATE_CHOICES, default='opened')
    created = models.DateTimeField()
    last_updated = models.DateTimeField()

    user_agent = models.CharField(max_length=(1024 * 1024), null=True, blank=True)
    platform = models.CharField(max_length=(1024 * 1024), null=True, blank=True)
    app = models.CharField(max_length=(1024 * 1024), null=True, blank=True)
    version = models.CharField(max_length=(1024 * 1024), null=True, blank=True)
    device_model = models.CharField(max_length=(1024 * 1024), null=True, blank=True)

    description = models.TextField(max_length=(1024 * 1024), null=True, blank=True)
    tags = models.CharField(max_length=(1024 * 1024), null=True, blank=True)

    stability_related = models.BooleanField(default=False)
    uptime_related = models.BooleanField(default=False)
    responsiveness_related = models.BooleanField(default=False)
    battery_use_related = models.BooleanField(default=False)
    power_management_related = models.BooleanField(default=False)
    data_volume_related = models.BooleanField(default=False)
    data_quality_related = models.BooleanField(default=False)
    bandwidth_related = models.BooleanField(default=False)
    storage_related = models.BooleanField(default=False)
    configuration_related = models.BooleanField(default=False)
    location_related = models.BooleanField(default=False)
    correctness_related = models.BooleanField(default=False)
    ui_related = models.BooleanField(default=False)
    device_performance_related = models.BooleanField(default=False)
    device_stability_related = models.BooleanField(default=False)

@receiver(pre_save, sender=DeviceIssue)
def device_issue_pre_save_handler(sender, **kwargs): # pylint: disable=unused-argument, invalid-name
    issue = kwargs['instance']

    if issue.platform is None:
        issue.platform = issue.device.platform

    if issue.user_agent is None:
        issue.user_agent = issue.device.source.latest_user_agent()

class PermissionsSupport(models.Model):
    class Meta: # pylint: disable=too-few-public-methods, old-style-class, no-init, bad-option-value
        managed = False
        default_permissions = ()

        permissions = (
            ('passive_data_kit_dashboard_access', 'Access Passive Data Kit dashboard'),
            ('passive_data_kit_export_access', 'Create Passive Data Kit data exports'),
        )
