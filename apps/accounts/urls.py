from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("login/", views.tenant_discovery, name="login"),
    path("logout/", views.AccountLogoutView.as_view(), name="logout"),
    path("redirect/", views.post_login_redirect, name="post_login_redirect"),
]
