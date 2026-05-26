import sys

import django

from django.urls import re_path, include

urlpatterns = [
    re_path(r'^admin/', django.contrib.admin.site.urls),
    re_path(r'^data/', include('passive_data_kit.urls')),
]
