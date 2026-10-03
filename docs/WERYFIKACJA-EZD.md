# Weryfikacja etapu konektora EZD — 03.10.2026

## Wynik i granice dowodów

41 testów lokalnych przeszło (`evidence/ezd-and-core-tests.txt`): 23 dotychczasowe testy rdzenia i 18 nowych testów konektora, kolejki, współbieżności oraz odtwarzania. Ruff, Django check, zgodność migracji i kontrola diffu przeszły. Migracja 0002 zastosowana lokalnie po wykonaniu backupu.

**Nie wykonano testu z prawdziwym EZD.** Żądania HTTP w nowych testach są obsługiwane przez MockTransport. Kontrakt pochodzi z publicznego Swagger NASK; zgodność z nim jest przesłanką do testu integracyjnego, a nie dowodem działania całej integracji. Nie ma przydzielonego klucza ani instancji piaskownicy. Zgłoszenie przygotowano, nie wysłano.

## Sprawdzone lokalnie

- Algorytm parametrów OAuth, brak surowego klucza w żądaniu i brak tokenu/klucza w wynikach operacji i audycie.
- Profil urzędu, HTTPS i prywatne pliki; odmowa użycia publicznego demo do zapisu.
- Weryfikacja podmiotu sprawy, utworzenie sprawy z jawnym numerem/JRWA, multipart PDF i mapowane atrybuty.
- Odczyt PDF z dopuszczonego repozytorium, brak Bearer przy pobraniu, porównanie SHA-256.
- Jeden link sprawy i jedna operacja po równoczesnym zleceniu; niezmienny dokument w kolejce.
- Retry po błędzie połączenia/429, pomijanie zakończonych etapów i terminu ponowienia; blokada timeoutu po zapisie, 5xx i zmiany instancji.
- Uzgodnienie niepewnego wyniku z odczytem API, zgodnością przestrzeni i SHA-256; odmowa dla innego PDF/przestrzeni.
- Wykrycie przerwanego procesu. Odtworzenie snapshotu wstrzymuje oczekujące wysyłki bez zmiany działającej bazy.
- Uprawnienia formularza EZD i brak możliwości zapisu bez konfiguracji.

## Rzeczywisty interfejs lokalny

W Chrome, jako urzędnik UMP, otwarto Pisma → Zapisz w EZD. Formularz informuje o braku połączenia i ma zablokowany przycisk. Dowód: `evidence/03-ezd-formularz.jpg`. Nie utworzono pozornego zadania EZD i nie oznaczono integracji jako działającej.

Następnie zlecono lokalny e-mail pisma `DRT/2026/APPROVAL/B1AF05263D43` do fikcyjnego `gni@example.invalid`. Faktyczny backend: `django.core.mail.backends.filebased.EmailBackend`. Worker zakończył operację `26f9e0f9-7dcb-4d0d-8e1a-f4a7ac46132f` stanem `LOCAL_SAVED`, jedna próba. Odczyt pliku MIME potwierdził Message-ID oraz jeden załącznik z SHA-256 zgodnym z niezmienną kopią dokumentu. Dowód: `evidence/local-email-proof.json` i `evidence/04-integracje-kolejka.jpg`.

To dowód lokalnego procesu UI → kolejka → plik wiadomości. Nie jest to test zewnętrznego SMTP ani doręczenia.

## Pozostałe wymagania

Pełny scenariusz EZD → Dyna, zdarzenia wpływu, korespondencja wychodząca i dowody doręczeń nie są zakończone. Oczekują też e-Doręczenia, podpisy, końcowy audyt ról, dostępności i bezpieczeństwa, PostgreSQL, pełna dokumentacja wdrożenia i wszystkie pozostałe wymagania celu wskazane w `docs/STATUS.md`.

Cały cel pozostaje aktywny. Ten etap nie jest potwierdzeniem gotowości do eksploatacji ani zgodności całego produktu ze specyfikacją.
