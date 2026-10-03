# Instalacja na infrastrukturze urzędu

Stan: 03.10.2026. Jest profil konfiguracji, Gunicorn, inicjalizacja pustej bazy,
wzory Nginx i usług systemd. Sprawdzono proces Gunicorn z PostgreSQL na macOS.
Nie wykonano instalacji na Linuxie ani próby Nginx z rzeczywistym certyfikatem.
To instrukcja przygotowania i odbioru, a nie potwierdzenie gotowości produktu.

## Układ jednej instalacji

Dedykowany serwer Linux z systemd, CPython 3.12, PostgreSQL i Nginx. Nginx
obsługuje HTTPS i statyczne zasoby; Gunicorn słucha wyłącznie 127.0.0.1:8000.
Na początek dwa procesy Gunicorn. Liczbę procesów, RAM, dysk i czasy zadań trzeba
dobrać w pomiarze z danymi i ruchem urzędu; lokalny test nie potwierdza pojemności.
Rdzeń nie wymaga SaaS. Sieć urzędu musi zapewnić dostęp do SMTP, wybranych API,
DNS, czasu i usług weryfikacji podpisów zgodnie z ich konfiguracją.

| Ścieżka / konto | Przeznaczenie |
| --- | --- |
| `/opt/dyna/releases/<SHA>` | Niezmienny kod wydania i jego własna `.venv`; właściciel root |
| `/opt/dyna/current` | Symlink do zatwierdzonego wydania |
| `/var/lib/dyna` | Prywatne dane pomocnicze aplikacji, właściciel dyna, 0700 |
| `/var/lib/dyna-deploy` | Prywatny katalog czynności instalacyjnych, właściciel dyna-deploy, 0700 |
| `/var/backups/dyna` | Chronione kopie, właściciel dyna, 0700; szyfrowany wolumen |
| `/etc/dyna/runtime.env` | Konfiguracja wykonawcza, root:dyna, 0640 |
| `/etc/dyna/migration.env` | Konfiguracja instalacyjna, root:dyna-deploy, 0640 |
| `/etc/dyna/tls` | Certyfikat i klucz Nginx; klucz czytelny tylko dla właściwego procesu |
| `dyna` | Konto systemowe aplikacji bez powłoki; brak zapisu do kodu |
| `dyna-deploy` | Konto instalacyjne bez powłoki; zapis tylko do własnych danych i staticfiles |
| `dyna_owner` | Osobne konto PostgreSQL do migracji, właściciel bazy |
| `dyna_runtime` | Konto PostgreSQL aplikacji, DML i sekwencje, bez DDL i członkostwa w rolach |

Nie instaluj tych usług na laptopie do testów lokalnych. Używaj istniejącego
`scripts/run-local.sh` i osobnego klastra opisanego w `POSTGRESQL-LOKALNIE.md`.

## Przygotowanie wydania i bazy

Administrator infrastruktury zakłada konta systemowe, katalogi i dedykowaną bazę.
Wzór `deploy/postgresql.sql.example` rozdziela właściciela i konto wykonawcze oraz
ustawia prawa przyszłych tabel i sekwencji. Dotyczy **nowej dedykowanej bazy**;
nie wykonuj go w istniejącym współdzielonym schemacie. Hasła ustaw osobno przez
interaktywne `psql \password`. Włącz odpowiednie reguły pg_hba, ogranicz sieć i
sprawdź brak uprawnień administracyjnych oraz możliwości SET ROLE do właściciela.

Kod dostarcz jako zweryfikowane wydanie o pełnym SHA, zachowując źródłowe dokumenty.
W jego katalogu utwórz `.venv` i zainstaluj `requirements.txt` z wymuszeniem
`--require-hashes --only-binary=:all:`. Lock zawiera dokładne wersje, zależności
przechodnie i SHA-256. Nie instaluj wydania z `requirements.in`. Procedura,
pakiet offline i granice kontroli: `ZALEZNOSCI.md`; spis i dostarczone teksty
licencji: `../THIRD-PARTY-NOTICES.md`. Dostępność paczek Linux x86-64/ARM64
sprawdzono przez pobranie, a nie przez wykonanie na tych platformach. Odbiór
Linuxa oraz ocena pełnego pakietu redystrybucyjnego pozostają wymagane.

Utwórz `staticfiles` z właścicielem dyna-deploy i prawami 0755. Pozostały kod i
środowisko są czytelne dla aplikacji, ale nie mogą być przez nią modyfikowane.
Nowe wydanie przygotuj przed zmianą symlinka. Wszystkie dane i sekrety pozostają
poza katalogiem wydania.

## Konfiguracja

Z `deploy/onprem.env.example` przygotuj dwa prywatne pliki konfiguracji. Uzupełnij
rzeczywistą domenę, losowy klucz sesji, pełny SHA, bazę i SMTP. Nie używaj `.env`
w repozytorium ani sekretów w argumentach poleceń. systemd czyta EnvironmentFile;
nie wykonujemy zawartości tego pliku jako skryptu powłoki.

W `runtime.env`: PGUSER=dyna_runtime i DYNA_DATA_DIR=/var/lib/dyna.
W `migration.env`: PGUSER=dyna_owner, odpowiednie hasło,
DYNA_DATA_DIR=/var/lib/dyna-deploy oraz DYNA_INITIAL_ADMIN_EMAIL z adresem osoby
odpowiedzialnej za instalację. Oba pliki wskazują ten sam APP_URL i wydanie.

Wymagane `DJANGO_SETTINGS_MODULE=config.settings_onprem` i `DYNA_ENV=onprem`.
Profil blokuje DEBUG, słaby klucz, SQLite, wildcardy hosta, brak SHA, dane w
katalogu kodu i SMTP bez szyfrowania. Dla zdalnej bazy wymaga `verify-full` i CA;
lokalny socket lub loopback podlegają ochronie systemu i pg_hba. Certyfikat CA
musi być dostępny dla obu kont, a jego zgodność trzeba sprawdzić w próbie TLS.

SMTP: STARTTLS (`EMAIL_USE_TLS=1`, `EMAIL_USE_SSL=0`) lub TLS od początku
(`EMAIL_USE_TLS=0`, `EMAIL_USE_SSL=1`, zwykle port 465). Podaj port i tożsamość
zgodne z serwerem urzędu. Najpierw sprawdź OTP na zatwierdzonym koncie testowym.
Nie wystarczy kontrola ustawień — dostarczenie maila wymaga osobnej próby.

Profile EZD/e-Doręczeń/podpisów mają ścieżki poza Git i uprawnienia zgodne z
konektorami. Instrukcje są w osobnych dokumentach. Brak profilu nie oznacza
działającej integracji. Uruchomienie kolejki z poprawnym profilem może wykonywać
rzeczywiste operacje wcześniej zlecone przez urzędników.

## Pierwsze uruchomienie

Po przygotowaniu katalogów, konfiguracji i symlinka administrator instaluje
pliki `.service` i `.timer` z `deploy/` do `/etc/systemd/system`, następnie:

```sh
systemctl daemon-reload
systemctl start dyna-maintenance@migrate.service
systemctl start dyna-maintenance@initialize.service
systemctl start dyna-maintenance@collectstatic.service
```

Sprawdź exit status i dziennik każdego kroku przed następnym. Nie włączaj usług,
gdy migracja lub zbieranie zasobów zakończyły się błędem. Inicjalizacja jest tylko
dla pustej instalacji. Tworzy 35 nieaktywnych urzędów, administratora OTP bez
hasła i wzory do zatwierdzenia. Nie tworzy spraw, pojazdów, numerów ani fikcyjnych
adresów urzędów; jest audytowana i nie wysyła wiadomości. Nie używaj `seed_local`.

Uzupełnij wzór `deploy/nginx.conf.example` właściwą domeną i certyfikatami.
W zależności od dystrybucji umieść go w konfiguracji włączanej w kontekście `http`.
Zweryfikuj `nginx -t` i `systemd-analyze verify` dla przygotowanych jednostek.
Przeładuj Nginx, dopiero po pomyślnym sprawdzeniu. Nie otwieraj portu 8000 na
interfejsach publicznych; na 80/443 dopuść ruch zgodnie z polityką urzędu.

```sh
systemctl enable --now dyna-web.service
```

ExecStartPre uruchamia `check_onprem --database`. Kontrola jest tylko do odczytu:
odrzuca administracyjne prawa PostgreSQL, CREATE w schemacie, własność obiektów,
członkostwo w innych rolach i brakujące migracje. Nie wykonuje migracji kontem
aplikacji. To nie jest test działania SMTP, certyfikatu lub operatora.

Nginx nadpisuje X-Dyna-Client-IP i X-Forwarded-Proto. Pierwszy middleware przyjmuje
je tylko od 127.0.0.1, wymaga pojedynczego poprawnego IP i protokołu, usuwa obce
Forwarded/X-Forwarded-For/X-Forwarded-Host. Jest to jedna określona topologia,
bez domniemanego zaufania do kolejnego proxy. Przed dodaniem load balancera lub
CDN należy zmienić i zweryfikować cały łańcuch zaufania. Podstawa:
[Django SECURE_PROXY_SSL_HEADER](https://docs.djangoproject.com/en/5.2/ref/settings/#secure-proxy-ssl-header),
[Nginx proxy_set_header](https://nginx.org/en/docs/http/ngx_http_proxy_module.html#proxy_set_header).

Kontrola deployment Django pozostawia widoczne W005 i W021: HSTS dla subdomen
oraz preload. Celowo nie obejmujemy nieznanych subdomen ani nie deklarujemy
rejestracji w globalnej liście przeglądarek. HSTS dla samej domeny ma rok.
Decyzję o rozszerzeniu podejmuje właściciel domeny po sprawdzeniu HTTPS; nie jest
to dowód braku innych problemów bezpieczeństwa. Ostrzeżenia nie są wyciszone.

Administrator loguje się przez OTP, uzupełnia dane i domeny urzędów, ADE i konta
biznesowe, zatwierdza szablony oraz aktywuje przygotowane urzędy. TERYT i adresy
kontaktowe wymagają potwierdzenia, a nie zgadywania w instalatorze.

## Zadania i monitorowanie

Po kontroli konfiguracji, kolejki i odbiorze wymaganych integracji:

```sh
systemctl enable --now dyna-jobs.timer dyna-security.timer dyna-backup.timer
```

Kolejka i wygasanie rezerwacji: minuta po zakończeniu poprzedniej próby. Zadanie
nie uruchamia równocześnie drugiego wystąpienia tej samej jednostki. Stan
przerwanej operacji przechodzi do uzgodnienia, zamiast automatycznej ponownej
wysyłki. Limit 100 zleceń/przebieg i 30 minut wymaga pomiaru czasu z operatorem.
RPW nie jest automatycznie odczytywane: harmonogram per profil i zakres dat
przygotowuje administrator zgodnie z `WPLYWY-EZD.md`, po potwierdzeniu dostępu.

`expire_reservations` bez argumentów zachowuje jednorazowy przebieg używany
przez timer. Profil lokalny uruchamia osobny `--watch --interval 30`, który
wygasza również bez ruchu WWW. Dwa procesy chronią transakcje i blokady;
statusy wpisu/wniosku oraz oba zdarzenia audytu powstają atomowo.
Odbiór PostgreSQL i procesu natywnego opisuje `REZERWACJE-I-ODMOWA.md`;
systemd i harmonogram na serwerze urzędu nadal wymagają rzeczywistego odbioru.

Ochrona publiczna: dzienne usuwanie wygasłych liczników/CAPTCHA. Opcjonalny
`purge_security_state --include-auth` dodaje OTP i sesje wygasłe ponad dobę
wcześniej; wymaga jawnego włączenia, a timer zachowuje dotychczasowy zakres.
`retention_inventory` przygotowuje zbiorczy, odczytowy raport 19 klas danych.
Polityka spraw, audytu, dokumentów, korespondencji i plików pozostaje decyzją
urzędu. Warunki, podgląd, zapis i formularz polityki: `RETENCJA-DANYCH.md`.

Kopia: dziennie 02:15 Europe/Warsaw, nowa nazwa przy każdej próbie. Wzór nie usuwa
starszych kopii i nie przesyła ich poza serwer. Urząd musi zapewnić szyfrowanie,
osobną kopię poza hostem, kontrolę dostępnego miejsca i zatwierdzoną retencję.
Procedura spójności i odtworzenia: `BACKUP-POSTGRESQL.md`. Klucze i konfiguracja
mają osobny chroniony backup; nie trafiają do archiwum aplikacji.

Monitoruj HTTPS `/api/health/`: 200 + właściwy `revision`, a przy awarii bazy
503 bez danych połączenia. Health sprawdza połączenie z bazą; nie dowodzi
zgodności schematu, pełnych procesów biznesowych ani działania integracji.
Sprawdzaj również stan usług/timerów, exit status kopii, wiek ostatniej poprawnej
kopii, wolne miejsce, błędy kolejki i zbliżające się wygaśnięcie certyfikatów.
Alerty skonfiguruj do zatwierdzonego kanału urzędu. Nie uruchomiono takiego kanału.
Logi HTTP ograniczają dane: bez query string, kodów OTP i treści formularzy;
dziennik audytowy nadal zawiera chronione dane operacyjne.

## Aktualizacja i odtworzenie

Przygotuj nowe wydanie i środowisko obok dotychczasowego. Sprawdź wpływ migracji,
wykonaj oraz zweryfikuj backup. Zatrzymaj timery i aktywne zadania, zaczekaj na
ich zakończenie, a następnie zatrzymaj aplikację. Nie zmieniaj symlinka podczas
pracy kolejki: stare i nowe procesy nie mogą równocześnie przetwarzać operacji.

Przełącz `current`, zmień pełny APP_REVISION w obu konfiguracjach, wykonaj migracje
kontem właściciela i collectstatic, sprawdź wyniki. Uruchom aplikację, sprawdź
preflight, health ze zgodnym SHA, OTP i kluczowe przepływy. Dopiero potem przywróć
timery. Zmiany destrukcyjne wymagają osobnej zgody i planu migracji.

Cofnięcie kodu jest możliwe tylko przy potwierdzonej zgodności starego kodu z
aktualnym schematem. Nie wykonuj automatycznego cofania migracji. Jeśli potrzebne
jest odtworzenie, użyj osobnej nowej bazy i procedury kontroli dokumentów/liczb,
unieważnienia sesji oraz wstrzymania kolejki. Przełączenie do odtworzonej bazy
następuje po sprawdzeniu i świadomej decyzji administratora; późniejsze zapisy
mogą wymagać uzgodnienia. Nie obiecujemy bezstratnego rollbacku po nowych zapisach.

## Wykonane próby i wymagany odbiór

- 24/24 testy PostgreSQL PASS (0,215 s); SQLite 23 PASS / 1 SKIP PG (0,144 s).
  Profil, proxy, izolacja liczników ochrony, inicjalizacja i health.
- Rzeczywisty Gunicorn 23.0.0 + PostgreSQL 18.6 na prywatnym lokalnym sockecie:
  migracja, czysta instalacja 35 urzędów / 1 konto / 0 spraw i pism,
  konto wykonawcze odrzucone przy CREATE TABLE, health 200 z testowym SHA,
  HTTP→HTTPS, obcy host i brak nagłówków 400, dwa osobne liczniki IP w bazie.
- Konto właściciela odrzucone przez kontrolę roli wykonawczej; rzeczywisty
  pg_dump i spójny backup wykonane kontem wykonawczym. Archiwum jest prywatne.
- Nagłówki proxy dostarczał klient HTTP testu. To **nie** jest test Nginx, TLS,
  certyfikatu, systemd, SMTP, operatora ani rzeczywistego wdrożenia urzędowego.
- Zbieranie statycznych zasobów i sprawdzenie konfiguracji Gunicorn zakończone
  poprawnie. macOS nie ma tutaj Nginx/systemd; pliki usług nie były uruchomione.

Dowody: `evidence/onprem-native-tests.txt`, `onprem-postgres-tests.txt`,
`onprem-postgres-preflight.txt`, `onprem-gunicorn-postgres-smoke.json`.
Odbiór Linuxa musi obejmować konfigurację jednostek, prawa plików, poprawny
certyfikat, realny adres klienta i spoofing nagłówków, OTP, zadania po restarcie,
awarię/odtworzenie, monitoring, aktualizację i zgodny SHA. Pozostałe wymagania
całego celu, w tym rzeczywiste integracje i kwalifikacja podpisów, są otwarte.


## Zaproszenia i domeny urzędów

Po inicjalizacji A0 musi skonfigurować pełne domeny e-mail poszczególnych
urzędów. Pusta lista blokuje logowanie urzędników w profilu urzędowym.
Migracja 0010 dodaje trwałe zaproszenia do kont; `dyna-jobs.service`
przetwarza również `process_account_invitations`. Po aktualizacji pliku
jednostki administrator serwera wykonuje standardowe przeładowanie systemd.
Niepewna wysyłka i odtworzona kolejka nie są ponawiane automatycznie.
Przed wznowieniem należy sprawdzić wynik w serwerze SMTP. Szczegóły i stan
weryfikacji: `KONTA-I-ZAPROSZENIA.md`. Nie wykonano tego wdrożenia na Linuxie.
