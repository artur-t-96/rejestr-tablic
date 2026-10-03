# Uprawnienia do wniosków o pule II/III

03.10.2026, poprawka po `9fce1d8a72bcb01e3fa4316c9822bf0aa97c7633`.
Specyfikacja §3 przyznaje „Wniosek o nową pulę” tylko A2. A3 nadal
składa wniosek indywidualny w imieniu UMP i przydziela pule.

## Poprawione zachowanie

Przed zmianą wspólna usługa dopuszczała utworzenie wniosku II/III przez UMP.
Macierz wszystkich tras sprawdzała dla tej trasy poprawny wniosek I;
nie rozróżniała uprawnienia zależnego od rodzaju wniosku.

Usługa blokuje teraz utworzenie II/III przez UMP przed wygaszaniem rezerwacji,
numeracją, zapisem wniosku, audytu lub PDF. API i spreparowany formularz
z poprawnymi danymi II/III odpowiadają 403. Formularz UMP oferuje wyłącznie I
i pomija pola liczby numerów/stacji. Link do wniosku o pulę jest dostępny A2.

Ograniczenie obejmuje również złożenie już istniejącego szkicu II/III,
w tym starego szkicu przypisanego UMP. UMP przegląda szkic puli bez przycisku
„Złóż wniosek do UMP”; backend odmówi również bezpośredniego POST.
Nie zmieniamy ani nie usuwamy dawnych wniosków i dokumentów.

Wnioski I UMP oraz wnioski II/III powiatów pozostają dostępne. UMP nadal
rozpatruje złożone wnioski II/III i bezpośrednio nadaje pulę II. Nie ma migracji.

## Dowody lokalne

- Próby przed zmianą odtworzyły brak blokady tworzenia, błędne opcje/link
  oraz możliwość złożenia istniejącego szkicu. Wyniki:
  `evidence/pool-request-roles-before-fix.txt` i
  `evidence/pool-request-submit-before-fix.txt`.
- **54/54 testy PASS** w 5,652 s: dziesięć nowych testów, dotychczasowe role
  tras, audyt IP pism, walidacja operacji API i rdzeń. Odmowa tworzenia ma
  próbkę wygasłej rezerwacji, aby wykazać brak skutków ubocznych także dla
  cudzych danych. Testy złożenia obejmują szkice powiatu i UMP oraz HTML/API.
  `evidence/pool-request-roles-tests.txt`. Ruff, format, Django check
  i kontrola braku migracji przeszły.
- **17 rzeczywistych operacji POST HTTP** na świeżej kopii SQLite, z dwiema
  sesjami OTP zapisanymi do plików i rzeczywistym CSRF. Osiem odmów tworzenia
  i złożenia II/III przez UMP; po każdej wszystkie 27 tabel identyczne.
  Dziewięć operacji dozwolonych: I UMP przez HTML/API, II/III powiatu,
  złożenie przez powiat, decyzje UMP i bezpośrednia pula II.
  `evidence/pool-request-roles-http-proof.json` zachowuje hashe końcowego kodu.
- Chrome: logowanie UMP i powiatu, porównanie formularzy/menu i dwa zapisy
  (I UMP, III powiatu). Pięć obejrzanych zrzutów 144–148 oraz
  `evidence/pool-request-roles-browser-report.json`. Ta próba poprzedzała
  końcową blokadę złożenia szkicu; formularz tworzenia i lista pul nie
  zmieniły się później.
- Końcowy Chrome: UMP widzi szkic III bez złożenia oraz rzeczywiście składa
  własny szkic I do stanu SENT. Szkic III przygotowano natywną usługą jako
  oznaczony fikcyjny obiekt. Dwa obejrzane zrzuty 149–150 oraz
  `evidence/pool-request-submit-browser-report.json`.
- Zachowano 58 dawnych audytów, 12 PDF i wszystkie 27 tabel głównej bazy.
  Próby biznesowe korzystały z oddzielnych baz; nie uruchamiano Dockera,
  PostgreSQL, zewnętrznych operatorów ani produkcji.

To uzupełnienie kontroli konkretnego wiersza macierzy §3. Dotychczasowe
`ROLE-I-TRASY.md` zachowuje datę i zakres swoich dowodów. Pełny odbiór
publicznej dostępności i rzeczywistych integracji pozostaje otwarty.
