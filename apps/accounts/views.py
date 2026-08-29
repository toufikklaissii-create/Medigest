from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView, LogoutView
from django.shortcuts import redirect

from .models import Profile


class AccountLoginView(LoginView):
    template_name = "accounts/login.html"

    def get_success_url(self):
        return "/accounts/redirect/"


class AccountLogoutView(LogoutView):
    next_page = "accounts:login"


@login_required
def post_login_redirect(request):
    profile = getattr(request.user, "profile", None)
    if profile and profile.role == Profile.Role.DOCTOR:
        return redirect("clinical:doctor_dashboard")
    return redirect("appointments:assistant_dashboard")
