import sys

import django

from django.urls import re_path as url, include # pylint: disable=no-name-in-module

urlpatterns = [
    re_path(r'^admin/', django.contrib.admin.site.urls),
    re_path(r'^data/', include('passive_data_kit.urls')),
]
