# pylint: disable=line-too-long, no-member

import json

import iso8601

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core import serializers

from .models import AppConfiguration, AppConfigurationVersion

def import_objects(file_type, import_file):
    if file_type == 'passive_data_kit.appconfiguration':
        return import_app_configuration(import_file)

    return None

def import_app_configuration(import_file): # pylint: disable=too-many-locals,too-many-branches,too-many-statements
    user_messages = []

    with import_file.open() as file_stream:
        configurations_json = json.load(file_stream)

        configurations_imported = 0
        versions_imported = 0

        # for script_json in scripts_json: # pylint: disable=too-many-nested-blocks
        #     if script_json.get('model', None) == 'django_dialog_engine.dialogscript':
        #         identifier = script_json.get('fields', {}).get('identifier', None)

        #         if identifier is not None:
        #             script_obj = DialogScript.objects.filter(identifier=identifier).first()

        #             if script_obj is None:
        #                 script_obj = DialogScript.objects.create(identifier=identifier)
        #                 script_obj.versions.all().delete()

        #                 scripts_created += 1
        #             else:
        #                 scripts_updated += 1

        #             for field_key in script_json.get('fields', {}).keys():
        #                 field_value = script_json.get('fields', {}).get(field_key, None)

        #                 if field_key in ('created', 'updated'):
        #                     if field_value is not None:
        #                         field_value = iso8601.parse_date(field_value)

        #                 setattr(script_obj, field_key, field_value)

        #             script_obj.save()

        #             script_obj.versions.all().order_by('-pk').first().delete()

        #             DialogScriptVersion.objects.filter(dialog_script=None).delete()

        #             for version in script_json.get('versions', []):
        #                 if version.get('model', None) == 'django_dialog_engine.dialogscriptversion':
        #                     updated_str = version.get('fields', {}).get('updated', None)

        #                     updated = iso8601.parse_date(updated_str)

        #                     version_obj = DialogScriptVersion.objects.filter(dialog_script=script_obj, updated=updated).first()

        #                     if version_obj is None:
        #                         version_obj = DialogScriptVersion.objects.create(dialog_script=script_obj, updated=updated)

        #                     for field_key in version.get('fields', {}).keys():
        #                         field_value = version.get('fields', {}).get(field_key, None)

        #                         if field_key in ('created', 'updated'):
        #                             if field_value is not None:
        #                                 field_value = iso8601.parse_date(field_value)
        #                         elif field_key == 'creator__username':
        #                             creator = get_user_model().objects.filter(username=field_value).first()

        #                             if creator is None:
        #                                 creator = get_user_model().objects.create(username=field_value, is_active=False)

        #                             field_key = 'creator'
        #                             field_value = creator

        #                         setattr(version_obj, field_key, field_value)

        #                     version_obj.save()

        #                     versions_imported += 1

        if configurations_imported > 1:
            user_messages.append(('%s configurations imported.' % configurations_imported, messages.SUCCESS))
        elif configurations_imported == 1:
            user_messages.append(('1 configuration imported.', messages.SUCCESS))
        else:
            user_messages.append(('No configurations imported.', messages.INFO))

    return user_messages

def export_configurations(queryset):
    to_export = []

    for configuration in queryset:
        configuration_json = json.loads(serializers.serialize('json', AppConfiguration.objects.filter(pk=configuration.pk)))[0]

        del configuration_json['pk']

        configuration_json['versions'] = []

        for version in configuration.versions.all().order_by('created'):
            version_json = json.loads(serializers.serialize('json', AppConfigurationVersion.objects.filter(pk=version.pk)))[0]

            del version_json['pk']
            del version_json['fields']['configuration']

            creator = get_user_model().objects.filter(pk=version_json['fields']['creator']).first()

            if creator is None:
                version_json['fields']['creator__username'] = 'unknown-configuration-creator'
            else:
                version_json['fields']['creator__username'] = creator.username

            del version_json['fields']['creator']

            configuration_json['versions'].append(version_json)

        to_export.append(configuration_json)

    return to_export

def export_objects(queryset, queryset_name):
    to_export = []

    if queryset_name == 'AppConfiguration':
        to_export.extend(export_configurations(queryset))

    return to_export
