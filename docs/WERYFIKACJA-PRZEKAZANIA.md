# Przekazanie wpisu i izolacja urzędów

Stan: 03.10.2026. Poprawka lokalna; pełny odbiór systemu pozostaje otwarty.

## Problem i przyjęta zasada

UMP może zmienić urząd prowadzący wpis. Przed poprawką poprzedni urząd nie miał
już dostępu do ewidencji ani jej API, ale nadal mógł odczytać aktualnego
właściciela, adres, VIN i późniejsze korekty przez swój pierwotny wniosek.
Test odtworzył tę drogę ujawnienia danych. Dwa dodatkowe testy wykazały brak
blokady przekazania wniosku oczekującego na decyzję oraz wybór nieaktywnego
urzędu przez usługę zapisu.

Wniosek zachowuje pierwotny urząd i autora, znak sprawy oraz dokumentację
korespondencji. Zmiana urzędu prowadzącego nie przepisuje historii wnioskodawcy
ani nie regeneruje jego PDF. Dostęp do aktualnych danych wpisu wynika natomiast
z jego bieżącego urzędu. UMP zachowuje dostęp do całej ewidencji.

## Zmiana

- Widok wniosku osobno sprawdza prawo do powiązanego wpisu. Dawny urząd widzi
  numer i swoją sprawę, bez aktualnych danych właściciela, pojazdu, linku do
  ewidencji oraz późniejszych korekt. Komunikat wskazuje pierwotny PDF.
- Historia wpisu na stronie wniosku jest udostępniana tylko po sprawdzeniu
  dostępu do wpisu; dla powiatu obejmuje zdarzenia jego urzędu. Historia samego
  wniosku pozostaje dostępna jego wnioskodawcy.
- Przekazanie jest blokowane, gdy istnieje powiązany wniosek w DRAFT lub SENT.
  Wniosek należy wcześniej rozpatrzyć lub wycofać. Zapobiega to rozdzieleniu
  aktywnego procesu decyzyjnego między dwa urzędy.
- Urząd docelowy musi istnieć i być aktywny; kontrola działa także w API.
- Zmiana urzędu podlega istniejącej kontroli roli UMP, wersji wpisu, transakcji
  i audytowi wartości przed/po. Nie wymaga migracji ani zmiany istniejących danych.

## Testy

PostgreSQL 18.6, bez kontenerów: **28/28 PASS**, 0,865 s. SQLite: **27 PASS,
1 SKIP**, 0,644 s. Zakres to 6 nowych testów procesu przekazania, 1 rzeczywisty
test współbieżności i 21 dotychczasowych testów rdzenia. Na SQLite pominięto
wyłącznie test wymagający blokad SELECT FOR UPDATE PostgreSQL.

Sprawdzono ochronę całej odpowiedzi HTML, historię zmian, GET/PATCH ewidencji,
CSV, dostęp UMP i nowego urzędu, zachowanie autora i urzędu pierwotnego wniosku,
bajty pierwotnego PDF, blokadę transferu DRAFT/SENT i nieaktywny cel.

W teście współbieżności pierwsza transakcja trzymała blokadę podczas przekazania.
Potwierdzono w pg_stat_activity oczekiwanie drugiej transakcji dawnego urzędu.
Po commit przekazania druga transakcja ponownie sprawdziła office_id, nie znalazła
wpisu w swoim zakresie i nie zapisała danych. Wersja wzrosła wyłącznie o jeden,
a niedozwolona korekta nie pojawiła się w ewidencji.

Dodatkowo Ruff, kontrola diff i makemigrations --check --dry-run PASS.

## Chrome i rzeczywista lokalna baza

Utworzono osobną bazę `drt_transfer_ui_20261003` i dane fikcyjne. Główna baza
SQLite oraz bazy prób odtworzenia nie zostały użyte do tego scenariusza.

1. Gniezno zalogowało się rzeczywistym kodem OTP i odczytało własny zaakceptowany
   wniosek W/2026/00001 / P0 DYNA.
2. UMP zalogowało się OTP i w formularzu przekazało wpis do Piły, zmieniając
   fikcyjnego właściciela, adres i dane pojazdu z uzasadnieniem.
3. Gniezno zachowało własny wniosek i odnośniki do pierwotnych pism. Bieżące dane
   i korekta UMP zostały ukryte. Bezpośredni URL ewidencji pokazał Not Found.
4. Piła zalogowała się OTP, odczytała wpis i zapisała markę pojazdu. W historii
   pojawiły się autor Piła, uzasadnienie i wartości zmiany.
5. Gniezno zalogowało się ponownie. Dawny wniosek nadal nie ujawniał aktualnego
   właściciela, VIN ani nowej korekty Piły.
6. Odczyt bazy potwierdził pierwotne office_id=gni wniosku, bieżące office_id=pil
   wpisu, dwóch autorów korekt oraz pierwotnego właściciela w niezmienionym PDF.

Zrzuty 14 i 15 obejrzano wizualnie. Po próbie zatrzymano osobną aplikację i
klaster PostgreSQL; dane testu zachowano. Główną aplikację uruchomiono z nowym
kodem na porcie 8765, sprawdzono publiczny interfejs i health. Sumy wszystkich
wierszy sześciu tabel biznesowych przed i po restarcie są identyczne.

Dowody: `evidence/office-transfer-postgres-tests.txt`,
`evidence/office-transfer-sqlite-tests.txt`, `evidence/office-transfer-ui-proof.json`,
`evidence/office-transfer-old-ui.txt`, `evidence/14-przekazanie-dawny-urzad.jpg`,
`evidence/15-przekazanie-nowy-urzad.jpg`, `evidence/health-after-office-transfer.json`.

Próba nie jest pełnym audytem wszystkich uprawnień ani testem infrastruktury
urzędu. Nie obejmuje rzeczywistych API operatorów; te wymagania są nadal otwarte.
