# pylint: disable=no-member, line-too-long, too-many-lines, super-with-arguments, useless-object-inheritance, bad-option-value, invalid-name, too-many-instance-attributes

import calendar
import datetime
import importlib
import inspect
import json
import random
import string
import sys

from urllib.parse import urlparse, urlunsplit

from packaging.version import Version

import arrow
import requests

import django

from django.conf import settings
from django.core.checks import Warning, register # pylint: disable=redefined-builtin
from django.core.exceptions import MultipleObjectsReturned, ObjectDoesNotExist
from django.db import connection
from django.db.models import Q, QuerySet, JSONField
from django.db.models.signals import post_delete, pre_save, post_save
from django.dispatch.dispatcher import receiver
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify

from django.contrib.auth import get_user_model
from django.contrib.gis.db import models

from .data_bundle import DataBundle, DataBundleProcessingTrace
from .data_point import DataPoint
from .data_server import DataServer
from .data_source import DataSource, DataSourceReference

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

@register()
def check_prettyjson_installed(app_configs, **kwargs): # pylint: disable=unused-argument
    errors = []

    if ('prettyjson' in settings.INSTALLED_APPS) is False:
        error = Warning('"prettyjson" not found in settings.INSTALLED_APPS', hint='Add "prettyjson" to settings.INSTALLED_APPS.', obj=None, id='passive_data_kit.W001')
        errors.append(error)

    return errors

@register()
def check_python3_6(app_configs, **kwargs): # pylint: disable=unused-argument
    errors = []

    if sys.version_info < (3, 7): # Fall back to coarse file locking on Python 3.6 and lower
        error = Warning('Python 3.6 (or lower) detected', hint='Python 3.6 (or lower) detected. Some standard features will revert to alternative implementations that may not be appropriate for all deployments (such as database locking falling back to file locking). Validate that this is acceptable and add this warning to SILENCED_SYSTEM_CHECKS.', obj=None, id='passive_data_kit.W002')
        errors.append(error)

    return errors

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

    configuration_json = JSONField()

    evaluate_order = models.IntegerField(default=1)

    is_valid = models.BooleanField(default=False)
    is_enabled = models.BooleanField(default=True)

    def configuration(self):
        return self.configuration_json

    def __str__(self):
        return str(self.name)

class AppConfigurationVersion(models.Model):
    class Meta: # pylint: disable=too-few-public-methods, old-style-class, no-init
        ordering = ['-updated',]

    configuration = models.ForeignKey(AppConfiguration, null=True, related_name='versions', on_delete=models.SET_NULL)
    creator = models.ForeignKey(get_user_model(), null=True, blank=True, on_delete=models.SET_NULL)

    name = models.CharField(max_length=1024)
    id_pattern = models.CharField(max_length=1024, db_index=True)
    context_pattern = models.CharField(max_length=1024, default='.*', db_index=True)

    configuration_json = JSONField()

    evaluate_order = models.IntegerField(default=1)

    is_valid = models.BooleanField(default=False)
    is_enabled = models.BooleanField(default=True)

    updated = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return '%s - %s (%s)' % (self.configuration, self.updated, self.creator)

    def get_absolute_url(self):
        return '/admin/passive_data_kit/appconfigurationversion/%s/change' % self.pk

    def restore_version(self):
        self.configuration.name = self.name
        self.configuration.id_pattern = self.id_pattern
        self.configuration.context_pattern = self.context_pattern
        self.configuration.configuration_json = self.configuration_json
        self.configuration.evaluate_order = self.evaluate_order
        self.configuration.is_valid = self.is_valid
        self.configuration.is_enabled = self.is_enabled

        self.configuration.save()

@receiver(pre_save, sender=AppConfiguration)
def create_version_update_updated(sender, instance, **kwargs): # pylint: disable=unused-argument
    instance.updated = timezone.now()

    new_version = AppConfigurationVersion()

    new_version.name = instance.name
    new_version.id_pattern = instance.id_pattern
    new_version.context_pattern = instance.context_pattern
    new_version.configuration_json = instance.configuration_json
    new_version.evaluate_order = instance.evaluate_order
    new_version.is_valid = instance.is_valid
    new_version.is_enabled = instance.is_enabled
    new_version.updated = instance.updated
    new_version.creator = get_requested_user()

    new_version.save()

@receiver(post_save, sender=AppConfiguration) # Added to attach version that could not be attached due to unsaved DialogScript in pre_save signal.
def attach_version_update_updated(sender, instance, **kwargs): # pylint: disable=unused-argument
    config_versions = AppConfigurationVersion.objects.filter(configuration=None, name=instance.name, configuration_json=instance.configuration_json)

    for config_version in config_versions:
        config_version.configuration = instance
        config_version.save()

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


class DataFile(models.Model):
    data_point = models.ForeignKey(DataPoint, related_name='data_files', null=True, blank=True, on_delete=models.CASCADE)
    data_bundle = models.ForeignKey(DataBundle, related_name='data_files', null=True, blank=True, on_delete=models.SET_NULL)

    identifier = models.CharField(max_length=256, db_index=True)
    content_type = models.CharField(max_length=256, db_index=True)
    content_file = models.FileField(upload_to='data_files')


class DataSourceGroup(models.Model):
    name = models.CharField(max_length=1024, db_index=True)

    suppress_alerts = models.BooleanField(default=False)

    def __str__(self):
        return str(self.name)

    def refresh_performance_metadata(self):
        for member in self.sources.all():
            member.refresh_performance_metadata()


class DataSourceAlert(models.Model):
    alert_name = models.CharField(max_length=1024)
    alert_level = models.CharField(max_length=64, choices=ALERT_LEVEL_CHOICES, default='info', db_index=True)

    alert_details = JSONField()

    data_source = models.ForeignKey(DataSource, related_name='alerts', on_delete=models.CASCADE)
    generator_identifier = models.CharField(max_length=1024, null=True, blank=True)

    created = models.DateTimeField(db_index=True)
    updated = models.DateTimeField(null=True, blank=True, db_index=True)

    active = models.BooleanField(default=True, db_index=True)

    def fetch_alert_details(self):
        return self.alert_details

    def update_alert_details(self, details):
        self.alert_details = details

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

    alert.alert_details = alert_details

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

        batch_request.parameters = params

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

    parameters = JSONField()

    report = models.FileField(upload_to='pdk_reports', null=True, blank=True)

    def get_absolute_url(self):
        return reverse('pdk_download_report', args=[self.pk])

    def fetch_parameters(self):
        return self.parameters

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

    parameters = JSONField()

    def fetch_parameters(self):
        return self.parameters

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

    destination.parameters = parameters

class ReportJobBatchRequest(models.Model):
    requester = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)

    requested = models.DateTimeField(db_index=True)
    started = models.DateTimeField(db_index=True, null=True, blank=True)
    completed = models.DateTimeField(db_index=True, null=True, blank=True)

    priority = models.IntegerField(default=0)

    parameters = JSONField()

    def process(self): # pylint: disable=too-many-locals, too-many-branches, too-many-statements
        self.started = timezone.now()
        self.save()

        target_size = 5000000

        try:
            target_size = settings.PDK_TARGET_SIZE
        except AttributeError:
            pass

        params = None

        params = self.parameters

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

                job.parameters = job_params

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

                    job.parameters = job_params

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

                job.parameters = job_params

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

    job.parameters = parameters

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

class DeviceModel(models.Model):
    model = models.CharField(max_length=1024, unique=True)
    manufacturer = models.CharField(max_length=1024)

    reference = models.URLField(max_length=(1024 * 1024), null=True, blank=True)

    notes = models.TextField(max_length=(1024 * 1024), null=True, blank=True)

    def __str__(self):
        return str(self.model + ' (' + self.manufacturer + ')')

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
