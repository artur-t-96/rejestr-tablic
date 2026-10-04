"""W trybie demo wiadomości do adresów demonstracyjnych trafiają do skrzynki w aplikacji."""

from django.conf import settings

from .demo import is_demo_email
from .models import DemoMessage


def deliver(message):
    """Zwraca 1 jak `EmailMessage.send()`; adresy rzeczywiste idą zwykłą pocztą."""
    if not settings.DEMO_MODE:
        return message.send()
    demo = [address for address in message.to if is_demo_email(address)]
    for address in demo:
        DemoMessage.objects.create(
            recipient=address.lower(),
            subject=message.subject[:300],
            body=message.body,
            attachments=[item[0] for item in message.attachments if isinstance(item, tuple)],
        )
    message.to = [address for address in message.to if not is_demo_email(address)]
    if message.to:
        return message.send()
    return 1 if demo else 0


def demo_only(recipients):
    return settings.DEMO_MODE and bool(recipients) and all(is_demo_email(address) for address in recipients)
