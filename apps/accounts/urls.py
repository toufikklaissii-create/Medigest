from django.urls import path

from . import remplacants, views

app_name = "accounts"

urlpatterns = [
    path("login/", views.tenant_discovery, name="login"),
    path("logout/", views.AccountLogoutView.as_view(), name="logout"),
    path("redirect/", views.post_login_redirect, name="post_login_redirect"),
    path("reglages/", views.cabinet_settings, name="settings"),
    path("reglages/page-de-test/<str:document_type>/", views.print_test_page, name="print_test_page"),
    path("reglages/remplacants/", remplacants.remplacants, name="remplacants"),
    path("reglages/remplacants/<int:pk>/activation/", remplacants.remplacant_toggle, name="remplacant_toggle"),
    path("reglages/remplacants/<int:pk>/mot-de-passe/", remplacants.remplacant_password, name="remplacant_password"),
]
