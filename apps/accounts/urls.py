from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("login/", views.tenant_discovery, name="login"),
    path("logout/", views.AccountLogoutView.as_view(), name="logout"),
    path("redirect/", views.post_login_redirect, name="post_login_redirect"),
    path("reglages/", views.cabinet_settings, name="settings"),
    path("reglages/page-de-test/<str:document_type>/", views.print_test_page, name="print_test_page"),
]
