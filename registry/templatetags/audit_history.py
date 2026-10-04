from django import template

from registry.accounts import account_label
from registry.audit_presentation import present_event
from registry.demo import demo_viewer

register = template.Library()


@register.inclusion_tag("registry/history_event.html", takes_context=True)
def audit_event(context, event):
    viewer = context["user"]
    return {
        **present_event(event, viewer),
        "show_values": viewer.role != "ADMIN",
        # Konta demo są wspólne dla wielu osób: nie pokazujemy im adresów IP ani identyfikatorów kont.
        "show_origin": not demo_viewer(viewer),
    }


@register.filter
def account_name(account, viewer):
    """Samo imię i nazwisko konta, z tą samą maską dla kont demo."""
    return account_label(account, viewer=viewer) if account else ""


@register.filter
def account_for(account, viewer):
    """Podpis konta dla danego oglądającego; konto demo nie widzi danych kont rzeczywistych."""
    return account_label(account, viewer=viewer, with_email=True) if account else ""
