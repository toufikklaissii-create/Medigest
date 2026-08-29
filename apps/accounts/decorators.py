from functools import wraps

from django.http import HttpResponseForbidden


def role_required(*roles):
    """Restrict a view to users whose profile.role is one of `roles`."""

    def decorator(view_func):
        @wraps(view_func)
        def wrapped(request, *args, **kwargs):
            profile = getattr(request.user, "profile", None)
            if not request.user.is_authenticated or profile is None or profile.role not in roles:
                return HttpResponseForbidden("Accès refusé : rôle insuffisant.")
            return view_func(request, *args, **kwargs)

        return wrapped

    return decorator
