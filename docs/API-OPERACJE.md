# Walidacja wniosków, decyzji i wydania przez API

Stan: 03.10.2026, zmiana na bazie `fa45920`. API wymaga sesji urzędnika
oraz CSRF dla zapisu. Ten etap obejmuje POST wniosków, submit/withdraw/decide,
POST pul i issue; korekty PATCH opisuje `API-KOREKTY.md`.

## Kontrakt danych

- Treść jest obiektem JSON. Powtórzone klucze, także zagnieżdżone, NaN,
  Infinity i nadmierne zagnieżdżenie zwracają HTTP 400.
- Wniosek: kind, number, owner, address, vin, case_number, station,
  justification są tekstami; count jest dodatnią liczbą całkowitą JSON.
  Reguły wymaganych pól i długości nadal sprawdza formularz danego modułu.
  Urząd i autor wynikają z sesji; klient nie może ich narzucić.
- Submit: pusty obiekt `{}`. Withdraw: opcjonalny tekst reason; wymagania
  uzasadnienia wynikają z procesu. Nieobsługiwane pola nie są ignorowane.
- Decide: approve jest obowiązkową wartością logiczną JSON, reason tekstem.
  Odmowa wymaga niepustego powodu. Decyzję wykonuje wyłącznie UMP.
- Akceptacja II/III nadaje kolejny blok numerów wyliczony przez serwer
  (`UWAGI-UMP-20261029.md`); decide nie przyjmuje niepustego obiektu pool
  (null oznacza jego brak). Urząd, rodzaj i stacja wynikają z wniosku.
- Bezpośrednie POST pul jest dostępne wyłącznie UMP. Dopuszczone pola:
  wyłącznie kind i office (teksty). Zakres, prefiks i daty nadaje system;
  odpowiedź zawiera first_number i last_number. Tablice tymczasowe (III)
  można przydzielać bez wniosku.
- Daty: istniejący dzień kalendarzowy w formacie RRRR-MM-DD. Opcjonalny
  valid_until może mieć null/pusty tekst; valid_from nie może.
- Issue: obowiązkowe slot (dodatnia liczba całkowita JSON) i case_number
  (niepusty tekst, najwyżej 100 znaków). Ułamki, tekstowe identyfikatory i
  wartości logiczne nie wskazują innego numeru przez konwersję. Wspólna
  usługa egzekwuje limit sprawy także dla formularza HTML.

Poprawny przydział nadal podlega kolizjom, ważności, kolejności numeracji,
liczbie z wniosku i transakcji. Zmiana nie dodaje migracji ani zmienia blokad.
Błędne dane zwracają 400; niedozwolona rola 403; obcy/nieistniejący numer
404. Typy są celowo ścisłe: klient wysyłający wcześniej `"1"` zamiast `1`
musi poprawić żądanie.

## Dowody i granice

- Odtworzono pięć błędów: case_number null powodował 500, ułamkowy slot
  wydawał inną pozycję, zbyt długa sprawa była przyjmowana przez SQLite,
  obiekt właściciela zapisywano jako tekst, ułamkowy zakres decyzji obcinano.
- 81/81 testów SQLite PASS: nowe regresje, korekty API, rdzeń, formularze
  pul, mały układ i powiadomienia decyzji. Ruff i format PASS.
  Wynik: `evidence/api-operations-validation-tests.txt`.
- 49 sprawdzeń rzeczywistego lokalnego HTTP na osobnej kopii SQLite,
  z prawdziwym OTP do pliku i CSRF. Pełny I: wniosek → złożenie → akceptacja
  → rejestracja → zbycie; II/III: wniosek → decyzja → wydanie. Także odmowa,
  wycofanie, bezpośrednia pula II, kolizja, błędne typy/daty, inne urzędy i A0.
  Negatywne operacje zachowały osiem tabel, łącznie z audytem i numeracją.
  `evidence/api-operations-validation-http.json` zawiera hashe źródeł.
- Główne osiem tabel, w tym audyt, pozostało bez zmian w czasie testów HTTP.
  Kopia nie uruchamiała workerów wysyłkowych; nie wykonano zewnętrznego API.
- To odbiór opisanych operacji backendu, bez nowego testu Chrome, PostgreSQL,
  wyścigu, wyglądu PDF ani pełnego WCAG. Poprzednie dowody mają własne rewizje.
  Cały cel pozostaje aktywny; brak zdalnego repozytorium, CI i wdrożenia urzędu.
