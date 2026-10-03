"""Powrót po OTP wyłącznie do panelu tej samej instalacji."""

from urllib.parse import unquote, urlsplit

from django.utils.http import url_has_allowed_host_and_scheme


def safe_login_return(value):
    if (
        not isinstance(value, str)
        or len(value) > 2048
        or not value.startswith("/panel/")
        or "\\" in value
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
        or not url_has_allowed_host_and_scheme(value, allowed_hosts=set(), require_https=True)
    ):
        return ""
    path = unquote(urlsplit(value).path)
    if (
        "\\" in path
        or any(part in {".", ".."} for part in path.split("/"))
        or any(ord(char) < 32 or ord(char) == 127 for char in path)
    ):
        return ""
    return value


def session_owner(user):
    """Identyfikator kontekstu konta; nie jest tokenem uwierzytelnienia."""
    return f"{user.pk}:{user.role}:{user.office_id or ''}"
