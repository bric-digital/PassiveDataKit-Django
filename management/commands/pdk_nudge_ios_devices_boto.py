# pylint: disable=no-member,line-too-long

import json
import re

import boto
import boto.exception
import boto.sns

from django.conf import settings

from django.core.management.base import BaseCommand

from ...decorators import handle_lock, log_scheduled_event
from ...models import DataPoint

class Command(BaseCommand):
    help = 'Send silent notifications to iOS devices to nudge power management systems for transmission using Boto and Amazon Simple Notification Service.'

    def add_arguments(self, parser):
        pass

    @handle_lock
    @log_scheduled_event
    def handle(self, *args, **options): # pylint: disable=too-many-locals, too-many-branches, too-many-statements
        tokens = {}

        for point in DataPoint.objects.filter(generator_identifier='pdk-app-event', secondary_identifier='pdk-ios-device-token').order_by('created'):
            properties = point.fetch_properties()

            tokens[point.source] = properties['event_details']['token']

        region = [r for r in boto.sns.regions() if r.name == settings.PDK_BOTO_REGION][0]

        notification = {'aps': {'content-available' : 1}}

        message = {'APNS': json.dumps(notification), 'default': 'nil'}

        sns = boto.sns.SNSConnection(
            aws_access_key_id=settings.PDK_BOTO_ACCESS_KEY,
            aws_secret_access_key=settings.PDK_BOTO_ACCESS_SECRET,
            region=region,
        )

        for source, token in list(tokens.items()): # pylint: disable=unused-variable
            try:
                endpoint_response = sns.create_platform_endpoint(
                    platform_application_arn=settings.PDK_BOTO_SNS_ARN,
                    token=token,
                )
                endpoint_arn = endpoint_response['CreatePlatformEndpointResponse']['CreatePlatformEndpointResult']['EndpointArn']
            except boto.exception.BotoServerError as err:
                print('ERR 1: ' + err.message)
                # Yes, this is actually the official way:
                # http://stackoverflow.com/questions/22227262/aws-boto-sns-get-endpoint-arn-by-device-token
                result_re = re.compile(r'Endpoint(.*)already', re.IGNORECASE)
                result = result_re.search(err.message)

                if result:
                    endpoint_arn = result.group(0).replace('Endpoint ', '').replace(' already', '')
                else:
                    raise

            try:
                sns.publish(target_arn=endpoint_arn, message_structure='json', message=json.dumps(message))
            except boto.exception.BotoServerError as err:
                print('FAILED SENDING TO ' + token)
                print('ERR: ' + err.message)

                result_re = re.compile(r'Endpoint(.*)disabled', re.IGNORECASE)
                result = result_re.search(err.message)

                if result:
                    for point in DataPoint.objects.filter(source=source, generator_identifier='pdk-app-event', secondary_identifier='pdk-ios-device-token').order_by('created'):
                        properties = point.fetch_properties()

                        if token == properties['event_details']['token']:
                            print('RENAMING: ' + token)
                            point.secondary_identifier = 'pdk-ios-device-token-sandbox'
                            point.save()
                else:
                    raise

        tokens = {}

        for point in DataPoint.objects.filter(generator_identifier='pdk-app-event', secondary_identifier='pdk-ios-device-token-sandbox').order_by('created'):
            properties = point.fetch_properties()

            tokens[point.source] = properties['event_details']['token']

        message = {'APNS_SANDBOX': json.dumps(notification), 'default': 'nil'}

        for source, token in list(tokens.items()): # pylint: disable=unused-variable
            try:
                endpoint_response = sns.create_platform_endpoint(
                    platform_application_arn=settings.PDK_BOTO_SNS_ARN_SANDBOX,
                    token=token,
                )
                endpoint_arn = endpoint_response['CreatePlatformEndpointResponse']['CreatePlatformEndpointResult']['EndpointArn']
            except boto.exception.BotoServerError as err:
                print('ERR 2: ' + err.message)
                # Yes, this is actually the official way:
                # http://stackoverflow.com/questions/22227262/aws-boto-sns-get-endpoint-arn-by-device-token
                result_re = re.compile(r'Endpoint(.*)already', re.IGNORECASE)
                result = result_re.search(err.message)

                if result:
                    endpoint_arn = result.group(0).replace('Endpoint ', '').replace(' already', '')
                else:
                    raise

            try:
                sns.publish(target_arn=endpoint_arn, message_structure='json', message=json.dumps(message))
                # print('PUBLISHED DEV: ' + token)
            except boto.exception.BotoServerError as err:
                print('FAILED SENDING 2 TO ' + token)
                print('ERR: ' + err.message)

                result_re = re.compile(r'Endpoint(.*)disabled', re.IGNORECASE)
                result = result_re.search(err.message)

                if result:
                    for point in DataPoint.objects.filter(source=source, generator_identifier='pdk-app-event', secondary_identifier='pdk-ios-device-token-sandbox').order_by('created'):
                        properties = point.fetch_properties()

                        if token == properties['event_details']['token']:
                            print('RENAMING 2: ' + token)
                            point.secondary_identifier = 'pdk-ios-device-token-disabled'
                            point.save()
                else:
                    raise
