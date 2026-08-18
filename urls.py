# pylint: disable=line-too-long, wrong-import-position

from django.contrib.auth.views import LogoutView
from django.conf import settings

from django.urls import re_path

from .views import pdk_add_data_point, pdk_add_data_bundle, pdk_app_config, pdk_issues, \
                   pdk_issues_json, pdk_fetch_metadata_json, pdk_data_source_list

urlpatterns = [
    re_path(r'^add-point.json$', pdk_add_data_point, name='pdk_add_data_point'),
    re_path(r'^add-bundle.json$', pdk_add_data_bundle, name='pdk_add_data_bundle'),
    re_path(r'^app-config.json$', pdk_app_config, name='pdk_app_config'),
]

try:
    from .withings_views import pdk_withings_start, pdk_withings_auth

    if settings.PDK_WITHINGS_CLIENT_ID and settings.PDK_WITHINGS_SECRET:
        urlpatterns.append(re_path(r'^withings/start/(?P<source_id>.+)$', pdk_withings_start, name='pdk_withings_start'))
        urlpatterns.append(re_path(r'^withings/auth$', pdk_withings_auth, name='pdk_withings_auth'))
except AttributeError:
    pass

try:
    if settings.PDK_DASHBOARD_ENABLED:
        from .views import pdk_home, pdk_unmatched_sources, pdk_source, pdk_source_generator, \
                           pdk_visualization_data, pdk_export, pdk_download_report, \
                           pdk_system_health, pdk_profile

        urlpatterns.append(re_path(r'^visualization/(?P<source_id>.+)/(?P<generator_id>.+)/(?P<page>\d+).json$', \
                                   pdk_visualization_data, name='pdk_visualization_data'))
        urlpatterns.append(re_path(r'^report/(?P<report_id>\d+)/download$', pdk_download_report, name='pdk_download_report'))
        urlpatterns.append(re_path(r'^source/(?P<source_id>.+)/(?P<generator_id>.+)$', pdk_source_generator, name='pdk_source_generator'))
        urlpatterns.append(re_path(r'^source/(?P<source_id>.+)$', pdk_source, name='pdk_source'))
        urlpatterns.append(re_path(r'^export$', pdk_export, name='pdk_export'))
        urlpatterns.append(re_path(r'^system-health$', pdk_system_health, name='pdk_system_health'))
        urlpatterns.append(re_path(r'^profile$', pdk_profile, name='pdk_profile'))
        urlpatterns.append(re_path(r'^fetch-metadata.json$', pdk_fetch_metadata_json, name='pdk_fetch_metadata_json'))
        urlpatterns.append(re_path(r'^issues.json$', pdk_issues_json, name='pdk_issues_json'))
        urlpatterns.append(re_path(r'^data-sources.txt$', pdk_data_source_list, name='pdk_data_source_list_txt'))
        urlpatterns.append(re_path(r'^issues$', pdk_issues, name='pdk_issues'))
        urlpatterns.append(re_path(r'^unmatched-sources.json$', pdk_unmatched_sources, name='pdk_unmatched_sources'))
        urlpatterns.append(re_path(r'^logout$', LogoutView.as_view(), name='pdk_logout'))
        urlpatterns.append(re_path(r'^$', pdk_home, name='pdk_home'))

except AttributeError:
    pass

try:
    if settings.PDK_API_ENABLED:
        from .api_views import pdk_request_token, pdk_data_point_query, pdk_data_source_query, pdk_data_source_update
        urlpatterns.append(re_path(r'^api/request-token.json$', pdk_request_token, name='pdk_request_token'))
        urlpatterns.append(re_path(r'^api/data-points.json$', pdk_data_point_query, name='pdk_data_point_query'))
        urlpatterns.append(re_path(r'^api/data-sources.json$', pdk_data_source_query, name='pdk_data_source_query'))
        urlpatterns.append(re_path(r'^api/data-sources/update.json$', pdk_data_source_update, name='pdk_data_source_update'))
except AttributeError:
    pass
