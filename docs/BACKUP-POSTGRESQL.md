# Kopia i odtworzenie PostgreSQL

Stan: 03.10.2026. Wykonano rzeczywisty pg_dump i pg_restore na PostgreSQL 18.6
uruchomionym lokalnie bez kontenerów. Nie wykonano jeszcze próby awarii na
infrastrukturze urzędu ani testu PITR/WAL.

Ponowny odbiór na `dc3d6df`: 18 testów PostgreSQL PASS, rzeczywista kopia i
odtworzenie obu silników, aktualizacja odtworzonego schematu PG 0005→0010
oraz Chrome z podpisanym archiwum i wstrzymaną kolejką. Zakres i granice:
`ODBIOR-BAZY-I-AKTUALIZACJI.md`. Nie zastępuje to pełnego odbioru systemu.

## Co obejmuje kopia

`manage.py backup_registry` rozpoznaje skonfigurowany silnik. Dla PostgreSQL
tworzy archiwum ZIP z `database.dump` w formacie custom oraz `manifest.json`.
Zapisane są wszystkie obiekty schematu public dedykowanej bazy aplikacji, dane,
sekwencje, dokumenty oryginalne i podpisane, raporty podpisów, kolejka i dowody.
Manifest zawiera SHA-256 zrzutu, liczby rekordów, listę migracji oraz wersję serwera
i narzędzia. Plik końcowy ma uprawnienia 0600.

Manifest przechowuje kodowanie oraz dostawcę, locale, reguły i wersję sortowania
bazy. Nowa baza jest tworzona z tymi ustawieniami, a ich niezgodność blokuje
odtworzenie. Nie wymusza się starej wersji biblioteki sortowania na nowym serwerze.
Dowody obejmują UTF8 / libc / C; ICU i builtin są obsługiwane w kodzie, lecz nie
były jeszcze sprawdzone w próbie operacyjnej. Podstawa: [CREATE DATABASE](https://www.postgresql.org/docs/18/sql-createdatabase.html).

Sprawdzenie sum dokumentów, numeracji i liczb rekordów oraz pg_dump używają
jednego snapshotu REPEATABLE READ. Zapis danych w aplikacji może trwać równolegle.
Weryfikacja bytea używa nazwanych kursorów z małymi partiami, zamiast pobierać
wszystkie PDF do RAM. Odtworzenie rozpakowuje zrzut strumieniowo i sprawdza dostępne
miejsce na dysku. Nie ma arbitralnego limitu 2 GB dla zrzutu PostgreSQL.

Podstawa techniczna: [pg_dump](https://www.postgresql.org/docs/18/app-pgdump.html),
[snapshoty](https://www.postgresql.org/docs/18/functions-admin.html#FUNCTIONS-SNAPSHOT-SYNCHRONIZATION),
[pg_restore](https://www.postgresql.org/docs/18/app-pgrestore.html).

Kopia **nie zawiera** plików konfiguracyjnych usług, sekretów integracji, klucza
sesji, kluczy prywatnych do podpisu ani systemowych ról, haseł i konfiguracji
PostgreSQL. Zawiera dane uwierzytelniania przechowywane w bazie, dane osobowe
ewidencji oraz dokumenty; wymaga chronionego, szyfrowanego miejsca przechowywania.
SHA-256 wykrywa zmianę bajtów, ale nie potwierdza pochodzenia kopii. Odtwarzaj kopie
z własnego zaufanego repozytorium; pg_restore wykonuje definicje SQL ze źródła.

Pliki konfiguracji, zaufane certyfikaty i sekrety przechowuj w osobnej chronionej
kopii administracyjnej. Odzyskanie klucza do podpisu zależy od sposobu jego
przechowywania, w tym HSM. Nie umieszczaj tych plików w repozytorium Git.

## Uruchomienie lokalne

Uruchom klaster opisany w `docs/POSTGRESQL-LOKALNIE.md`, a następnie w osobnej
powłoce z katalogu projektu:

```sh
export PGHOST="$PWD/var/postgres-native/socket"
export PGPORT=18765
export PGUSER=dyna_pgtest
export PGDATABASE=drt_pg_local
export DYNA_DATA_DIR="$PWD/var/postgres-app"

.venv/bin/python manage.py backup_registry \
  --output var/backups/nowa-kopia-postgres.zip

.venv/bin/python manage.py restore_registry \
  var/backups/nowa-kopia-postgres.zip \
  --target var/restores/nowe-odtworzenie \
  --target-database drt_restore_nowe
```

Nazwy docelowe muszą być nowe. `--target` jest katalogiem raportu odtworzenia,
a `--target-database` nazwą nowej bazy. Źródło pozostaje skonfigurowaną bazą.
Program nie przełącza aplikacji i nie zastępuje istniejących baz ani plików.
Główna aplikacja SQLite na porcie 8765 nie jest modyfikowana tymi poleceniami.

Narzędzia pobierane są z `--pg-bin-directory`, `DYNA_POSTGRES_BIN` lub PATH;
w trybie lokalnym istnieje także ścieżka do pakietu w var. Poza trybem lokalnym
nie ma automatycznego wyboru pakietu macOS. Używaj narzędzi zgodnych z wersją
serwera; bieżące dowody obejmują serwer i narzędzia 18.6.

Hasło i ustawienia połączenia pochodzą z konfiguracji PostgreSQL aplikacji.
Nie przekazuj haseł w argumentach poleceń ani nazwie kopii. TLS dla zdalnej bazy
konfiguruj zgodnie z polityką urzędu, z weryfikacją certyfikatu serwera.

## Kontrole odtworzenia

Przed utworzeniem bazy sprawdzane są format archiwum, manifest, miejsce na dysku,
SHA-256, narzędzie i zakaz wskazania źródłowej lub systemowej bazy.
Istniejąca baza docelowa jest odrzucana; nie jest usuwana ani czyszczona.

Tworzona jest nowa baza z template0. Jej pusty schemat public jest usuwany bez
CASCADE, aby pg_restore mógł odtworzyć go ze zrzutu. Import jest wykonywany
z `--single-transaction --exit-on-error --no-owner --no-acl`, bez `--clean` i `--create`.
Właścicielem odtworzonych obiektów jest konto wykonujące odtworzenie.

Następnie sprawdzane są liczby rekordów, migracje, sumy oryginalnych i podpisanych
PDF, kolejki i dowodów oraz numery i watermarki liczników. Sesje są usuwane z
**odtworzonej** bazy, kody logowania unieważniane, a aktywne zadania przechodzą
w REVIEW_REQUIRED i tracą claim. Powiązania EZD będące w CREATING również wymagają
sprawdzenia. Identyfikatory zewnętrzne, etapy, zamrożony załącznik i zakończone
wyniki nie są zastępowane fikcyjnym sukcesem ani ponownie wysyłane.

Raport `restore-manifest.json` jest zapisywany z uprawnieniami 0600 dopiero po
przejściu kontroli. Błąd po utworzeniu bazy blokuje nowe połączenia do tej bazy
przez ALLOW_CONNECTIONS=false i pozostawia ją do kontroli. Program nie usuwa
jej automatycznie. Jeśli nie uda się również zablokować połączeń, komunikat
wprost wymaga izolacji przez administratora. Nie uruchamiaj aplikacji na bazie,
której odtworzenie nie zakończyło się poprawnym raportem.

## Procedura dla infrastruktury urzędu

1. Administrator przygotowuje dedykowaną bazę aplikacji ze schematem public,
   narzędzia pg_dump/pg_restore i chroniony katalog kopii. Konto kopii musi
   odczytywać wszystkie tabele i sekwencje aplikacji. Nie potrzebuje SUPERUSER.
   Odtworzenie wykonuje odrębne konto administracyjne z prawem tworzenia baz;
   konto zwykłej aplikacji nie powinno mieć CREATEDB.
2. Kopię uruchamia harmonogram urzędu. Nie wykonuj w tym samym czasie migracji
   schematu. Monitoruj kod zakończenia i obecność poprawnego manifestu.
   Kopie przechowuj także poza serwerem aplikacji i regularnie sprawdzaj ich
   odtworzenie. Retencję i wymagania RPO/RTO uzgodnij z właścicielem systemu.
3. Przy awarii odtwórz kopię do nowej bazy na izolowanym środowisku. Konta,
   konfiguracja systemowa, certyfikaty i sekrety wymagają oddzielnego odtworzenia.
   Nie włączaj wysyłki z kopii próbnej. Skontroluj raport, dane, dokumenty i UI.
4. Przed właściwym przełączeniem zatrzymaj zapisy i workery starej instancji.
   Uzgodnij operacje wykonane po dacie kopii, numery już użyte w pismach oraz
   wyniki u operatorów. Dwie niezależne kopie mogą wygenerować te same kolejne
   numery; nie wolno eksploatować ich równolegle jako tej samej instancji.
5. Administrator nadaje uzgodnione uprawnienia kontu aplikacji do nowej bazy,
   przełącza konfigurację i wykonuje testy wszystkich ról. Stare sesje nie są
   przywracane. Workery można uruchomić po uzgodnieniu odtworzonych zadań;
   REVIEW_REQUIRED nie stanowi zgody na ponowną wysyłkę.

Jest to procedura do odbioru przez urząd. Konto tylko do odczytu, docelowy system
operacyjny, harmonogram, szyfrowane repozytorium, RPO/RTO i proces przełączenia
nie zostały jeszcze sprawdzone na infrastrukturze urzędu. Logiczny pg_dump nie
zastępuje skonfigurowanego i przetestowanego backupu fizycznego/WAL, jeśli urząd
wymaga odtwarzania do konkretnego punktu czasu.

## Wykonane próby i dowody

- 6/6 testów rzeczywistych narzędzi PostgreSQL PASS, 2,006 s:
  pełny import podpisanego PDF i sztucznego dowodu, ochrona sesji/kolejki,
  zachowanie numeracji, odrzucenie uszkodzonego archiwum i istniejącego celu,
  kwarantanna przy niezgodnym manifeście, blokada kopii z uszkodzonym PDF lub
  cofniętym licznikiem, brak narzędzia i zachowanie istniejącego pliku.
- W teście zapisu równoległego utworzono i zapisano nowy wniosek w źródłowej bazie
  po pobraniu snapshotu; manifest i zrzut zgodnie go nie zawierały.
- 5/5 testów regresji kopii SQLite PASS, 0,388 s.
- Końcowa kopia `var/backups/2026-10-03-postgres-final.zip`, odtworzona do
  `drt_restore_20261003_final`. SHA-256 zrzutu:
  `7b8350c99e1d64851eba555330e115302c8b978c2c4e3936804d8304d596223d`.
  Wcześniejsza próba i jej kopia zostały zachowane oddzielnie; nie zawierały jeszcze
  metadanych locale wymaganych przez końcową implementację.
- Odtworzono 4 wnioski, 8 pism i podpisane pismo `DRT/ump/2026/000004`.
  Ponownie zweryfikowano kryptograficznie podpis DEMO; pozostaje niekwalifikowany.
- Nowy wniosek wyłącznie w kopii otrzymał `W/2026/00005`, pismo
  `DRT/gni/2026/000005`. Źródło zachowało 4 wnioski i niezmienione liczby rekordów.
- Uruchomienie workera w kopii nie zmieniło wstrzymanego zadania; prób 0.
- Chrome: nowe logowanie OTP, dostęp do archiwum podpisanego pisma oraz widoczna
  wstrzymana kolejka. Nie wysłano korespondencji do żadnego operatora.

Dowody: `evidence/postgres-backup-tests.txt`, `evidence/sqlite-backup-regression.txt`,
`evidence/postgres-backup-final-manifest.json`, `evidence/postgres-restore-final-proof.json`,
`evidence/postgres-final-source-preserved.json`,
`evidence/13-postgres-odtworzenie-koncowe.jpg`. Pierwsza próba ma osobne pliki
`postgres-backup-manifest.json`, `postgres-restore-proof.json`,
`postgres-restored-worker-held.json`, `postgres-source-preserved.json` oraz zrzut 12.

Próba nie dowodzi kwalifikacji podpisu, autentyczności sztucznego dowodu doręczenia,
zgodności wszystkich procesów ani działania rzeczywistych API. Nie przetestowano
dużego archiwum ani awarii zasilania. Budowa pełnego systemu pozostaje w toku.
