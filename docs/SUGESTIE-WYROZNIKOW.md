# Podpowiedzi wolnych wyróżników

Stan po uwagach odbiorcy z 04.10.2026. Wcześniejsza wersja proponowała także wyróżniki skrócone,
wydłużone i z podmienionym znakiem (specyfikacja 4.2 pkt 4). Odbiorca uznał to za mylące: kto pyta
o `M1 URBAN`, nie chce propozycji `M1 URBAA`. Wyróżnika wybranego przez właściciela nie zmieniamy.

## Reguła

- Podpowiadamy wyłącznie ten sam wyróżnik: wolne inne cyfry wybranej litery województwa, potem wolne
  cyfry drugiej litery (P ↔ M). Kolejność rosnąca.
- Nie powtarzamy numerów pokazanych już w siatce wyniku. Bez wybranej cyfry siatka pokazuje wszystkie
  dziesięć cyfr wybranej litery, więc podpowiedzi obejmują drugą literę.
- Zajętość liczona dla całego województwa: wpis aktywny, rezerwacja i wniosek w toku blokują numer;
  wpis zwolniony nie blokuje.
- HTML i API (`/api/availability/`) korzystają z tej samej funkcji `registry/suggestions.py`.

## Prezentacja

- Formularz: województwo → cyfra → wyróżnik, w kolejności znaków na tablicy.
- Numer na stronie publicznej jest zapisany jak na tablicy: `M1 URBAN`. API zwraca numer bez odstępu
  (`M1URBAN`), jak dotąd.

## Weryfikacja

`registry/test_suggestions.py`: kolejność i zakres podpowiedzi, niezmienność wyróżnika dla siedmiu
kształtów części indywidualnej i obu liter, wykluczenie zajętych, zgodność HTML z API, kolejność pól
i zapis z odstępem. Lokalnie w przeglądarce: `M`, `1`, `URBAN`.
