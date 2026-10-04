from django import template

from registry.accounts import account_label
from registry.audit_presentation import present_event

register = template.Library()


@register.inclusion_tag("registry/history_event.html", takes_context=True)
def audit_event(context, event):
    return {**present_event(event, context["user"]), "show_values": context["user"].role != "ADMIN"}


@register.filter
def account_for(account, viewer):
    """Podpis konta dla danego oglądającego; konto demo nie widzi danych kont rzeczywistych."""
    return account_label(account, viewer=viewer, with_email=True) if account else ""
