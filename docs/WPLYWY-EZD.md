# EZD → Dyna: odbiór przesyłek wpływających

Stan: 03.10.2026. Zaimplementowany kod odczytu RPW i zapisu linku w metadanych.
Testy operatora używają MockTransport. Nie wykonano scenariusza na rzeczywistym
EZD: nadal potrzebne są instancja testowa, klucz i uprawnienia stanowiska.

## Źródło i zakres

Ponownie pobrano [oficjalny kontrakt NASK API v2](https://integrator-api.demo.ezdrp.gov.pl/swagger/v2/swagger.json).
HTTP 200, SHA-256 zgodny z zapisanym `docs/api/ezdrp-v2.json`:
`f4a44316998fc046c983a916d365141ade63dee832f4396ab6701cbd13ba3bff`.
Dokumentacja scenariuszy: [podręcznik NASK](https://podrecznik.ezdrp.gov.pl/przyklady-uzycia-metod-api-ezd-rp/).

Konektor korzysta z:

- `POST /ezdrp/integrator/v2/rpw/_search` — odczyt, nie utworzenie RPW;
- `GET /ezdrp/integrator/v2/rpw/{numer}/{rok}/metadane` — stan, przestrzeń i załączniki;
- `GET /ezdrp/integrator/v2/dokumenty/{id}/metadane`, dokument i link do repozytorium;
- osobno `PUT /ezdrp/integrator/v2/dokumenty/{id}/metadane` — zapis identyfikatora i URL.

W kontrakcie wyszukiwanie wymaga uprawnienia `Rejestry.PrzesylkiWplywajace`.
Profil urzędu i SID muszą mieć dostęp do właściwego RPW oraz dokumentów.
Nie wprowadzono domniemanego webhooka operatora. Odbiór działa jako jawny odczyt
po numerze lub okresowe przeglądanie rejestru przez API.

## Powiązanie i archiwum

Urząd odbiorcy otwiera Integracje → Wpływy z EZD, wpisuje numer, rok i uzasadnienie.
Odczyt nie zmienia statusu wniosku, rezerwacji ani decyzji. Administrator techniczny
nie ma dostępu do tego ekranu ani dokumentów. Urząd widzi wyłącznie swoje wpływy,
także gdy UMP ma szersze uprawnienia do ewidencji województwa.

Załącznik PDF musi odpowiadać przestrzeni i wersji wskazanej w RPW. Wersja jest
odczytywana ponownie po pobraniu. Repozytorium musi być dopuszczone w profilu;
Bearera nie przekazuje się do pobierania pliku. Limit to 10 MB na plik, 100
załączników i 8 poziomów zagnieżdżenia. Nie przyjmujemy usuniętego RPW ani stanu
w trakcie rejestracji jako potwierdzonego wpływu.

Automatyczne powiązanie wymaga identycznych bajtów z jednym pismem Dyna
adresowanym do urzędu odbiorcy. Sprawdzana jest integralność oryginału lub
podpisanego dokumentu, a powiązany wniosek wynika z tego pisma. Skonfigurowany
identyfikator w metadanych EZD, jeśli występuje, musi wskazywać ten sam wniosek.
Atrybut odczytu dopasowujemy po `id` albo `kluczSystemowy`, nigdy po podobnej
nazwie. Wartość URL z EZD nie steruje przekierowaniem w aplikacji.

Nieznany PDF, sprzeczny identyfikator lub niewłaściwy odbiorca pozostawia wpis
UNMATCHED bez treści dokumentu w archiwum Dyna. Zachowane są minimalne
identyfikatory, SHA-256 i komunikat do diagnostyki. Sam UUID nie jest dowodem
zgodnej treści. Skan/OCR albo zmieniony dokument wymagają osobnego rozstrzygnięcia;
ten etap nie wprowadza ręcznego przypisania takich plików.

Zgodny dokument jest archiwizowany z oryginalnymi bajtami, SHA-256, wersją i RPW.
Unikalny indeks oraz krótka blokada urzędu zapobiegają podwójnemu wpisowi przy
równoczesnych odczytach. Ten sam identyfikator wersji z innymi bajtami daje błąd;
nie nadpisuje archiwum. Nowa wersja ma odrębny wpis.

## Link w EZD i historia

Przycisk „Zapisz link w EZD” wymaga osobnego uzasadnienia. Profil musi mieć różne,
uzgodnione mapowania `request_id` i `request_url`. Przed PUT ponownie sprawdzane
są cel profilu, członkostwo dokumentu w RPW, wersja, przestrzeń, SHA-256 oraz
identyfikator wniosku. Zapis dotyczy wyłącznie dwóch skonfigurowanych atrybutów.
Nie tworzy dokumentu, RPW ani sprawy.

URL jest utrwalony przy powiązaniu. Powtórzenie po timeoutie używa tych samych
wartości i poprzedza je odczytem API. Nie wysyła ponownie pisma. Próba, granica
PUT, błąd i potwierdzenie mają stan w dzienniku oraz audyt. Wynik końcowy nie
nadpisze późniejszej próby. Niespodziewane przerwanie może pozostawić CHECKING
albo PUBLISHING; trzeba ponownie odczytać wynik, bez ręcznej deklaracji sukcesu.

Kontrakt PUT nie daje w tym miejscu potwierdzonego warunkowego zapisu konkretnej
wersji. Odczyty przed PUT ograniczają ryzyko zmiany, ale nie dowodzą atomowości
względem równoczesnej edycji w EZD. To wymagany scenariusz odbioru instancji.
Wyświetlanie atrybutu jako klikalnego linku i informacji o wpływie w interfejsie
EZD również musi zostać potwierdzone na rzeczywistym systemie urzędu.

W Dyna lista wpływów prowadzi do konkretnego wniosku i odebranego PDF. We wniosku
widoczna jest dokumentacja wpływu własnego urzędu. Audyt odbioru jest przypisany
urzędowi odbiorcy; historyczny wniosek nadawcy nie ujawnia jego dziennika wpływów.
PDF jest chroniony uprawnieniami i no-store, a błędny SHA-256 blokuje pobranie.

## Polecenia i okresowy odczyt

Odczyt jednej przesyłki:

```sh
.venv/bin/python manage.py receive_ezd_rpw 17 2026 \
  --actor ump@example.invalid --reason 'Kontrola wpływu RPW'
```

Opcja `--publish-links` zleca także zapis linków do zgodnych dokumentów.
Bez niej polecenie nie zapisuje nic w EZD.

Odczyt okresu:

```sh
.venv/bin/python manage.py sync_ezd_incoming \
  --actor ump@example.invalid --from 2026-10-01 --to 2026-10-03 \
  --max-pages 10 --reason 'Okresowa kontrola wpływów'
```

Zakres do 31 dni, 25 wpisów na stronę, maksymalnie 100 stron na uruchomienie.
Zakończenie wymaga potwierdzenia ostatniej strony z API. Przekroczenie limitu lub
błąd daje niezerowy wynik i komunikat o niepełnym odczycie. Powtórzenie tego
samego okresu jest bezpieczne: nie dubluje wersji dokumentów. Nie zapisujemy
kursora, który mógłby pominąć spóźnione wpisy; harmonogram urzędu powinien odczytywać
nakładające się okresy. Nie uruchomiono automatycznego połączenia z operatorem.

Obsługiwany numer odpowiedzi ma format `RPW/numer/rok`. Inny format zostanie
odrzucony do sprawdzenia. Sposób prezentacji numeru, paginację, zakres podmiotu
oraz kształt metadanych trzeba potwierdzić na przydzielonej instancji.

## Dowody i granice

- PostgreSQL 18.6: 50/50 PASS, 3,116 s. Rzeczywiste dwie sesje odbioru, deduplikacja,
  izolacja po przekazaniu wpisu oraz pg_dump/restore podpisanego PDF wpływu.
- SQLite: 45 PASS i 2 SKIP PostgreSQL, 47 testów, 0,585 s. Także rzeczywista kopia
  do osobnego katalogu i odrzucenie kopii z uszkodzonym dokumentem wpływu.
- HTTP jest MockTransport; baza, transakcje, uprawnienia, dokumenty i kopie są
  rzeczywiste. Testy nie dowodzą działania operatora.
- Chrome na osobnej bazie: OTP UMP → lista → brak profilu przy odczycie/zapisie
  linku → właściwy wniosek → odebrany PDF; OTP Piły → pusta lista i HTTP 404
  przy bezpośrednim pobraniu dokumentu UMP. Zrzuty obejrzano wizualnie.
- Dwa wpływy UI zostały utworzone przez rzeczywistą usługę importu z podstawionym
  transportem. Są jawnie fikcyjne; nie pochodzą od operatora. W serwerze UI nie
  skonfigurowano profilu zewnętrznego. Nie zapisano linku w rzeczywistym EZD.
- Migracja 0007 dodaje tabelę wpływów. Przed instalacją wykonano prywatny backup.
  Główna aplikacja działa z nowym kodem, health 200; sześć tabel biznesowych ma
  niezmienione skróty i nie dodano do niej fikcyjnych wpływów.
- Chrome na głównej aplikacji: sesja UMP otwiera nowy ekran wpływów; lista jest
  pusta zgodnie ze stanem głównej bazy. Brak błędów i ostrzeżeń konsoli. Zrzut 24
  przedstawia główną aplikację, a zrzuty 20–23 osobne fikcyjne scenariusze.

Dowody: `evidence/ezd-incoming-contract.json`, `ezd-incoming-sqlite-tests.txt`,
`ezd-incoming-postgres-tests.txt`, `ezd-incoming-ui-state.json`,
`health-after-ezd-incoming.json` oraz zrzuty 20–24 w katalogu `evidence`.

Pozostałe prace: rzeczywisty scenariusz EZD → Dyna → kliknięcie linku, mapowanie
niestandardowych/skanowanych pism, kwalifikowana walidacja podpisów, korespondencja
wychodząca EZD i dowody doręczeń, pełne wdrożenie urzędowe oraz pozostałe wymagania
całego celu. Ten etap nie jest odbiorem kompletnego produktu.
