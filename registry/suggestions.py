"""Deterministyczne, wolne propozycje z różnymi zmianami części indywidualnej."""

from itertools import zip_longest

from django.core.exceptions import ValidationError

from .validation import validate_part

CHARACTERS = "ABCDEFGHIJKLMNOPRSTUVWXYZ0123456789"


def free_suggestions(part, prefix, digit, occupied):
    displayed = {f"{prefix}{d}{part}" for d in (range(10) if digit is None else (digit,))}
    suggestions = []

    def add(number):
        if number and number not in occupied and number not in displayed and number not in suggestions:
            suggestions.append(number)

    if digit is not None:
        for alternative in range(10):
            add(f"{prefix}{alternative}{part}")

    groups = (
        (part[:i] + part[i + 1 :] for i in reversed(range(len(part)))),
        (
            part[:i] + character + part[i:]
            for i in reversed(range(len(part) + 1))
            for character in "S" + CHARACTERS
        ),
        (
            part[:i] + character + part[i + 1 :]
            for i in reversed(range(len(part)))
            for character in CHARACTERS
            if character != part[i]
        ),
    )
    digits = list(range(10)) if digit is None else [digit] + [d for d in range(10) if d != digit]

    def numbers(candidates):
        seen = set()
        for candidate in candidates:
            if candidate == part or candidate in seen:
                continue
            seen.add(candidate)
            try:
                candidate = validate_part(candidate)
            except ValidationError:
                continue
            for d in digits:
                number = f"{prefix}{d}{candidate}"
                if number not in occupied:
                    yield number

    # Przeplatanie grup pozwala pokazać różne rodzaje zmian już w pierwszej dwunastce.
    for row in zip_longest(*(numbers(group) for group in groups)):
        for number in row:
            add(number)
            if len(suggestions) == 12:
                return suggestions
    return suggestions
