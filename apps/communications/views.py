import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.shortcuts import get_object_or_404, redirect, render

from apps.accounts.decorators import role_required
from apps.accounts.models import CLINICIAN_ROLES, Profile
from apps.patients.models import Patient

from .models import Task


@login_required
def index(request):
    return render(request, "communications/index.html", {"tasks": _active_tasks_for(request.user)})


def _active_tasks_for(user):
    return (
        Task.objects.select_related("author", "patient")
        .filter(assignee=user, cabinet=user.profile.cabinet)
        .exclude(status=Task.Status.COMPLETED)
        .order_by("-priority", "-created_at")
    )


@login_required
def tasks_panel(request):
    return render(
        request, "communications/_tasks_panel.html", {"tasks": _active_tasks_for(request.user)}
    )


@login_required
def toggle_task(request, pk):
    task = get_object_or_404(
        Task, pk=pk, assignee=request.user, cabinet=request.user.profile.cabinet
    )
    toast_message = None
    if request.method == "POST":
        task.status = Task.Status.COMPLETED
        task.save(update_fields=["status"])
        toast_message = f"Tâche « {task.title} » marquée terminée."

    response = render(
        request, "communications/_tasks_panel.html", {"tasks": _active_tasks_for(request.user)}
    )
    if toast_message:
        response.headers["HX-Trigger"] = json.dumps(
            {"toast": {"message": toast_message, "type": "success"}}
        )
    return response


@login_required
@role_required(*CLINICIAN_ROLES)
def create_task(request):
    if request.method == "POST":
        cabinet = request.user.profile.cabinet
        title = request.POST.get("title", "").strip()
        if title:
            assignee = User.objects.filter(
                profile__role=Profile.Role.ASSISTANT, profile__cabinet=cabinet
            ).first()
            patient_id = request.POST.get("patient") or None
            patient = (
                Patient.objects.filter(pk=patient_id, cabinet=cabinet).first()
                if patient_id
                else None
            )
            Task.objects.create(
                cabinet=cabinet,
                author=request.user,
                assignee=assignee or request.user,
                title=title,
                description=request.POST.get("description", ""),
                patient=patient,
                priority=request.POST.get("priority", Task.Priority.NORMAL),
            )
            messages.success(request, "Consigne envoyée à l'assistante.")
    return redirect("clinical:doctor_dashboard")
