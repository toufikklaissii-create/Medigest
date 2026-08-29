from .views import _active_tasks_for


def active_task_count(request):
    if not request.user.is_authenticated:
        return {}
    return {"active_task_count": _active_tasks_for(request.user).count()}
