# pylint: disable=line-too-long, wrong-import-position

import sys

from django.contrib.auth.views import LogoutView
from django.conf import settings

if sys.version_info[0] > 2:
    from django.urls import re_path as url # pylint: disable=no-name-in-module
else:
    from django.conf.urls import url

from .views import pdk_add_data_point, pdk_add_data_bundle, pdk_app_config, pdk_issues, \
                   pdk_issues_json, pdk_fetch_metadata_json, pdk_data_source_list

urlpatterns = [
    url(r'^add-point.json$', pdk_add_data_point, name='pdk_add_data_point'),
    url(r'^add-bundle.json$', pdk_add_data_bundle, name='pdk_add_data_bundle'),
    url(r'^app-config.json$', pdk_app_config, name='pdk_app_config'),
]

try:
    from .withings_views import pdk_withings_start, pdk_withings_auth

    if settings.PDK_WITHINGS_CLIENT_ID and settings.PDK_WITHINGS_SECRET:
        urlpatterns.append(url(r'^withings/start/(?P<source_id>.+)$', pdk_withings_start, name='pdk_withings_start'))
        urlpatterns.append(url(r'^withings/auth$', pdk_withings_auth, name='pdk_withings_auth'))
except AttributeError:
    pass

try:
    if settings.PDK_DASHBOARD_ENABLED:
        from .views import pdk_home, pdk_unmatched_sources, pdk_source, pdk_source_generator, \
                           pdk_visualization_data, pdk_export, pdk_download_report, \
                           pdk_system_health, pdk_profile

        urlpatterns.append(url(r'^visualization/(?P<source_id>.+)/(?P<generator_id>.+)/(?P<page>\d+).json$', \
                               pdk_visualization_data, name='pdk_visualization_data'))
        urlpatterns.append(url(r'^report/(?P<report_id>\d+)/download$', pdk_download_report, name='pdk_download_report'))
        urlpatterns.append(url(r'^source/(?P<source_id>.+)/(?P<generator_id>.+)$', pdk_source_generator, name='pdk_source_generator'))
        urlpatterns.append(url(r'^source/(?P<source_id>.+)$', pdk_source, name='pdk_source'))
        urlpatterns.append(url(r'^export$', pdk_export, name='pdk_export'))
        urlpatterns.append(url(r'^system-health$', pdk_system_health, name='pdk_system_health'))
        urlpatterns.append(url(r'^profile$', pdk_profile, name='pdk_profile'))
        urlpatterns.append(url(r'^fetch-metadata.json$', pdk_fetch_metadata_json, name='pdk_fetch_metadata_json'))
        urlpatterns.append(url(r'^issues.json$', pdk_issues_json, name='pdk_issues_json'))
        urlpatterns.append(url(r'^data-sources.txt$', pdk_data_source_list, name='pdk_data_source_list_txt'))
        urlpatterns.append(url(r'^issues$', pdk_issues, name='pdk_issues'))
        urlpatterns.append(url(r'^unmatched-sources.json$', pdk_unmatched_sources, name='pdk_unmatched_sources'))
        urlpatterns.append(url(r'^logout$', LogoutView.as_view(), name='pdk_logout'))
        urlpatterns.append(url(r'^$', pdk_home, name='pdk_home'))

except AttributeError:
    pass

try:
    if settings.PDK_API_ENABLED:
        from .api_views import pdk_request_token, pdk_data_point_query, pdk_data_source_query, pdk_data_source_update
        urlpatterns.append(url(r'^api/request-token.json$', pdk_request_token, name='pdk_request_token'))
        urlpatterns.append(url(r'^api/data-points.json$', pdk_data_point_query, name='pdk_data_point_query'))
        urlpatterns.append(url(r'^api/data-sources.json$', pdk_data_source_query, name='pdk_data_source_query'))
        urlpatterns.append(url(r'^api/data-sources/update.json$', pdk_data_source_update, name='pdk_data_source_update'))
except AttributeError:
    pass
