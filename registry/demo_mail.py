"""Na instancji demonstracyjnej korespondencja obiegu trafia do skrzynki w aplikacji.

Treść pism i powiadomień pochodzi od kont demo, więc nie wysyłamy jej prawdziwą pocztą nawet
na rzeczywisty adres kontaktowy urzędu. Prawdziwą pocztą idą tylko kody logowania i zaproszenia
do kont rzeczywistych (`workflow=False`).
"""

from django.conf import settings

from .demo import is_demo_email
from .models import DemoMessage


def deliver(message, *, workflow=True):
    """Zwraca 1 jak `EmailMessage.send()`, gdy wiadomość przyjęto do wysyłki lub skrzynki demo."""
    if not settings.DEMO_MODE:
        return message.send()
    stored = [address for address in message.to if workflow or is_demo_email(address)]
    for address in stored:
        DemoMessage.objects.create(
            recipient=address.lower(),
            subject=message.subject[:300],
            body=message.body,
            attachments=[item[0] for item in message.attachments if isinstance(item, tuple)],
        )
    message.to = [address for address in message.to if address not in stored]
    if message.to:
        return message.send()
    return 1 if stored else 0


def demo_only(recipients, *, workflow=True):
    """Czy wiadomość zostanie w całości w skrzynce demo (status „zapisano lokalnie”)."""
    return (
        settings.DEMO_MODE
        and bool(recipients)
        and (workflow or all(is_demo_email(address) for address in recipients))
    )
