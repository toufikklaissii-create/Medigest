from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView, LogoutView
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.text import slugify

from .models import Cabinet, Profile


def tenant_discovery(request):
    error = None
    if request.method == "POST":
        raw_slug = request.POST.get("slug", "").strip()
        cabinet = Cabinet.objects.filter(slug=slugify(raw_slug), actif=True).first()
        if cabinet:
            return redirect("tenant_login", slug=cabinet.slug)
        error = "Espace introuvable."
    return render(request, "accounts/discovery.html", {"error": error})


class TenantLoginView(LoginView):
    template_name = "accounts/login.html"

    def dispatch(self, request, *args, **kwargs):
        self.cabinet = get_object_or_404(Cabinet, slug=kwargs["slug"], actif=True)
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["cabinet"] = self.cabinet
        return context

    def form_valid(self, form):
        response = super().form_valid(form)
        profile = getattr(form.get_user(), "profile", None)
        if not profile or profile.cabinet_id != self.cabinet.id:
            logout(self.request)
            form.add_error(None, "Vous n'appartenez pas à ce cabinet.")
            return self.form_invalid(form)
        return response

    def get_success_url(self):
        return "/accounts/redirect/"


tenant_login = TenantLoginView.as_view()


class AccountLogoutView(LogoutView):
    next_page = "accounts:login"


@login_required
def post_login_redirect(request):
    profile = getattr(request.user, "profile", None)
    if profile and profile.role == Profile.Role.DOCTOR:
        return redirect("clinical:doctor_dashboard")
    return redirect("appointments:assistant_dashboard")
