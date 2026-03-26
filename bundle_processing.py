# pylint: disable=no-member

import uuid

from .models import DataBundleProcessingTrace


def new_bundle_trace_id():
    return str(uuid.uuid4())


def bundle_summary(bundle, properties, bundle_trace_id):
    point_count = 0
    sources = set()
    generators = set()

    if isinstance(properties, list):
        point_count = len(properties)

        for point in properties:
            if isinstance(point, dict) and 'passive-data-metadata' in point:
                metadata = point['passive-data-metadata']

                source = metadata.get('source')
                generator = metadata.get('generator')

                if source:
                    sources.add(source)

                if generator:
                    generators.add(generator)

    return {
        'bundle_trace_id': bundle_trace_id,
        'bundle_id': bundle.pk,
        'encrypted': bundle.encrypted,
        'compression': bundle.compression,
        'point_count': point_count,
        'source_count': len(sources),
        'generator_count': len(generators),
    }


def bundle_log_fields(bundle, properties, bundle_trace_id):
    summary = bundle_summary(bundle, properties, bundle_trace_id)

    return (
        summary['bundle_trace_id'],
        summary['bundle_id'],
        summary['encrypted'],
        summary['compression'],
        summary['point_count'],
        summary['source_count'],
        summary['generator_count'],
    )


def attach_trace_context(bundle_point, bundle, bundle_trace_id):
    bundle_point['_pdk_trace_context'] = {
        'bundle_trace_id': bundle_trace_id,
        'bundle_id': bundle.pk,
    }


def record_bundle_processing_trace(bundle, bundle_trace_id, status, properties=None, data_point_id=None, error_class=None):
    point_count = None

    if isinstance(properties, list):
        point_count = len(properties)

    DataBundleProcessingTrace.objects.create(
        bundle_id=bundle.pk,
        bundle_trace_id=bundle_trace_id,
        data_point_id=data_point_id,
        status=status,
        bundle_recorded=bundle.recorded,
        point_count=point_count,
        encrypted=bundle.encrypted,
        compression=bundle.compression,
        error_class=error_class,
    )


def record_bundle_deleted(bundle, bundle_trace_id):
    record_bundle_processing_trace(bundle, bundle_trace_id, 'deleted')
