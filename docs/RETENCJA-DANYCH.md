# Minimalizacja danych i przygotowanie retencji

Stan: 03.10.2026, na bazie `319c543`. Specyfikacja pozostawia retencję danych
do ustalenia. Aplikacja zachowuje dane spraw i dokumenty; okresy oraz sposób
ich archiwizacji, anonimizacji i usunięcia wymagają decyzji urzędu.

Podstawa do ustalenia polityki: art. 5 ust. 1 lit. c i e oraz art. 25
[RODO w oficjalnym EUR-Lex](https://eur-lex.europa.eu/eli/reg/2016/679/oj/eng).
Obejmują minimalizację, ograniczenie przechowywania i ochronę danych przy
projektowaniu. Nie wyznaczają jednego okresu przechowywania wszystkich klas
tej aplikacji. Próg techniczny opisany poniżej jest rekomendacją projektu,
nie ustaleniem kategorii archiwalnej spraw urzędu.

## Zakres danych i decyzje urzędu

| Dane | Obecne zabezpieczenie / zachowanie | Decyzja do wdrożenia urzędowego |
|---|---|---|
| Wnioski, ewidencja, właściciel i pojazd | Brak pól PESEL/REGON; dane według procesu. A2 własny urząd, A3 województwo, publicznie wyłącznie dostępność. | Podstawa i cel, okres, początek liczenia, kwalifikacja archiwalna, wyłączenia i blokady usunięcia. |
| Pule i wydania | Urząd, zakres, okres/stacja, wydający i sprawa; kontrola kolizji. | Okres historii wydań i dokumentów źródłowych; los numeru po anonimizacji. |
| PDF, podpisy, wpływy i dowody operatora | Oryginalne bajty, hash i powiązanie ze sprawą. | Archiwum właściwe, zakres przechowywania w aplikacji, sprawdzenie podpisów i ślad przekazania. |
| Dziennik audytowy | Chroniona historia operacji i korekt; nie usuwana przez porządkowanie techniczne. | Osobny okres, dostęp i wymogi rozliczalności/archiwizacji. |
| Konta, zaproszenia i powiadomienia | Role, domeny, dezaktywacja i trwały status obsługi. | Okres po dezaktywacji; powiązania z audytem i sprawami; treści wiadomości i wyniki wysyłki. |
| OTP i sesje w bazie | Ważność i jednorazowość OTP, termin sesji; opcjonalne porządkowanie poniżej. | Zatwierdzenie technicznego progu i harmonogramu. |
| Liczniki i wyzwania publiczne | Dotychczasowy ograniczony zakres porządkowania, oparty na czasie. | Monitoring wykonania i wymagania incydentowe. |
| Lokalna skrzynka MIME, źródłowe CSV/XLSX, eksporty, kopie i logi | Osobne pliki poza tabelami; nie są objęte nowym usuwaniem. Lokalnie wyłącznie dane fikcyjne. | Polityka plików i kopii, bezpieczne przechowywanie, kanały eksportu i sposób zniszczenia. |
| Sekrety / klucze podpisu | Chroniona konfiguracja i osobna kopia; nie w repozytorium ani raporcie. | Cykl życia kluczy, uprawnienia i kopia zgodnie z profilem urzędu. |

Numery, serie i historia przydziałów nie są zerowane przez upływ okresu
przechowywania danych osobowych. Projekt docelowej anonimizacji musi
zachować unikalność, zakaz ponownego przydziału aktywnego numeru, spójność
powiązań i wymagane dokumenty. Zwolnienie numeru pozostaje decyzją UMP.

## Inwentaryzacja do ustalenia polityki

Na skonfigurowanym środowisku administrator hosta wykonuje:

```sh
.venv/bin/python manage.py retention_inventory
```

Raport JSON jest wyłącznie odczytowy. Zawiera 19 klas: ewidencja, wnioski,
pule, numery puli, pisma, zadania integracji, dowody, wpływy i linki EZD,
zaproszenia, audyt, OTP, sesje, konta, urzędy, sekwencje, szablony, wyzwania
publiczne oraz liczniki. Pokazuje liczby, najstarsze/najnowsze daty i kategorie
zadeklarowane w modelach. Nieznana kategoria jest UNKNOWN; pola bez
zadeklarowanego słownika nie są drukowane jako grupy.

Nie drukuje właścicieli, adresów, e-maili, numerów, identyfikatorów wierszy,
hashy haseł, kodów, sesji, treści audytu ani dokumentów. Nie wczytuje BLOB-ów.
Raport ma charakter operacyjny: zapytania wykonywane kolejno mogą obserwować
zmiany pracującej aplikacji. Nie jest spójną kopią ani podglądem konkretnych
wierszy do zniszczenia. Dotyczy bazy, nie inwentaryzacji systemu plików.
Przechowuj go jako wewnętrzny materiał administracyjny z ograniczonym dostępem.

## Opcjonalne porządkowanie wygasłego uwierzytelniania

Dotychczasowy zakres i timer `dyna-security.service` obejmują wygasłe wyzwania
publiczne i liczniki starsze niż dobę. Zachowano ich zachowanie. Rozszerzenie
na OTP i sesje wymaga jawnego `--include-auth`; domyślnie jest wyłączone.

Podgląd rozszerzonego zakresu, bez zmiany danych:

```sh
.venv/bin/python manage.py purge_security_state --include-auth --json
```

Warunki: `LoginCode.expires_at <= teraz - 24 h`,
`Session.expire_date <= teraz - 24 h`. Uwzględnia użyte i nieużyte kody;
stan used nie przyspiesza usuwania. Wygasłe dopiero w ostatniej dobie i
niewygasłe kody/sesje pozostają. Doba jest marginesem technicznym po
wygaśnięciu, a nie okresem liczonym od utworzenia konta/kodu.

Zapis po przeglądzie zakresu i zatwierdzeniu operacji przez administratora:

```sh
.venv/bin/python manage.py purge_security_state --apply --include-auth --json
```

Polecenie ponownie wyznacza próg czasu. Raport podaje tryb, próg, kandydatów
i faktycznie usunięte liczby; nie drukuje danych wierszy. Operacja obejmuje
jedną transakcję bazy. Błąd cofa całość. Kolejne wykonanie jest bezpieczne dla
tego samego zakresu. Nie usuwa kont, audytu, spraw, numeracji, dokumentów ani
plików MIME. Zapisy techniczne usunięte z bazy odzyskuje się z właściwej
chronionej kopii, nie z tego raportu.

Nie uruchamiano tego rozszerzenia na głównej bazie. Nie zmieniono timera.
Po zatwierdzeniu technicznej polityki administrator może dodać
`--include-auth` do dotychczasowego ExecStart, sprawdzić podgląd, kopię i
harmonogram. Produkcyjne usunięcie wymaga jawnego zatwierdzenia konkretnego
zakresu; w tej realizacji wykonano je tylko na osobnej fikcyjnej kopii.

## Dowody lokalne

- `evidence/security-retention-tests.txt`: 33 testy, 32 PASS/1 SKIP wymagający
  PostgreSQL. Zakres: retencja techniczna, logowanie, sesje i ochrona publiczna.
  Granica czasu, aktywne i niedawno wygasłe dane, zachowanie starego zakresu,
  powtórzenie, cofnięcie po wstrzykniętym błędzie oraz brak treści w raporcie.
- `evidence/security-retention-native-proof.json`: rzeczywiste polecenia
  Django na osobnej kopii SQLite. Podgląd bez zapisu; podstawowy apply zachował
  OTP/sesje; jawny rozszerzony apply usunął dwa fikcyjne stare kody i dwie stare
  sesje; ponowienie usunęło zero. Wszystkie pozostałe tabele kopii zachowane.
- `evidence/retention-inventory-local.json`: zbiorczy odczyt rzeczywistych
  lokalnych danych fikcyjnych; 19 klas. Wszystkie tabele głównej bazy zachowane.
- Ruff/format PASS, bez nowych migracji. Nie wykonano nowego PostgreSQL,
  systemd, procedury biznesowego brakowania ani odbioru polityki przez urząd.

## Formularz decyzji urzędu

Dla każdej klasy urząd uzupełnia: właściciel procesu i administrator danych;
cel i podstawa; zatwierdzony zakres pól; kwalifikacja archiwalna; zdarzenie
rozpoczynające bieg; okres i jednostka; sytuacje zatrzymujące usunięcie;
archiwum docelowe; zakres anonimizacji; osoba zatwierdzająca; podgląd i dowód
przekazania; skutki dla kopii/logów/eksportów; test odtworzenia oraz data
zatwierdzenia polityki. Wdrożenie konkretnych zasad następuje po tej decyzji.
Stan danych biznesowych pozostaje `requires_office_decision`.
