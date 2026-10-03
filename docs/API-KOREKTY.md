# Walidacja korekt przez API

Stan: 03.10.2026. `PATCH /api/records/<uuid>/` wymaga sesji urzędnika,
aktualnego tokenu CSRF i obiektu JSON. Zakres pól wynika z roli; A2 może
korygować dane pojazdu i zbycia wyłącznie własnego urzędu, A3 pola dopuszczone
przez usługę korekt. Numer pozostaje nieedytowalny.

Przykład:

```json
{
  "fields": {"sale_date": "2025-02-28"},
  "reason": "Poprawa daty sprzedaży",
  "version": 1
}
```

- `fields`: niepusty obiekt, wyłącznie dopuszczone pola.
- `reason`: niepusty tekst uzasadnienia.
- `version`: dodatnia liczba całkowita JSON; tekst, ułamek i wartość logiczna
  są błędem. Nieaktualna wersja blokuje zapis.
- Daty: istniejąca data kalendarzowa w dokładnym formacie `RRRR-MM-DD`.
  `null` albo pusty tekst oznaczają świadome wyczyszczenie pola, podlegające
  pozostałym regułom procesu. Brak pola pozostawia dotychczasową wartość.
- Pozostałe pola: tekst JSON; struktury, liczby i `null` nie są automatycznie
  zamieniane na tekst.

Niepoprawne dane zwracają JSON z błędem i HTTP 400. Nie zapisują korekty ani
zdarzenia `plate.updated`. Nadal obowiązują reguły chronologii sprzedaży,
obowiązkowych danych wydania, wersji wpisu, aktywnego wniosku i urzędu.
Obsługa zaległego wygaśnięcia rezerwacji przed odczytem wpisu pozostaje osobnym
procesem; nie jest korektą danych z żądania PATCH.

Wspólna osłona operacji API odrzuca treść JSON inną niż obiekt i nietekstowe
uzasadnienie. Brak sesji: 401, niedozwolona rola/pole: 403, cudzy wpis A2: 404.
CSRF jest sprawdzany przez middleware także dla API.

## Dowody i ograniczenia

Przed poprawką test otrzymał HTTP 200 dla `sale_date: "niepoprawna data"`:
data została usunięta, status `SOLD` zmieniony na `ISSUED`, wersja zwiększona.
Walidacja teraz odrzuca taką korektę przed wywołaniem usługi zapisu.

`evidence/api-record-validation-tests.txt`: 54 testy, 53 PASS i jeden SKIP
wymagający PostgreSQL. Zestaw obejmuje nową walidację, dotychczasowe korekty,
przekazanie urzędu, logowanie i rdzeń procesu. Dla odrzuconych korekt porównuje
wszystkie pola wpisu oraz audyt. Dla niepoprawnych obiektów JSON na pozostałych
trasach porównuje osiem tabel. Poprawna korekta ma dokładne wartości przed/po
i autora. Ruff PASS. Nie zmieniono schematu ani transakcji; PostgreSQL w tym
etapie nie uruchamiano.

`evidence/api-record-validation-http.json`: 12 rzeczywistych scenariuszy HTTP
na porcie 8776, osobna kopia SQLite i fikcyjny wpis `P8API`. Logowanie przez
rzeczywiste jednorazowe kody zapisane do lokalnych plików poczty, bez
podstawiania sesji. Negatywne żądania zachowały osiem tabel; poprawna data
zachowała status sprzedaży, `null` jawnie usunął datę z uzasadnieniem,
nieaktualna wersja nie zapisała danych. Piła 404, administrator 403,
brak CSRF 403. Raport zawiera hashe trzech plików kodu i testów.

To odbiór backendu przez HTTP. Nie wykonano zewnętrznego SMTP, API operatora,
wdrożenia Linux ani ponownego pełnego odbioru wszystkich ekranów Chrome.
Główna baza nie służyła do tych mutacji.
