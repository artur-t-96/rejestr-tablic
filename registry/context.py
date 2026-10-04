from django.conf import settings

from .authentication import safe_login_return, session_owner
from .demo import demo_viewer


def app_context(request):
    context = {
        "local_mode": settings.LOCAL,
        "demo_mode": settings.DEMO_MODE,
        "demo_user": demo_viewer(request.user),
        "app_name": "Dyna Rejestr Tablic",
    }
    if request.user.is_authenticated:
        context.update(
            session_owner=session_owner(request.user),
            session_return=safe_login_return(request.get_full_path()) or "/panel/",
        )
    return context
