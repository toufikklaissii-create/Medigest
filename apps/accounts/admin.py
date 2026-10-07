from django.contrib import admin

from .models import Profile


class TenantScopedAdmin(admin.ModelAdmin):
    """Restreint les non-superusers aux objets de leur propre cabinet."""

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        profile = getattr(request.user, "profile", None)
        if profile is None:
            return qs.none()
        return qs.filter(cabinet=profile.cabinet)


@admin.register(Profile)
class ProfileAdmin(TenantScopedAdmin):
    list_display = ("user", "role", "cabinet")
    list_filter = ("role", "cabinet")
    search_fields = ("user__username", "user__first_name", "user__last_name")
