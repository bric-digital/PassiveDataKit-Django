# pylint: disable=no-member, line-too-long

from builtins import str # pylint: disable=redefined-builtin

import datetime
import importlib
import io
import json
import os
import re
import traceback

from django.conf import settings
from django.db.utils import DataError
from django.http import HttpResponse, HttpResponseNotAllowed, JsonResponse, HttpResponseNotFound, \
                        FileResponse, UnreadablePostError
from django.shortcuts import render, get_object_or_404, redirect
from django.utils import timezone
from django.utils.encoding import smart_str
from django.views.decorators.csrf import csrf_exempt

from django.contrib.admin.views.decorators import staff_member_required

from .models import DataPoint, DataBundle, DataFile, DataSourceGroup, DataSource, ReportJob, \
                    generator_label, install_supports_jsonfield, DataSourceAlert, \
                    DataServerMetadatum, AppConfiguration, DeviceIssue, Device, DeviceModel


@csrf_exempt
def pdk_add_data_point(request): # pylint: disable=too-many-statements
    try:
        if settings.PDK_DISABLE_DATA_UPLOAD:
            response_payload = {'message': 'Data collection has been disabled and incoming transmissions are being discarded.'}

            response = HttpResponse(json.dumps(response_payload, indent=2), content_type='application/json', status=201)
            response['Access-Control-Allow-Origin'] = '*'
            response['Access-Control-Allow-Methods'] = 'CREATE, POST'
            response['Access-Control-Request-Headers'] = 'Content-Type'
            response['Access-Control-Allow-Headers'] = 'Content-Type'

            return response
    except AttributeError:
        pass

    response_payload = {'message': 'Data point added successfully.'}

    if request.method == 'CREATE': # pylint: disable=no-else-return
        response = HttpResponse(json.dumps(response_payload, indent=2), content_type='application/json', \
                                status=201)
        response['Access-Control-Allow-Origin'] = '*'
        response['Access-Control-Allow-Methods'] = 'CREATE, POST'
        response['Access-Control-Request-Headers'] = 'Content-Type'
        response['Access-Control-Allow-Headers'] = 'Content-Type'

        point = json.loads(request.body)

        data_point = DataPoint(recorded=timezone.now())
        data_point.source = point['passive-data-metadata']['source']
        data_point.generator = point['passive-data-metadata']['generator']
        data_point.created = datetime.datetime.fromtimestamp(point['passive-data-metadata']['source'], tz=timezone.get_default_timezone())

        if 'generator-id' in point['passive-data-metadata']:
            data_point.generator_identifier = point['passive-data-metadata']['generator-id']

        if install_supports_jsonfield():
            data_point.properties = point
        else:
            data_point.properties = json.dumps(point, indent=2)

        data_point.save()

        data_point.fetch_secondary_identifier(skip_save=True, properties=data_point.properties)
        data_point.fetch_user_agent(skip_save=True, properties=data_point.properties)
        data_point.fetch_generator_definition(skip_save=True)
        data_point.fetch_source_reference(skip_save=True)

        data_point.save()

        return response
    elif request.method == 'POST':
        response = HttpResponse(json.dumps(response_payload, indent=2), \
                                content_type='application/json', \
                                status=201)

        response['Access-Control-Allow-Origin'] = '*'
        response['Access-Control-Allow-Methods'] = 'CREATE, POST'
        response['Access-Control-Request-Headers'] = 'Content-Type'
        response['Access-Control-Allow-Headers'] = 'Content-Type'

        point = json.loads(request.POST['payload'])

        data_point = DataPoint(recorded=timezone.now())
        data_point.source = point['passive-data-metadata']['source']
        data_point.generator = point['passive-data-metadata']['generator']
        data_point.created = datetime.datetime.fromtimestamp(point['passive-data-metadata']['timestamp'], tz=timezone.get_default_timezone())

        if 'generator-id' in point['passive-data-metadata']:
            data_point.generator_identifier = point['passive-data-metadata']['generator-id']

        if install_supports_jsonfield():
            data_point.properties = point
        else:
            data_point.properties = json.dumps(point, indent=2)

        data_point.save()

        data_point.fetch_secondary_identifier(skip_save=True, properties=data_point.properties)
        data_point.fetch_user_agent(skip_save=True, properties=data_point.properties)
        data_point.fetch_generator_definition(skip_save=True)
        data_point.fetch_source_reference(skip_save=True)

        data_point.save()

        return response
    elif request.method == 'OPTIONS':
        response = HttpResponse('', content_type='text/plain', status=200)
        response['Access-Control-Allow-Origin'] = '*'
        response['Access-Control-Allow-Methods'] = 'CREATE, POST'
        response['Access-Control-Request-Headers'] = 'Content-Type'
        response['Access-Control-Allow-Headers'] = 'Content-Type'

        return response

    return HttpResponseNotAllowed(['CREATE', 'POST'])


@csrf_exempt
def pdk_add_data_bundle(request): # pylint: disable=too-many-statements, too-many-branches, too-many-return-statements
    try:
        if settings.PDK_DISABLE_DATA_UPLOAD:
            response_payload = {
                'message': 'Data collection has been disabled and incoming transmissions are being discarded.',
                'added': True
            }

            response = HttpResponse(json.dumps(response_payload, indent=2), content_type='application/json', status=201)
            response['Access-Control-Allow-Origin'] = '*'
            response['Access-Control-Allow-Methods'] = 'CREATE, POST'
            response['Access-Control-Request-Headers'] = 'Content-Type'
            response['Access-Control-Allow-Headers'] = 'Content-Type'

            return response
    except AttributeError:
        pass

    response_payload = {
        'message': 'Data bundle added successfully, and ready for processing.',
        'added': True
    }

    supports_json = install_supports_jsonfield()

    if request.method == 'CREATE': # pylint: disable=no-else-return
        response = HttpResponse(json.dumps(response_payload, indent=2), \
                                content_type='application/json', \
                                status=201)

        response['Access-Control-Allow-Origin'] = '*'
        response['Access-Control-Allow-Methods'] = 'CREATE, POST, HEAD'
        response['Access-Control-Request-Headers'] = 'Content-Type'
        response['Access-Control-Allow-Headers'] = 'Content-Type'

        points = None

        body_str = request.body.decode('utf-8')

        body_str = body_str.replace('\\u0000', '')

        try:
            points = json.loads(body_str)
        except UnreadablePostError:
            traceback.print_exc()

            response = {'message': 'Unable to parse data bundle.'}
            response = HttpResponse(json.dumps(response, indent=2), \
                                    content_type='application/json', \
                                    status=400)

            bundle = DataBundle(recorded=timezone.now())

            bundle.properties = json.dumps(request.body.decode('utf-8'))
            bundle.errored = timezone.now()
            bundle.processed = timezone.now()
            bundle.save()

            return response

        try:
            bundle = DataBundle(recorded=timezone.now())

            if supports_json:
                bundle.properties = points
            else:
                bundle.properties = json.dumps(points)

            bundle.save()
        except DataError:
            traceback.print_exc()

            response = {'message': 'Unable to parse data bundle.'}
            response = HttpResponse(json.dumps(response, indent=2), \
                                    content_type='application/json', \
                                    status=400)

            bundle.properties = json.dumps(request.body.decode('utf-8'))
            bundle.errored = timezone.now()
            bundle.processed = timezone.now()
            bundle.save()

        return response

    elif request.method == 'POST':
        response = HttpResponse(json.dumps(response_payload), \
                                content_type='application/json', \
                                status=201)

        response['Access-Control-Allow-Origin'] = '*'
        response['Access-Control-Allow-Methods'] = 'CREATE, POST, HEAD'
        response['Access-Control-Request-Headers'] = 'Content-Type'
        response['Access-Control-Allow-Headers'] = 'Content-Type'

        try:
            bundle = DataBundle(recorded=timezone.now(), encrypted=False)

            if 'encrypted' in request.POST:
                bundle.encrypted = (request.POST['encrypted'] == 'true')

            if 'compression' in request.POST:
                bundle.compression = request.POST['compression']

            if bundle.encrypted:
                payload = {
                    'encrypted': request.POST['payload'],
                    'nonce': request.POST['nonce']
                }

                if supports_json:
                    bundle.properties = payload
                else:
                    bundle.properties = json.dumps(payload)
            else:
                if bundle.compression == 'none':
                    points = json.loads(request.POST['payload'])

                    if supports_json:
                        bundle.properties = points
                    else:
                        bundle.properties = json.dumps(points)
                else:
                    properties = {
                        'payload': request.POST['payload']
                    }

                    if supports_json:
                        bundle.properties = properties
                    else:
                        bundle.properties = json.dumps(properties)

            bundle.save()
        except ValueError:
            response_payload = {'message': 'Unable to parse data bundle.'}
            response = HttpResponse(json.dumps(response_payload), \
                                    content_type='application/json', \
                                    status=400)
        except UnreadablePostError:
            response_payload = {'message': 'Unable to parse data bundle.'}
            response = HttpResponse(json.dumps(response_payload), \
                                    content_type='application/json', \
                                    status=400)

        for key, value in list(request.FILES.items()): # pylint: disable=unused-variable
            data_file = DataFile(data_bundle=bundle)
            data_file.identifier = key
            data_file.content_type = value.content_type
            data_file.content_file.save(key, value)
            data_file.save()

        return response
    elif request.method == 'OPTIONS':
        response = HttpResponse('', content_type='text/plain', status=200)
        response['Access-Control-Allow-Origin'] = '*'
        response['Access-Control-Allow-Methods'] = 'CREATE, POST, HEAD'
        response['Access-Control-Request-Headers'] = 'Content-Type'
        response['Access-Control-Allow-Headers'] = 'Content-Type'

        return response
    elif request.method == 'HEAD':
        response = HttpResponse('', content_type='text/plain', status=200)
        response['Access-Control-Allow-Origin'] = '*'
        response['Access-Control-Allow-Methods'] = 'CREATE, POST, HEAD'
        response['Access-Control-Request-Headers'] = 'Content-Type'
        response['Access-Control-Allow-Headers'] = 'Content-Type'

        return response

    return HttpResponseNotAllowed(['CREATE', 'POST', 'HEAD'])


@staff_member_required
def pdk_home(request): # pylint: disable=too-many-branches, too-many-statements
    for app in settings.INSTALLED_APPS:
        try:
            app_views = importlib.import_module(app + '.views')

            return app_views.custom_pdk_home(request)
        except ImportError:
            pass
        except AttributeError:
            pass

    context = {}

    if request.method == 'POST':
        if request.POST['operation'] == 'add_source':
            identifier = request.POST['source_identifier'].strip()
            name = request.POST['friendly_name'].strip()

            group = request.POST['assigned_group']
            group_name = request.POST['new_group_name'].strip()

            final_identifier = identifier
            final_count = 2

            while DataSource.objects.filter(identifier=final_identifier).count() > 0:
                final_identifier = identifier + '-' + str(final_count)

                final_count += 1

            final_name = name
            final_count = 2

            while DataSource.objects.filter(name=final_name).count() > 0:
                final_name = name + ' ' + str(final_count)

                final_count += 1

            source = DataSource(identifier=final_identifier, name=final_name)

            if group == "-1":
                pass
            elif group == "0":
                group = DataSourceGroup.objects.filter(name=group_name).first()

                if group is None:
                    group = DataSourceGroup(name=group_name)
                    group.save()

                source.group = group
            else:
                source.group = DataSourceGroup.objects.get(pk=int(group))

            source.save()
        elif request.POST['operation'] == 'remove_source':
            DataSource.objects.filter(pk=int(request.POST['pk'])).delete()
        elif request.POST['operation'] == 'move_source':
            source = DataSource.objects.get(pk=int(request.POST['move_pk']))

            group_pk = int(request.POST['move_group_pk'])
            group_name = request.POST['move_group_name']

            if group_pk == 0 and group_name.strip() != '':
                group = DataSourceGroup.objects.filter(name=group_name).first()

                if group is None:
                    group = DataSourceGroup(name=group_name)
                    group.save()

                source.group = group
            else:
                source.group = DataSourceGroup.objects.get(pk=group_pk)

            source.save()
        elif request.POST['operation'] == 'rename_source':
            source = DataSource.objects.get(pk=int(request.POST['rename_pk']))
            source.name = request.POST['rename_name']

            source.save()

    context['groups'] = DataSourceGroup.objects.order_by('name')
    context['solo_sources'] = DataSource.objects.filter(group=None).order_by('name')

    excluded_sources = []

    try:
        excluded_sources = settings.PDK_EXCLUDED_SOURCES
    except AttributeError:
        pass

    context['excluded_sources'] = excluded_sources

    return render(request, 'pdk_home.html', context=context)


@staff_member_required
def pdk_source(request, source_id): # pylint: disable=unused-argument
    if '/' in source_id:
        return redirect('pdk_source', source_id=source_id.replace('/', ''))

    context = {}

    excluded_sources = []

    try:
        excluded_sources = settings.PDK_EXCLUDED_SOURCES
    except AttributeError:
        pass

    if source_id in excluded_sources:
        return HttpResponseNotFound()

    source = DataSource.objects.filter(identifier=source_id).first()

    if source is None:
        source = DataSource(identifier=source_id, name=source_id)
        source.save()

    context['source'] = source

    context['alerts'] = DataSourceAlert.objects.filter(active=True, data_source=source)

    return render(request, 'pdk_source.html', context=context)


@staff_member_required
def pdk_source_generator(request, source_id, generator_id): # pylint: disable=unused-argument
    if ('/' in source_id) or ('/' in generator_id):
        return redirect('pdk_source_generator', source_id=source_id.replace('/', ''), generator_id=generator_id.replace('/', ''))

    context = {}

    excluded_sources = []

    try:
        excluded_sources = settings.PDK_EXCLUDED_SOURCES
    except AttributeError:
        pass

    if source_id in excluded_sources:
        return HttpResponseNotFound()

    source = DataSource.objects.filter(identifier=source_id).first()

    if source is None:
        source = DataSource(identifier=source_id, name='Unknown')
        source.save()

    context['source'] = source
    context['generator'] = generator_id
    context['generator_label'] = generator_label(generator_id)

    context['visualization'] = None

    for app in settings.INSTALLED_APPS:
        if context['visualization'] is None:
            try:
                pdk_api = importlib.import_module(app + '.pdk_api')

                context['visualization'] = pdk_api.visualization(source, generator_id)
            except ImportError:
                pass
            except AttributeError:
                pass

    for app in settings.INSTALLED_APPS:
        try:
            pdk_api = importlib.import_module(app + '.pdk_api')

            context['data_table'] = pdk_api.data_table(source, generator_id)
        except ImportError:
            pass
        except AttributeError:
            pass

    return render(request, 'pdk_source_generator.html', context=context)


@staff_member_required
def pdk_unmatched_sources(request): # pylint: disable=unused-argument
    sources = DataPoint.objects.sources()

#    for point in DataPoint.objects.order_by('source').values_list('source', flat=True).distinct():
#        sources.append(point)

    return JsonResponse(sources, safe=False, json_dumps_params={'indent': 2})


@staff_member_required
def pdk_visualization_data(request, source_id, generator_id, page): # pylint: disable=unused-argument
    folder = settings.MEDIA_ROOT + '/pdk_visualizations/' + source_id + '/' + generator_id

    filename = 'visualization-' + page + '.json'

    if page == '0':
        filename = 'visualization.json'

    try:
        with io.open(folder + '/' + filename, encoding='utf-8') as data_file:
            return HttpResponse(data_file.read(), content_type='application/json')
    except IOError:
        pass

    return HttpResponseNotFound()


@staff_member_required
def pdk_download_report(request, report_id): # pylint: disable=unused-argument
    job = get_object_or_404(ReportJob, pk=int(report_id))

    filename = settings.MEDIA_ROOT + '/' + job.report.name

    response = FileResponse(io.open(filename, 'rb'), content_type='application/octet-stream') # pylint: disable=consider-using-with

    download_name = 'pdk-export_' + job.started.date().isoformat() + '_' + smart_str(job.pk) + '.zip'

    response['Content-Length'] = os.path.getsize(filename)
    response['Content-Disposition'] = 'attachment; filename=' + download_name

    return response


@staff_member_required
def pdk_export(request): # pylint: disable=too-many-branches, too-many-locals, too-many-statements
    context = {}

    groups = []

    excluded_sources = []

    try:
        excluded_sources = settings.PDK_EXCLUDED_SOURCES
    except AttributeError:
        pass

    for group in DataSourceGroup.objects.all().order_by('name'):
        group_def = (group.name, [], group.pk)

        for source in group.sources.all().order_by('name'):
            if (source.identifier in excluded_sources) is False:
                group_def[1].append(source)

        if len(group_def[1]) > 0: # pylint: disable=len-as-condition
            groups.append(group_def)

    group_def = ('(Not in group)', [], 0)

    for source in DataSource.objects.filter(group=None).order_by('name'):
        if (source.identifier in excluded_sources) is False:
            group_def[1].append(source)

    if len(group_def[1]) > 0: # pylint: disable=len-as-condition
        groups.append(group_def)

    context['groups'] = groups
    context['sources'] = sorted(DataPoint.objects.sources())
    context['generators'] = sorted(DataPoint.objects.generator_identifiers())

    to_remove = []

    for generator in context['generators']:
        if generator in context['sources']:
            context['sources'].remove(generator)

        try:
            if generator in settings.PDK_EXCLUDE_GENERATORS:
                to_remove.append(generator)
        except AttributeError:
            pass

    for generator in to_remove:
        context['generators'].remove(generator)

    all_extra_generators = []
    to_remove = []

    try:
        for extra_generator in settings.PDK_EXTRA_GENERATORS:
            all_extra_generators.append(extra_generator)
    except AttributeError:
        pass

    for app in settings.INSTALLED_APPS: # pylint: disable=too-many-nested-blocks
        for generator in context['generators']:
            try:
                module_name = '.generators.' + generator.replace('-', '_')

                generator_module = importlib.import_module(module_name, package=app)

                extra_generators = generator_module.extra_generators(generator)

                if extra_generators is not None and extra_generators:
                    for extra_generator in extra_generators:
                        all_extra_generators.append(extra_generator)

                        try:
                            if extra_generator[0] in settings.PDK_EXCLUDE_GENERATORS:
                                to_remove.append(extra_generator)
                        except AttributeError:
                            pass

            except ImportError:
                pass

            except AttributeError:
                pass

    for generator in to_remove:
        all_extra_generators.remove(generator)

    context['extra_generators'] = all_extra_generators

    context['message'] = ''
    context['message_type'] = 'ok'

    if request.method == 'POST':
        export_sources = []
        export_generators = []

        respond_json = False

        for source in context['sources']:
            key = 'source_' + source

            if key in request.POST:
                export_sources.append(source)

        for generator in context['generators']:
            key = 'generator_' + generator

            if key in request.POST:
                export_generators.append(generator)

        for generator in context['extra_generators']:
            key = 'generator_' + generator[0]

            if key in request.POST:
                export_generators.append(generator[0])

        raw_sources = request.POST.get('sources', None)

        if raw_sources is not None:
            respond_json = True

            parsed_sources = raw_sources.split(';')

            for source in parsed_sources:
                if source != '':
                    export_sources.append(source)

        if len(export_sources) == 0: # pylint: disable=len-as-condition
            context['message_type'] = 'error'

            if len(export_generators) == 0: # pylint: disable=len-as-condition
                context['message'] = 'Please select one or more sources and generators to export data.'
            else:
                context['message'] = 'Please select one or more sources to export data.'
        elif len(export_generators) == 0: # pylint: disable=len-as-condition
            context['message_type'] = 'error'

            context['message'] = 'Please select one or more generators to export data.'
        else:
            export_raw = ('export_raw_json' in request.POST and request.POST['export_raw_json'])

            data_start = request.POST['data_start']

            data_end = request.POST['data_end']

            date_type = request.POST['date_type']

            created = ReportJob.objects.create_jobs(request.user, export_sources, export_generators, export_raw, data_start, data_end, date_type) # pylint: disable=assignment-from-no-return

            context['message_type'] = 'ok'

            if created == 1:
                context['message'] = 'Export job queued. Check your e-mail for a link to the output when the export is complete.' # pylint: disable=
            else:
                context['message'] = 'Export jobs queued. Check your e-mail for links to the output when the export is complete.'

        if respond_json:
            return HttpResponse(json.dumps({'success': True}, indent=2), content_type='application/json', status=200)

    return render(request, 'pdk_export.html', context=context)


@staff_member_required
def pdk_system_health(request):
    datum = DataServerMetadatum.objects.filter(key='Server Health').first()

    if datum is not None:
        return render(request, 'pdk_system_health.html', context=json.loads(datum.value))

    return render(request, 'pdk_system_health.html', context={})


@staff_member_required
def pdk_profile(request):
    context = {}
    context['user'] = request.user

    if request.method == 'POST':
        current_password = request.POST['current_password']

        if request.user.check_password(current_password):
            new_password = request.POST['new_password']
            confirm_password = request.POST['confirm_password']

            if new_password == confirm_password:
                request.user.set_password(new_password)
                request.user.save()

                context['message'] = 'Password updated successfully.'
                context['message_class'] = 'success'
            else:
                context['message'] = 'Provided passwords do not match. Please try again.'
                context['message_class'] = 'danger'
        else:
            context['message'] = 'Current password is incorrect. Please try again.'
            context['message_class'] = 'danger'

    return render(request, 'pdk_user_profile.html', context=context)

@csrf_exempt
def pdk_app_config(request): # pylint: disable=too-many-statements, too-many-branches
    identifier = None
    context = None

    if request.method == 'GET':
        identifier = request.GET.get('id', request.GET.get('identifier', None))

        context = request.GET.get('context', None)

    if request.method == 'POST':
        identifier = request.POST.get('id', request.POST.get('identifier', None))

        context = request.POST.get('context', None)

    if identifier is None:
        identifier = 'default'

    if context is None:
        context = 'default'

    configuration = None

    source = DataSource.objects.filter(identifier=identifier).first()

    if source is not None:
        if source.configuration is not None:
            configuration = source.configuration.configuration()

    if configuration is None:
        for config in AppConfiguration.objects.filter(id_pattern=identifier, is_valid=True, is_enabled=True).order_by('evaluate_order'):
            if configuration is None and config.context_pattern == '.*' or re.search(config.context_pattern, context) is not None:
                configuration = config.configuration()

    if configuration is None:
        for config in AppConfiguration.objects.filter(is_valid=True, is_enabled=True).order_by('evaluate_order'):
            if configuration is None and config.id_pattern == '.*' or re.search(config.id_pattern, identifier) is not None:
                if config.context_pattern == '.*' or re.search(config.context_pattern, context) is not None:
                    configuration = config.configuration()

    try:
        settings.PDK_UPDATE_APP_CONFIGURATION(identifier, configuration)
    except AttributeError:
        pass

    response = HttpResponse(json.dumps(configuration, indent=2), content_type='application/json', status=200)

    response['Access-Control-Allow-Origin'] = '*'

    return response

@staff_member_required
def pdk_issues(request):
    context = {}

    context['manufacturers'] = DeviceModel.objects.order_by('manufacturer').values_list('manufacturer', flat=True).distinct()

    return render(request, 'pdk_issues.html', context=context)

@staff_member_required
def pdk_issues_json(request): # pylint: disable=too-many-statements
    payload = []

    if request.method == 'POST':
        payload = {
            'success': False,
            'message': ''
        }

        if 'source' in request.POST:
            source = DataSource.objects.filter(identifier=request.POST['source']).first()

            if source is not None:
                device = Device.objects.filter(source=source).first()

                if device is not None:
                    device.populate_device()
                else:
                    device = Device(source=source)
                    device.populate_device()

                issue = DeviceIssue(device=device)
                issue.description = request.POST['description']
                issue.tags = request.POST['tags']
                issue.created = timezone.now()
                issue.last_updated = timezone.now()

                issue.stability_related = (request.POST['app_stability'] == 'true')
                issue.uptime_related = (request.POST['app_uptime'] == 'true')
                issue.responsiveness_related = (request.POST['app_responsiveness'] == 'true')
                issue.battery_use_related = (request.POST['battery'] == 'true')
                issue.power_management_related = (request.POST['power'] == 'true')
                issue.data_volume_related = (request.POST['data_volume'] == 'true')
                issue.data_quality_related = (request.POST['data_quality'] == 'true')
                issue.bandwidth_related = (request.POST['bandwidth'] == 'true')
                issue.storage_related = (request.POST['storage'] == 'true')
                issue.configuration_related = (request.POST['app_configuration'] == 'true')
                issue.location_related = (request.POST['location'] == 'true')
                issue.correctness_related = (request.POST['app_correctness'] == 'true')
                issue.ui_related = (request.POST['app_ui'] == 'true')
                issue.device_performance_related = (request.POST['device_performance'] == 'true')
                issue.device_stability_related = (request.POST['device_stability'] == 'true')

                issue.save()

                payload['message'] = 'New issue created successfully.'
                payload['success'] = True
            else:
                payload['message'] = 'Unable to locate data source with identifier: ' + request.POST['source'] + '.'
        else:
            payload['message'] = 'Source identifier not provided.'
    else:
        payload = []

        for issue in DeviceIssue.objects.all():
            issue_obj = {}

            issue_obj['source'] = issue.device.source.identifier
            issue_obj['model'] = str(issue.device.model)
            issue_obj['state'] = issue.state
            issue_obj['created'] = issue.created.isoformat()

            if issue.last_updated is not None:
                issue_obj['updated'] = issue.last_updated.isoformat()

            issue_obj['platform'] = issue.platform
            issue_obj['user_agent'] = issue.user_agent
            issue_obj['description'] = issue.description

            issue_obj['stability_related'] = issue.stability_related
            issue_obj['uptime_related'] = issue.uptime_related
            issue_obj['responsiveness_related'] = issue.responsiveness_related
            issue_obj['battery_use_related'] = issue.battery_use_related
            issue_obj['power_management_related'] = issue.power_management_related
            issue_obj['data_volume_related'] = issue.data_volume_related
            issue_obj['data_quality_related'] = issue.data_quality_related
            issue_obj['bandwidth_related'] = issue.bandwidth_related
            issue_obj['storage_related'] = issue.storage_related
            issue_obj['configuration_related'] = issue.configuration_related
            issue_obj['location_related'] = issue.location_related
            issue_obj['correctness_related'] = issue.correctness_related

            payload.append(issue_obj)

    return JsonResponse(payload, safe=False, json_dumps_params={'indent': 2})

@csrf_exempt
def pdk_fetch_metadata_json(request):
    metadata = {}

    if 'identifier' in request.POST and 'request-key' in request.POST: # pylint: disable=too-many-nested-blocks
        try:
            if request.POST['request-key'] == settings.PDK_REQUEST_KEY:
                source = DataSource.objects.filter(identifier=request.POST['identifier']).first()

                if source is not None:
                    metadata = source.fetch_performance_metadata()

                    for app in settings.INSTALLED_APPS:
                        try:
                            pdk_api = importlib.import_module(app + '.pdk_api')

                            pdk_api.annotate_remote_metadata(source.identifier, metadata)
                        except ImportError:
                            pass
                        except AttributeError:
                            pass

        except AttributeError:
            pass


    return JsonResponse(metadata, safe=False, json_dumps_params={'indent': 2})
