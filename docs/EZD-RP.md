# EZD RP — konfiguracja i weryfikacja konektora

Stan 03.10.2026: zaimplementowane uwierzytelnianie i zapis PDF w sprawie według publicznego API v2. Testy kontraktowe używają `httpx.MockTransport`. Nie wykonano operacji w piaskownicy ani na instancji urzędu: nie ma przydzielonych kluczy ani potwierdzenia używanego systemu EZD. Samo ustawienie konfiguracji nie potwierdza połączenia.

## Kontrakt i źródła

Pobrano publiczne kontrakty z demo NASK: [API v2](https://integrator-api.demo.ezdrp.gov.pl/swagger/v2/swagger.json) i [API v1](https://integrator-api.demo.ezdrp.gov.pl/swagger.json). Kopie są w `docs/api`, a daty i SHA-256 w `docs/api/manifest.json`. Implementacja korzysta z v2. Dokumentacja scenariuszy v1 jest materiałem uzupełniającym, a nie źródłem nazw parametrów v2.

Uwierzytelnianie stosuje opisany przez NASK grant `api_credentials`: `client_id` z SHA-256 i Base64 hosta aplikacji, `pid`, `aki`, czas `rt` oraz `akh` ze skrótu czasu połączonego z kluczem. API otrzymuje Bearer i SID stanowiska technicznego. [Instrukcja uwierzytelniania](https://podrecznik.ezdrp.gov.pl/wykorzystania-klucza-api-w-komunikacji-z-ezd-rp/).

Klucz wydaje administrator EZD z uprawnieniem `Administracja.KluczeApi` w instytucji; klucz jest przypisany użytkownikowi technicznemu. [Zarządzanie kluczami](https://podrecznik.ezdrp.gov.pl/uwierzytelnianie-systemow-zewnetrznych/).

## Zakres obecnej implementacji

1. Osobny profil i powiązanie sprawy dla każdego urzędu. Użytkownik urzędu nadawcy wybiera istniejącą sprawę lub uzgodniony numer nowej sprawy. Uzasadnienie jest audytowane.
2. Weryfikacja istniejącej sprawy przez `GET /ezdrp/integrator/v2/sprawy/{idSprawa}`, w tym zgodności podmiotu.
3. Utworzenie sprawy przez `POST /ezdrp/integrator/v2/sprawy`, jeśli podano numer oraz konfigurację JRWA i kategorii archiwalnej. Numeru nie zgadujemy i nie wykorzystujemy lokalnego ID wniosku jako numeru kancelaryjnego.
4. Zapis PDF przez `POST /ezdrp/integrator/v2/sprawy/{idSprawa}/dokumenty`, pole multipart `files`. Kolejka przechowuje niezmienną kopię PDF i SHA-256 z chwili zlecenia.
5. Ustawienie skonfigurowanych atrybutów przez `PUT /ezdrp/integrator/v2/dokumenty/{idDokumentPrzestrzeni}/metadane`. Klucze atrybutów muszą istnieć w instancji EZD. Nie ma domniemanych „standardowych” kluczy Dyna.
6. Pobranie linku PDF, odczyt bajtów i porównanie SHA-256. Pobranie odbywa się wyłącznie z dopuszczonego repozytorium, bez przekazywania Bearer do repozytorium, bez automatycznych przekierowań.
7. Zapis identyfikatorów sprawy i dokumentu, etapów operacji oraz audytu. Status `REGISTERED` oznacza zapis w EZD, a nie wysyłkę ani doręczenie.

## Konfiguracja urzędu

Przykład bez sekretów: `docs/api/ezdrp-config.example.json`. Skopiuj go poza repozytorium, uzupełnij rzeczywiste identyfikatory i ustaw `EZDRP_CONFIG_FILE` na ścieżkę bezwzględną. Klucz API znajduje się w osobnym pliku wskazanym przez `api_key_file`. Pliki muszą mieć uprawnienia 0600 albo 0640 dla zatwierdzonej grupy usługi; bez dostępu dla pozostałych użytkowników. Nie commituj konfiguracji, klucza ani tokenów.

`web_host` jest hostem aplikacji EZD, bez schematu i ścieżki. `api_url` jest korzeniem Integratora. `token_url` wskazuje endpoint `/connect/token` otrzymanego serwera SSO. Wszystkie adresy muszą używać HTTPS. Publiczne demo służy do odczytu dokumentacji i nie jest dopuszczone jako cel zapisu.

`download_origins` to lista dokładnych originów HTTPS repozytorium plików zwracającego PDF. Uwzględnij rzeczywisty origin otrzymany od administratora EZD. Linki z parametrami dostępowymi nie są zapisywane w logach. Prywatne CA można wskazać przez `ca_file`; weryfikacja TLS nie jest wyłączana. Klient nie korzysta automatycznie z proxy środowiskowego.

`metadata` mapuje tylko `request_id`, `request_url`, `letter_number` i `payload_sha256` na istniejące w EZD klucze i nazwy atrybutów. Usuń mapowanie, którego instancja nie obsługuje. Identyfikator wniosku i link są też zawarte w piśmie-wniosku. `APP_URL` musi wskazywać adres dostępny dla urzędników EZD; przejście do wniosku nadal wymaga uwierzytelnienia i uprawnień w Dyna.

Po skonfigurowaniu: panel Pisma → Zapisz w EZD → wybór sprawy → Dodaj dokument do kolejki EZD. Przetwarzanie:

```sh
.venv/bin/python manage.py process_integrations
```

Komendę należy uruchamiać okresowo jako użytkownik usługi. W lokalnym środowisku nie uruchomiono automatycznej wysyłki do żadnego zewnętrznego operatora.

## Błędy i uzgadnianie wyników

`RETRY` dotyczy błędu połączenia przed wysłaniem albo jawnej odmowy HTTP 429. Ponowienie ma termin, rosnące opóźnienie i limit pięciu prób. Zapisane etapy nie są ponownie wykonywane. HTTP 401/403 daje `CONFIG_ERROR`, jawny błąd walidacji `REJECTED`. Timeout po wysłaniu, HTTP 5xx/409 i przerwanie procesu dają `REVIEW_REQUIRED` — bez automatycznego ponowienia mutującego POST.

Administrator techniczny może wskazać identyfikatory po sprawdzeniu wyniku w EZD. Komenda odczytuje API i weryfikuje powiązanie przestrzeni oraz SHA-256 PDF:

```sh
.venv/bin/python manage.py reconcile_ezd_job IDENTYFIKATOR_OPERACJI \
  --actor EMAIL_ADMINISTRATORA \
  --case-id IDENTYFIKATOR_SPRAWY \
  --document-id IDENTYFIKATOR_DOKUMENTU \
  --reason 'Uzgodnienie po przerwaniu odpowiedzi EZD'
```

Po poprawieniu samej konfiguracji można pominąć identyfikatory już zapisane w operacji. Po niepewnym utworzeniu dokumentu wymagany jest identyfikator dokumentu. Komenda nie przyjmuje deklaracji „na pewno nie utworzono” jako podstawy do ponownego POST. Niepewną operację bez rozstrzygających danych trzeba uzgodnić z administratorem/operatorami EZD; nie edytować ręcznie statusu w bazie.

Odtworzenie backupu wstrzymuje oczekujące operacje. Snapshot nie pozwala ustalić, co operator przyjął już po jego wykonaniu. Przed podłączeniem odtworzonego systemu uzgodnij również operacje powstałe po dacie backupu, których w kopii może nie być.

## Test akceptacyjny na rzeczywistym EZD

Uzyskaj środowisko według `docs/DOSTEP-EZD-RP.md`. Używaj wyłącznie fikcyjnych danych w piaskownicy. Wykonaj osobno zapis w istniejącej sprawie i utworzenie nowej, sprawdź dokument i atrybuty w interfejsie EZD, pobierz PDF i porównaj SHA-256, otwórz link do Dyna jako właściwa i niewłaściwa rola. Sprawdź przerwanie komunikacji oraz uzgodnienie wyniku bez drugiego dokumentu. Zapisz wersję EZD, rewizję Dyna, czas, identyfikatory i dowody bez sekretów.

## Pozostały zakres celu

Zaimplementowano odczyt RPW przez API v2, powiązanie identycznych dokumentów z wnioskami, archiwum wpływów i zapis identyfikatora/linku w metadanych dokumentu. Instrukcja i granice dowodów: `docs/WPLYWY-EZD.md`. Nie potwierdzono wyświetlenia/kliknięcia linku w rzeczywistym EZD ani webhooków operatora. Niejednoznaczne/skanowane dokumenty wymagają dalszego rozstrzygnięcia. Rejestracja korespondencji wychodzącej EZD z dowodami doręczeń pozostaje otwarta. Instancja urzędu, JRWA, uprawnienia, repozytorium i jego mechanizm dostępu wymagają rzeczywistego testu. e-Doręczenia, kwalifikacja podpisów i pozostałe wymagania całego celu również nie są jeszcze odebrane.
