from django.contrib import admin

from apps.accounts.admin import TenantScopedAdmin

from .models import Task


@admin.register(Task)
class TaskAdmin(TenantScopedAdmin):
    list_display = ("title", "author", "assignee", "patient", "status", "priority", "cabinet", "created_at")
    list_filter = ("status", "priority", "cabinet")
    search_fields = ("title", "description")
