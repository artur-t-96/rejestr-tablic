# PostgreSQL bez kontenerów — uruchomienie i weryfikacja

Stan: 03.10.2026. Zweryfikowano macOS arm64, PostgreSQL 18.6, Django 5.2.17.
Jest to lokalny etap wdrożenia; nie stanowi odbioru infrastruktury urzędu.

## Narzędzia i oddzielna baza

Pakiet Postgres.app jest wskazany na [stronie projektu PostgreSQL](https://www.postgresql.org/download/macosx/).
Pobrano wydanie [Postgres.app 2.9.6 z PostgreSQL 18.6](https://postgresapp.com/downloads.html),
sprawdzono SHA-256 z metadanymi wydania oraz podpis pakietu poleceniem
`codesign --verify --deep --strict`. Używane są wyłącznie narzędzia CLI z prywatnego
katalogu projektu. Nie uruchomiono aplikacji graficznej, kontenerów, globalnej
usługi ani mechanizmu automatycznego startu.

Manifest pobrania jest lokalnie w `var/runtimes/postgresapp/download-manifest.json`.
SHA-256 archiwum: `9fc7d0dc08cf46dfd94bb32cbaaad81b41b37847a42d6dcb2f9fbd292813defb`.
Pakiet i pliki bazy są ignorowane przez Git. Na innym komputerze pobierz narzędzia
z oficjalnego źródła i wskaż ich katalog przez `--bin-dir` lub `DYNA_POSTGRES_BIN`.

```sh
# Tylko przy pierwszym uruchomieniu; istniejący katalog nie zostanie nadpisany:
.venv/bin/python scripts/local-postgres.py init

# W kolejnych sesjach:
.venv/bin/python scripts/local-postgres.py start
.venv/bin/python scripts/local-postgres.py status
```

Skrypt tworzy osobny klaster w `var/postgres-native`, prywatny socket Unix,
bazę `drt_pg_local` i rolę `dyna_pgtest`. Nie zmienia głównej bazy SQLite.
Katalogi mają tryb 0700, znacznik klastra 0600, socket 0700. Uwierzytelnianie peer
mapuje bieżącego użytkownika systemowego do roli testowej. PostgreSQL nie nasłuchuje
na TCP (`listen_addresses=''`); numer 18765 identyfikuje prywatny socket.

Rola nie ma SUPERUSER, CREATEROLE, REPLICATION ani BYPASSRLS. Ma CREATEDB wyłącznie
do tworzenia i usuwania przez Django jego własnej bazy testowej. **Nie używaj tej
roli ani konfiguracji klastra jako konfiguracji produkcyjnej.** Produkcja wymaga
osobnych uprawnień administratora/migracji i aplikacji oraz uzgodnionej polityki
kopii, WAL, dostępu i monitorowania.

Konfiguracja lokalna ogranicza zasoby: 20 połączeń, shared_buffers 16 MB,
work_mem 1 MB, brak równoległych workerów zapytań. Fsync, synchronous_commit i sumy
kontrolne danych są włączone. To profil do weryfikacji funkcji, nie test obciążenia.

## Osobna lokalna instancja aplikacji

Uruchom z katalogu projektu, w osobnej powłoce. Zmienne dotyczą tylko tej powłoki:

```sh
export PGHOST="$PWD/var/postgres-native/socket"
export PGPORT=18765
export PGUSER=dyna_pgtest
export PGDATABASE=drt_pg_local
export DYNA_DATA_DIR="$PWD/var/postgres-app"
export APP_URL=http://127.0.0.1:8767

.venv/bin/python manage.py migrate --noinput
.venv/bin/python manage.py seed_local
.venv/bin/python manage.py runserver 127.0.0.1:8767 --noreload --insecure
```

Adres podczas działania: `http://127.0.0.1:8767/`. Konta fikcyjne takie jak w README.
Kod OTP odczytuj z tej samej powłoki przez `manage.py local_mail`, aby użyć katalogu
`var/postgres-app/mail`. Ustawienia uruchomienia nie obejmują rzeczywistych usług
EZD, e-Doręczeń ani podpisu urzędu.

Nie uruchamiaj workerów na skopiowanej bazie przed sprawdzeniem kolejki. Lokalne
instancje na różnych portach tego samego hosta współdzielą nazwę ciasteczka sesji;
przełączając się pomiędzy nimi, zaloguj się ponownie do właściwej instancji.

## Wykonane testy

W powłoce z ustawionymi zmiennymi PostgreSQL:

```sh
.venv/bin/python manage.py test \
  registry.tests \
  registry.test_numbering.NumberingTests \
  registry.test_numbering.NumberingConcurrencyTests.test_simultaneous_first_request_numbers_are_unique \
  registry.test_numbering.NumberingConcurrencyTests.test_simultaneous_letter_revisions_preserve_original_and_get_unique_numbers \
  registry.test_signatures registry.test_ezdrp registry.test_edor \
  registry.test_database_concurrency --noinput --verbosity=2
```

**93/93 PASS**, 8,675 s. Zakres obejmuje role, rdzeń trzech modułów, numerację,
rzeczywiste testowe podpisy PAdES oraz kontrakty konektorów. Zewnętrzne API są
symulowane w testach konektorów. Testy backupu SQLite i migracji historycznej SQLite
nie są częścią tego uruchomienia.

Po zmianach wykonano również lokalny zestaw SQLite: **98 testów, 96 PASS,
2 pominięte**. Pominięte testy wymagają rzeczywistych blokad PostgreSQL.
Ruff i kontrola braku niezapisanych migracji PASS.

W szczególności sprawdzono:

- dwie równoczesne rezerwacje tego samego wyróżnika: jedna skuteczna;
- nakładające się pule: jeden przydział skuteczny;
- cztery równoczesne pierwsze numery wniosków i równoczesne wersje pisma;
- konkurujące zatwierdzenie i wycofanie: zgodne statusy wniosku i tablicy;
- równoczesne wydanie tego samego numeru puli: jedno wydanie i jeden wpis audytu;
- dwa procesy kolejki: jedno wywołanie transportu;
- wygaszanie z drugim procesem oczekującym na blokadę, potwierdzone przez
  `pg_stat_activity`: brak deadlocku i brak skutecznego wycofania wygasłego wniosku;
- blokada archiwalnego dokumentu nie blokuje utworzenia niezależnego nowego
  dokumentu przez klucze obce urzędu;
- przeterminowanej rezerwacji nie można przedłużyć, złożyć ani zatwierdzić;
- OTP urzędnika i administratora bez przypisanego urzędu.

Pierwszy przebieg wykrył niedozwoloną blokadę nullable outer join przy OTP.
Poprawka ogranicza blokadę do rekordu kodu. Wymuszony test wygaszania uruchomiony
z samą wcześniejszą funkcją `withdraw_request` z commita `a5a33e7` zakończył się
`deadlock detected`; ten sam test na aktualnej implementacji przechodzi.
Wcześniejszą funkcję załadowano tylko do pamięci procesu testowego, bez cofania
pliku, gałęzi ani rzeczywistej bazy aplikacji.

Blokady mają spójną kolejność tablica → wniosek. Wygaszanie porządkuje tablice
po PK. Operacje dokumentów stosują na urzędzie `FOR NO KEY UPDATE`, aby zachować
serializację bez blokowania odwołań FK. Claim kolejki blokuje samo zadanie,
bez niepotrzebnego blokowania dokumentu i urzędu odbiorcy.
Podstawa: [Django select_for_update](https://docs.djangoproject.com/en/5.2/ref/models/querysets/#select-for-update)
i [PostgreSQL — blokady](https://www.postgresql.org/docs/18/explicit-locking.html).

## Chrome i trwały zapis

Na osobnej instancji PostgreSQL wykonano rzeczywiste logowanie OTP powiatu i UMP,
utworzenie wniosku `TEST/PG/001` o fikcyjną tablicę `P4 BAZA`, złożenie i akceptację.
Wniosek `W/2026/00004`, pisma `DRT/gni/2026/000004` i `DRT/ump/2026/000004`.
Baza potwierdza APPROVED / ALLOCATED i prawidłowe SHA-256 obu PDF.
Nie wysyłano korespondencji do zewnętrznego operatora.

Dowody:

- `evidence/postgres-tests.txt` — 93 testy i ich nazwy;
- `evidence/sqlite-after-postgres-fixes.txt` — regresja SQLite;
- `evidence/postgres-deadlock-before.txt` — negatywny przebieg starej funkcji;
- `evidence/postgres-runtime.json` — rzeczywiste parametry i uprawnienia;
- `evidence/postgres-lifecycle.json` — ponowny start, odczyt stanu i zatrzymanie
  własnego klastra, bez ostrzeżeń o pliku haseł;
- `evidence/postgres-ui-proof.json` — stan wniosku i sumy dokumentów z bazy;
- `evidence/10-postgres-wniosek.jpg`, `evidence/11-postgres-decyzja.jpg` — obejrzane
  zrzuty po skutecznych operacjach w Chrome.

## Zatrzymanie i pozostały zakres

Najpierw zakończ wyłącznie uruchomioną w swojej powłoce aplikację na porcie 8767
przez Ctrl+C. Następnie:

```sh
.venv/bin/python scripts/local-postgres.py stop
.venv/bin/python scripts/local-postgres.py status
```

Dane pozostają na dysku. Skrypt sprawdza znacznik własnego klastra i nie nadpisuje
istniejącego katalogu. Nie zatrzymuje głównej aplikacji na porcie 8765.

Po weryfikacji zatrzymano testowy serwer na porcie 8767 i klaster PostgreSQL.
Główna aplikacja SQLite na porcie 8765 działa z poprawionym kodem. Nie wykonano
migracji danych pomiędzy tymi bazami.

Kopia/odtworzenie PostgreSQL zostały sprawdzone w kolejnym etapie:
`docs/BACKUP-POSTGRESQL.md`. Otwarty zakres: test instalacji na docelowym Linuxie,
profil produkcyjnych uprawnień, proces aktualizacji i monitoring oraz odbiór
infrastruktury urzędu. Polecenia backup_registry/restore_registry obsługują obecnie
SQLite i PostgreSQL. Lokalny PASS nie potwierdza zewnętrznych API, kwalifikowanego podpisu ani
kompletności całej specyfikacji.
