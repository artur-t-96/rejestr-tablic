# Rezerwacje w sprawdzarce dostępności

Specyfikacja, sekcja 4.3 Flow 2, wymaga komunikatu „zarezerwowany – wniosek w toku”
dla urzędnika. Sekcja 3 ogranicza zapytania A2 do własnego `office_id`.
Globalne sprawdzenie zajętości jest wspólne, ale dodatkowy stan jest filtrowany
według tej samej reguły co ewidencja: własny urząd A2, całe województwo A3.

## Zachowanie

- HTML i `GET /api/availability/` korzystają ze wspólnej funkcji `availability`.
- A2 i A3 otrzymują `reservation_pending` dla każdego wybranego numeru.
  Wartość jest prawdziwa tylko dla widocznego wpisu RESERVED lub SENT.
  W HTML pojawia się wtedy „Zarezerwowany – wniosek w toku”.
- Zajęty numer obcego urzędu pozostaje dla A2 „Niedostępny”; dodatkowe pole jest
  fałszywe zarówno dla obcej rezerwacji, jak i obcego przydziału.
- Publicznie i dla A0 odpowiedź zachowuje wyłącznie `number` i `available`.
  Nie ma dodatkowego pola ani komunikatu o trwającym wniosku.
- W odpowiedzi nie ma danych właściciela, urzędu, numeru sprawy ani UUID.
  Sugestie nadal obejmują tylko wolne numery. Wynik nie tworzy rezerwacji.
- Wycofanie lub wygaśnięcie przywraca dostępność. Dotychczasowe wygaszanie
  rezerwacji działa przed obliczeniem wyniku; sprawdzarka nie zmienia jego zasad.
- Konta i urzędy nieaktywne nie otrzymują dodatkowej informacji.
  Ochrona CAPTCHA, ograniczenie zapytań i `Cache-Control: no-store` obowiązują.

## Dowody i granice

`evidence/availability-status-tests.txt`: 53 testy, 52 PASS i jedno pominięcie
wymagające PostgreSQL. Zakres: selekcja cyfry/prefiksu, nowe rozróżnienie stanów,
izolacja własny/obcy urząd/UMP, dane publiczne/A0, wycofanie i wygaśnięcie,
ochrona publiczna, pełny kontrakt ról tras, HTML dostępności i regresja rdzenia.

`evidence/availability-status-http-proof.json`: rzeczywisty serwer host-native,
osobna kopia bazy z fikcyjnymi wnioskami, cztery odrębne logowania OTP i CSRF.
Pięć kontekstów (anonimowy, A0, Gniezno, Piła, UMP), każdy API GET i HTML POST:
10 sprawdzeń. Wszystkie 17 tabel biznesowych/audytu kopii zachowane podczas
odczytów; wszystkie 27 tabel głównej bazy zachowane. Testowana treść kodu jest
identyfikowana hashami źródeł w raporcie, na bazie rewizji 45ab47d.

`evidence/availability-status-browser-proof.json`: rzeczywisty Chrome użytkownika.
OTP Gniezna, Piły i UMP; dodatkowy wynik po wylogowaniu. Gniezno widzi P6ROLE
i P7ROLE jako w toku, Piła tylko własny P9ROLE, UMP wszystkie trzy. Publicznie
P6–P9 są jednakowo niedostępne. Fokus trafia do wyniku. Przy 320 px dokument
ma 320 px, karty nie mają przepełnienia i cały komunikat zawija się czytelnie.
Viewport przywrócony; pięć screenshotów 135–139 obejrzanych. Suma odczytów i
logowań zachowała 15 tabel kopii, wszystkie pola kont poza `last_login`
oraz wszystkie istniejące audyty;
jedynym nowym audytem było siedem zdarzeń `auth.login` (cztery HTTP, trzy Chrome).
Główne 27 tabel pozostało bez zmian.

Początkowe wejście Chrome trafiło na CAPTCHA po dziesięciu wcześniejszych
odczytach HTTP w tym samym oknie IP. Nie rozwiązywano ani nie omijano weryfikacji:
po upływie zwykłego 60-sekundowego okna ponownie otwarto i wysłano formularz.
To nie jest dowód pełnego scenariusza CAPTCHA.

Nie jest to nowy odbiór współbieżności, integracji operatorów ani całego WCAG.
Nie ma migracji ani zmian archiwalnych dokumentów.
