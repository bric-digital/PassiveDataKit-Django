# pylint: disable=no-member, line-too-long, consider-using-in, bad-option-value

from __future__ import print_function

import datetime
import importlib
import json

import arrow

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.http import HttpResponse, HttpResponseNotAllowed
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from django.contrib.auth import authenticate

from passive_data_kit.access_requests import build_django_user_identifier, build_token_identifier
from passive_data_kit.models import DataServerApiToken, DataPoint, DataServerAccessRequestPending, DataSource, DataSourceGroup, DataSourceReference, DataGeneratorDefinition


def valid_pdk_token_required(function):
    def wrap(request, *args, **kwargs):
        token = request.POST.get('token', None)

        now = timezone.now()

        expires = Q(expires__gte=now) | Q(expires=None)

        if DataServerApiToken.objects.filter(token=token).filter(expires).count() > 0:
            return function(request, *args, **kwargs)

        raise PermissionDenied('Invalid Token')

    wrap.__doc__ = function.__doc__
    wrap.__name__ = function.__name__

    return wrap


@csrf_exempt
def pdk_request_token(request):
    user = authenticate(username=request.POST['username'], password=request.POST['password'])

    if user is not None and user.is_staff:
        now = timezone.now()

        token = user.pdk_api_tokens.order_by('-expires').first()

        if (token is not None) and (token.expires < now):
            token = None

        if token is None:
            token_duration = datetime.timedelta(days=7)

            try:
                token_duration = datetime.timedelta(seconds=settings.PDK_TOKEN_LIFESPAN)
            except AttributeError:
                print('Unable to locate PDK_TOKEN_LIFESPAN in settings')

            token = DataServerApiToken(user=user, expires=(now + token_duration))
            token.save()

        response = {}
        response['token'] = token.fetch_token()
        response['expires'] = token.expires.isoformat()

        return HttpResponse(json.dumps(response), content_type='application/json')

    return HttpResponseNotAllowed(['POST'])


@csrf_exempt
@valid_pdk_token_required
def pdk_data_point_query(request): # pylint: disable=too-many-locals, too-many-branches, too-many-statements
    if request.method == 'POST':
        for app in settings.INSTALLED_APPS:
            try:
                pdk_plugin = importlib.import_module(app + '.pdk_api')

                response = pdk_plugin.pdk_data_point_query(request)

                if response is not None:
                    return response
            except ImportError:
                pass
            except AttributeError:
                pass

        page_size = int(request.POST['page_size'])
        page_index = int(request.POST['page_index'])

        filters = json.loads(request.POST['filters'])
        excludes = json.loads(request.POST['excludes'])
        order_bys = json.loads(request.POST['order_by'])

        latest = None

        if 'latest' in request.POST:
            latest = int(request.POST.get('latest_pk', 0))
        else:
            latest_point = DataPoint.objects.all().order_by('-pk').first()

            latest = latest_point.pk

        query = DataPoint.objects.filter(pk__lte=latest)

        for filter_obj in filters:
            processed_filter = {}

            for field, value in list(filter_obj.items()):
                if value is not None:
                    if field == 'created' or field == 'recorded':
                        value = arrow.get(value).datetime
                    elif field == 'source':
                        value = DataSourceReference.reference_for_source(value)
                        field = 'source_reference'
                    elif field == 'generator_identifier':
                        value = DataGeneratorDefinition.definition_for_identifier(value)
                        field = 'generator_definition'

                processed_filter[field] = value

            query = query.filter(**processed_filter)

        for exclude in excludes:
            processed_exclude = {}

            for field, value in list(exclude.items()):
                if value is not None:
                    if field == 'created' or field == 'recorded':
                        value = arrow.get(value).datetime
                    elif field == 'source':
                        value = DataSourceReference.reference_for_source(value)
                        field = 'source_reference'
                    elif field == 'generator_identifier':
                        value = DataGeneratorDefinition.definition_for_identifier(value)
                        field = 'generator_definition'

                processed_exclude[field] = value

            query = query.exclude(**processed_exclude)

        payload = {
            'latest': latest,
            'count': query.count(),
            'page_index': page_index,
            'page_size': page_size,
        }

        processed_order_by = []

        for order_by in order_bys:
            for item in order_by:
                processed_order_by.append(item)

        if processed_order_by:
            query = query.order_by(*processed_order_by)

        matches = []

        if payload['count'] > 0:
            for item in query[(page_index * page_size):((page_index + 1) * page_size)]:
                properties = item.fetch_properties()

                properties['passive-data-metadata']['pdk_server_created'] = arrow.get(item.created.isoformat()).timestamp()
                properties['passive-data-metadata']['pdk_server_recorded'] = arrow.get(item.recorded.isoformat()).timestamp()

                matches.append(properties)

        payload['matches'] = matches

        token = DataServerApiToken.objects.filter(token=request.POST.get('token', None)).first()

        access_request = DataServerAccessRequestPending()

        if token is not None:
            access_request.user_identifier = build_django_user_identifier(token.user)
        else:
            access_request.user_identifier = build_token_identifier(request.POST.get('token', None))

        access_request.request_type = 'api-data-points-request'
        access_request.request_time = timezone.now()
        access_request.request_metadata = json.dumps(request.POST, indent=2)
        access_request.successful = True
        access_request.save()

        return HttpResponse(json.dumps(payload, indent=2), content_type='application/json')

    return HttpResponseNotAllowed(['POST'])

@csrf_exempt
@valid_pdk_token_required
def pdk_data_source_query(request): # pylint: disable=too-many-locals, too-many-branches, too-many-statements
    if request.method == 'POST':
        page_size = int(request.POST.get('page_size', '32'))
        page_index = int(request.POST.get('page_index', '0'))

        filters = json.loads(request.POST.get('filters', '[]'))
        excludes = json.loads(request.POST.get('excludes', '[]'))
        order_bys = json.loads(request.POST.get('order_by', '[]'))

        query = None

        for filter_obj in filters:
            processed_filter = {}

            for field, value in list(filter_obj.items()):
                if value is not None:
                    if field == 'source':
                        field = 'source_reference'

                        value = DataSourceReference.reference_for_source(value)

                processed_filter[field] = value

            if query is None:
                query = DataSource.objects.filter(**processed_filter)
            else:
                query = query.filter(**processed_filter)

        for exclude in excludes:
            processed_exclude = {}

            for field, value in list(exclude.items()):
                if value is not None:
                    if field == 'source':
                        field = 'source_reference'

                        value = DataSourceReference.reference_for_source(value)

                processed_exclude[field] = value

            if query is None:
                query = DataSource.objects.exclude(**processed_exclude)
            else:
                query = query.exclude(**processed_exclude)

        if query is None:
            query = DataSource.objects.all()

        query = query.order_by('identifier')

        payload = {
            'count': query.count(),
            'page_index': page_index,
            'page_size': page_size,
        }

        processed_order_by = []

        for order_by in order_bys:
            for item in order_by:
                processed_order_by.append(item)

        if processed_order_by:
            query = query.order_by(*processed_order_by)

        matches = []

        for item in query[(page_index * page_size):((page_index + 1) * page_size)]:
            matches.append(item.fetch_definition())

        payload['matches'] = matches

        token = DataServerApiToken.objects.filter(token=request.POST.get('token', None)).first()

        access_request = DataServerAccessRequestPending()

        if token is not None:
            access_request.user_identifier = build_django_user_identifier(token.user)
        else:
            access_request.user_identifier = build_token_identifier(request.POST.get('token', None))

        access_request.request_type = 'api-data-source-request'
        access_request.request_time = timezone.now()
        access_request.request_metadata = json.dumps(request.POST, indent=2)
        access_request.successful = True
        access_request.save()

        return HttpResponse(json.dumps(payload), content_type='application/json')

    return HttpResponseNotAllowed(['POST'])

@csrf_exempt
@valid_pdk_token_required
def pdk_data_source_update(request): # pylint: disable=too-many-locals, too-many-branches, too-many-statements
    if request.method == 'POST': # pylint: disable=too-many-nested-blocks
        filters = json.loads(request.POST.get('filters', '[]'))
        excludes = json.loads(request.POST.get('excludes', '[]'))
        updates = json.loads(request.POST.get('updates', {}))

        query = None

        for filter_obj in filters:
            processed_filter = {}

            for field, value in list(filter_obj.items()):
                if value is not None:
                    if field == 'source':
                        field = 'source_reference'

                        value = DataSourceReference.reference_for_source(value)

                processed_filter[field] = value

            if query is None:
                query = DataSource.objects.filter(**processed_filter)
            else:
                query = query.filter(**processed_filter)

        for exclude in excludes:
            processed_exclude = {}

            for field, value in list(exclude.items()):
                if value is not None:
                    if field == 'source':
                        field = 'source_reference'

                        value = DataSourceReference.reference_for_source(value)

                processed_exclude[field] = value

            if query is None:
                query = DataSource.objects.exclude(**processed_exclude)
            else:
                query = query.exclude(**processed_exclude)

        update_count = 0

        for field_update in updates:
            processed_update = {}

            for field, value in list(field_update.items()):
                if value is not None:
                    if field == 'group':
                        group_name = value

                        value = DataSourceGroup.objects.filter(name=group_name).first()

                        if value is None:
                            value = DataSourceGroup.objects.create(name=group_name)

                processed_update[field] = value

            if query is None:
                update_count = DataSource.objects.update(**processed_exclude)
            else:
                update_count = query.update(**processed_update)

        payload = {
            'updated': update_count,
        }

        token = DataServerApiToken.objects.filter(token=request.POST.get('token', None)).first()

        access_request = DataServerAccessRequestPending()

        if token is not None:
            access_request.user_identifier = build_django_user_identifier(token.user)
        else:
            access_request.user_identifier = build_token_identifier(request.POST.get('token', None))

        access_request.request_type = 'api-data-source-update'
        access_request.request_time = timezone.now()
        access_request.request_metadata = json.dumps(request.POST, indent=2)
        access_request.successful = True
        access_request.save()

        return HttpResponse(json.dumps(payload), content_type='application/json')

    return HttpResponseNotAllowed(['POST'])
