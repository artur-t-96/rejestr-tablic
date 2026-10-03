from django import template

from registry.audit_presentation import present_event

register = template.Library()


@register.inclusion_tag("registry/history_event.html", takes_context=True)
def audit_event(context, event):
    return {**present_event(event), "show_values": context["user"].role != "ADMIN"}
