# Odmowa, przedłużenie i wygasanie — odbiór 03.10.2026

Rezerwacja nowego numeru trwa 14 dni. UMP może przedłużyć niewygasły wpis
RESERVED/SENT z powodem; powiat nie ma takiej czynności. Odmowa UMP wymaga
uzasadnienia, zmienia wniosek na REJECTED, zwalnia numer i generuje pismo
zwrotne. Dokumenty oraz dotychczasowa historia zostają w bazie.

## Automatyczne wygasanie

`scripts/run-local.sh` uruchamia osobny proces co 30 sekund i zatrzymuje go
wraz z serwerem. Przy ręcznym uruchamianiu aplikacji:

```sh
.venv/bin/python manage.py expire_reservations --watch --interval 30
```

Interwał dopuszcza 1–3600 sekund. Bez `--watch` polecenie wykonuje jeden
przebieg, jak dotąd; timer systemd nadal korzysta z tego wariantu.
Awaria procesu nie jest ukrywana. Proces trzeba monitorować i uruchamiać
ponownie przez nadzorcę usług opisany w instrukcji wdrożeniowej.

Wygasanie dotyczy wyłącznie RESERVED/SENT z terminem, który upłynął.
Nie zwalnia ALLOCATED, ISSUED ani SOLD, nawet przy pozostawionym dawnym terminie.
W jednej transakcji zapisuje RELEASED, wersję wpisu, EXPIRED właściwych
wniosków oraz `reservation.expired` i `request.expired`. Audyt ma aktora
systemowego, urząd, poprzedni status, termin i powód. Blokowanie jest w kolejności
wpis → wniosek. Powtórny przebieg nie dopisuje drugiej historii tego wygaszenia.
Awaria zapisu audytu wycofuje oba statusy.

Bezpośrednie linki do wniosku/wpisu oraz odczyty API odświeżają zaległe
wygasanie przed pokazaniem danych. Administrator techniczny jest odrzucany
przed tą operacją. Wygasły wniosek nie pokazuje decyzji lub wycofania;
wyjaśnia zachowanie historii i tworzenie nowej rezerwacji przez nowy wniosek.
Nie zakłada, że numer nadal jest wolny — mógł już zostać ponownie zarezerwowany.
Nieistniejący identyfikator przedłużenia daje 404 zamiast błędu serwera.

## Dowody

- Nowe testy najpierw odtworzyły luki: stary status na bezpośrednim ekranie/API,
  brak zdarzenia `request.expired`, brak trybu watch i 500 przy obcym UUID.
  `evidence/reservation-completion-before.txt` jest historycznym wynikiem
  przed poprawką, nie bieżącą awarią.
- Końcowy zestaw: **48 testów SQLite, 46 PASS/2 SKIP** (1.555 s) i **48 PASS
  PostgreSQL** (2.305 s). `reservation-completion-final-sqlite.txt` oraz
  `reservation-completion-final-postgres.txt` w evidence. Obejmuje nowe
  zachowanie, istniejący rdzeń, blokady PostgreSQL, HTTP i statusy czynności.
  To dwa przebiegi pokrywającego się zestawu, nie 96 różnych scenariuszy.
- Dwa rzeczywiste wątki/połączenia wygaszają jedną rezerwację: wyniki 0 i 1,
  oba statusy poprawne i po jednym zdarzeniu audytu. Wcześniejszy test oczekiwania
  wycofania na blokadę również przeszedł na PostgreSQL. Nie użyto kontenerów.
- Chrome, kopia bazy na porcie 8776: Gniezno złożyło W/2026/00006 (P6ODMW)
  i W/2026/00007 (P6TERM), oba z rzeczywistym PDF wniosku. Powiat nie ma
  przedłużenia. UMP otrzymał błąd odmowy bez powodu, potem zapisał odmowę
  z powodem; P6ODMW ma REJECTED/RELEASED i pismo DRT/ump/2026/000003.
- PDF odmowy: jedna strona, SHA-256 zgodny z bazą; treść numeru, sprawy,
  uzasadnienia i linku poprawna. Poppler renderował stronę do PNG; odczyt
  wizualny potwierdził polskie znaki, odstępy, kod QR, stopkę i brak ucięć.
  Dokument pozostaje oznaczony jako lokalny wzór wymagający zatwierdzenia.
  Nie podpisywano go ani nie wysyłano do operatora.
- UMP przedłużył P6TERM z 17.10 na 24.10 dokładnie o siedem dni, z powodem
  i audytem. Początkowe 14 dni zweryfikowano względem chwili utworzenia.
- Wyłącznie w odizolowanej kopii skrócono termin fikcyjnego P6TERM do trzech
  sekund. Osobny natywny worker `--interval 1` zmienił SENT/SENT na
  EXPIRED/RELEASED przed pierwszym odczytem tej zmiany w przeglądarce.
  Nie zmieniano zegara laptopa ani głównej bazy. Worker zgłosił jedną
  zwolnioną rezerwację; ponowne odczyty zachowały pojedyncze zdarzenia.
- Chrome pokazał objaśnienie wygaśnięcia, oryginalny PDF i historię bez
  decyzji/wycofania. Wpis nie ma przedłużenia. Publiczny formularz bez
  zalogowania pokazał P6ODMW i P6TERM jako dostępne bez danych właścicieli.
- `evidence/reservation-ui-proof.json` i `reservation-watch-process.txt`
  zawierają stan i sumy; prywatne zrzuty 98–100 oraz PDF pozostają poza Git.
- Backup/restore kopii: siedem tabel biznesowych i audyt identyczne,
  sesje i OTP unieważnione; `evidence/reservation-backup-proof.json`.
  Te same siedem tabel głównej bazy bez zmian. Bez migracji schematu.

## Granice odbioru

Nie czekano rzeczywistych 14 dni, nie odebrano timera na serwerze Linux ani
systemu urzędu. Brak zewnętrznego doręczenia, kwalifikowanego podpisu i nowego
audytu całego WCAG. Techniczne nazwy zdarzeń w historii nadal wymagają
dopracowania interfejsu. Pozostałe wymagania i dostęp do API opisuje STATUS.md;
cel całego systemu pozostaje aktywny.

Aktualizacja interfejsu: czytelne nazwy zdarzeń, daty i tabela zmian zostały
wdrożone w następnym etapie `AUDYT-I-HISTORIA.md`; powyższa uwaga o technicznych
nazwach opisuje wcześniejszy stan odbioru rezerwacji.
