from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("apps.accounts.urls")),
    path("patients/", include("apps.patients.urls")),
    path("appointments/", include("apps.appointments.urls")),
    path("clinical/", include("apps.clinical.urls")),
    path("billing/", include("apps.billing.urls")),
    path("communications/", include("apps.communications.urls")),
]
