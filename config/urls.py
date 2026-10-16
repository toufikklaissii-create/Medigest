from django.conf import settings
from django.contrib import admin
from django.urls import include, path

from apps.accounts.views import tenant_login
from apps.common.views import media_file

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("apps.accounts.urls")),
    path("c/<slug:slug>/login/", tenant_login, name="tenant_login"),
    path("patients/", include("apps.patients.urls")),
    path("appointments/", include("apps.appointments.urls")),
    path("clinical/", include("apps.clinical.urls")),
    path("billing/", include("apps.billing.urls")),
    path("communications/", include("apps.communications.urls")),
    # MEDIA protégé (DEBUG ou non) : jamais de service statique public de MEDIA_ROOT.
    path(f"{settings.MEDIA_URL.strip('/')}/<path:path>", media_file, name="media_file"),
]
