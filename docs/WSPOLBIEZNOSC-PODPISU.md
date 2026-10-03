# Podpis i kolejka — rzeczywiste transakcje PostgreSQL

Stan: 03.10.2026. Sprawdzono istniejącą implementację; nie było potrzeby zmiany
mechanizmu podpisu ani kolejki. Dodano testy odtwarzające równoczesne operacje,
których wcześniej nie sprawdzono na PostgreSQL. Wyniki nie są odbiorem całego
systemu ani integracji z operatorem.

## Sprawdzone zachowanie

| Kolejność / sytuacja | Wynik |
| --- | --- |
| Podpis zapisuje się przed SMTP, EZD lub e-Doręczeniami | Kolejka czeka na transakcję, odczytuje podpisaną wersję mimo starszego obiektu pisma i zapisuje jej dokładne bajty oraz SHA-256. |
| SMTP, EZD lub e-Doręczenia zapisują kolejkę przed podpisem | Podpis czeka, potem zostaje odrzucony jako zmiana zamkniętej wersji. Kolejka zachowuje niepodpisany oryginał. Nie dodaje się audytu udanego podpisu. |
| Dwie zweryfikowane próby podpisu | Zapisuje się dokładnie jeden podpis i jeden wpis audytu. Druga próba czeka i zostaje odrzucona; oryginał pozostaje bez zmian. |
| Transakcja podpisu wycofana przed commit | Oczekująca kolejka SMTP zapisuje oryginał. Brak częściowego podpisu i jego audytu. |
| Transakcja kolejki wycofana przed commit | Oczekujący podpis może zostać zapisany. Brak zadania i audytu wycofanej kolejki. |
| Wolne przygotowanie podpisu | Kryptografia wykonywana bez otwartej transakcji. Kolejka może zakończyć zapis; późniejszy podpis jest odrzucony po ponownym sprawdzeniu stanu. |
| Pracownik lokalnej poczty po zapisie podpisu i kolejki | Rzeczywisty plik MIME zawiera dokładnie podpisany PDF; ponowne wykonanie tego samego zadania nie zapisuje drugiej wiadomości. |

Operację podpisania wykonaj przed przekazaniem pisma do kolejki, jeżeli ma być
wysłana podpisana wersja. Pismo już przekazane do kolejki jest zamknięte do
podpisywania, także gdy wysyłka jeszcze się nie rozpoczęła. Potrzebna zmiana
wymaga nowej wersji pisma; nie anuluje wcześniejszej korespondencji.

Nie dodano w tym etapie nowej polityki obowiązkowego podpisu. Dopuszczalność
niepodpisanej korespondencji i wymagany typ podpisu/pieczęci wymagają ustaleń z
urzędem. Test kolejki pierwszej potwierdza zamknięcie i niezmienność tej wersji,
a nie jej dopuszczenie do oficjalnego obiegu.

## Jak uzyskano dowód

Testy używają odrębnych połączeń PostgreSQL w dwóch wątkach. Pierwsza transakcja
jest zatrzymana po zmianie danych, przed jej commit. Druga wykonuje rzeczywistą
funkcję aplikacji. Odczyt `pg_stat_activity` musi potwierdzić `wait_event_type=Lock`,
a `pg_blocking_pids` wskazać backend pierwszej transakcji. Różne identyfikatory
backendów są sprawdzane. Brak dowodu oczekiwania oznacza niepowodzenie testu.

Harmonogram jest kontrolowany przez zdarzenia/barierę i opakowanie audytu.
SQL, transakcje, podpis RSA/PAdES, weryfikacja podpisu i kontrola PDF działają
rzeczywiście. Nie zastąpiono blokad ani kryptografii atrapą. W teście wolnego
przygotowania opakowanie zatrzymuje prawdziwą funkcję podpisania, następnie ją
wywołuje. Używane certyfikaty są fikcyjne, niekwalifikowane; klucze są wyłącznie
w prywatnych katalogach tymczasowych, poza repozytorium i główną bazą.

Kolejność blokad: urząd → pismo; przygotowanie i weryfikacja kryptograficzna są
przed krótką transakcją zapisu. Po uzyskaniu blokady podpis ponownie sprawdza
oryginał, istniejący podpis i zadania kolejki. Kolejka czyta aktualny dokument
i przechowuje własną kopię. Podstawa semantyki:
[PostgreSQL 18 — blokady wierszy](https://www.postgresql.org/docs/18/explicit-locking.html#LOCKING-ROWS),
[Django — select_for_update](https://docs.djangoproject.com/en/5.2/ref/models/querysets/#select-for-update).

## Wyniki i odtworzenie

- Pierwszy przebieg: 10/10 testów współbieżności PASS, 4,755 s.
  `evidence/signature-concurrency-postgres-tests.txt`.
- Końcowy przebieg z kontrolą rzeczywistego załącznika poczty: 26/26 PASS,
  8,180 s — 10 testów współbieżności i 16 regresji podpisów, importu, izolacji,
  weryfikacji treści/certyfikatów i nowej wersji dokumentu.
  `evidence/signature-concurrency-postgres-final.txt`.
- Na SQLite wszystkie 10 nowych testów są jawnie pominięte. Nie traktujemy
  tego wyniku jako dowodu blokad wierszy. `evidence/signature-concurrency-sqlite-skips.txt`.
- Zbiorczy zakres i granice dowodów: `evidence/signature-concurrency-report.json`.
- Środowisko z locka: CPython 3.12.14, Django 5.2.17, pyHanko 0.35.0,
  natywny PostgreSQL 18.6 na prywatnym sockecie, bez TCP i kontenerów.
- Rzeczywisty backend plikowej poczty. Nie użyto serwera SMTP ani transportu
  HTTP operatora; profile EZD/e-Doręczeń są fikcyjne i służą wyłącznie walidacji
  utworzenia kolejki. Zadania tych dostawców nie zostały wysłane.

Po przygotowaniu prywatnego klastra według `POSTGRESQL-LOKALNIE.md`:

```sh
PGHOST="$PWD/var/postgres-native/socket" PGPORT=18765 PGUSER=dyna_pgtest PGDATABASE=drt_pg_local DYNA_DATA_DIR="$PWD/var/signature-concurrency-tests" .venv/bin/python manage.py test registry.test_signature_concurrency registry.test_signatures --noinput --verbosity 2
```

Django tworzy i usuwa własną bazę testową. Nie kieruj tego polecenia do bazy
urzędu. Klaster został po weryfikacji zatrzymany; główna aplikacja korzysta
z wcześniejszej SQLite, której dane biznesowe nie zostały zmienione.

## Granice

Sprawdzono dwa równoczesne połączenia i pismo wniosku indywidualnego, bez pomiaru
pojemności i ruchu wszystkich urzędów. Nie wykonano w tym etapie nowych testów
kopii, migracji wydania, awarii procesu/systemu ani scenariusza Chrome. Testy
HTTP importu w regresji używają klienta Django. PostgreSQL jest lokalny na
macOS, nie na docelowym serwerze urzędu.

Nie zweryfikowano wysyłki podpisanego pisma do rzeczywistego SMTP, EZD lub
e-Doręczeń, kwalifikacji podpisu/pieczęci, QSCD/HSM, znacznika czasu ani LTV.
Te wymagania i pełna realizacja celu pozostają otwarte.
