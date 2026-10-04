from django import template

from registry.validation import display_number

register = template.Library()


@register.filter
def plate(number):
    return display_number(str(number))
