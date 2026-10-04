"""Wolne propozycje z tym samym wyróżnikiem: inne cyfry i druga litera województwa."""

PREFIXES = ("P", "M")


def free_suggestions(part, prefix, digit, occupied):
    displayed = {f"{prefix}{d}{part}" for d in (range(10) if digit is None else (digit,))}
    # Wyróżnika wybranego przez właściciela nie zmieniamy; najpierw litera, o którą pytał.
    letters = (prefix, *(letter for letter in PREFIXES if letter != prefix))
    numbers = (f"{letter}{d}{part}" for letter in letters for d in range(10))
    return [number for number in numbers if number not in occupied and number not in displayed]
