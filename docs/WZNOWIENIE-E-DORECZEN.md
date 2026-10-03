# Bezpieczne wznowienie e-Doręczeń

Stan: 03.10.2026. Kod i lokalne testy wykonane bez kontenerów. Nie jest to odbiór
integracji INT/PROD. Nadal brakuje przydzielonego dostępu, ADE testowych i
certyfikatu systemu zarejestrowanego u operatora.

## Problem i wynik

Po błędzie konfiguracji zlecenie pozostawało zatrzymane. Istniejące polecenie
umożliwiało tylko wznowienie odczytów znanego zadania operatora. Nie można było
wznowić operacji, która zatrzymała się przed wysłaniem wiadomości.

Nowe zlecenia przechowują wersję mechanizmu kontrolującego granicę wysyłki
(`submission_guard_version=1`). Zapis IN_FLIGHT nadal następuje przed zewnętrznym
POST. Tylko jednoznaczny błąd sprzed wysyłki lub odpowiedź o nieprzyjęciu zapisuje
NOT_ACCEPTED z flagą safe_to_resubmit. Sam dawny zapis NOT_COMPLETED nie stanowi
dowodu braku wysyłki.

| Zapisany stan | Dopuszczalne działanie |
| --- | --- |
| Nowe zlecenie, brak rozpoczętego etapu send, zatrzymane po błędzie przed wysyłką | Administrator może sprawdzić konfigurację i wznowić to samo zlecenie |
| NOT_ACCEPTED i trwała flaga safe_to_resubmit=true | Po naprawie możliwe wznowienie tego samego zlecenia |
| COMPLETED z task_id | Wyłącznie weryfikacja zadania i wznowienie odczytów |
| IN_FLIGHT, timeout zapisu/odczytu POST, HTTP 408/409/5xx, 202 bez task_id | Ponowienie wysyłki zablokowane; ustalić wynik z operatorem |
| Starszy zapis bez wersji mechanizmu lub NOT_COMPLETED | Ponowienie wysyłki zablokowane; historia nie dowodzi braku przyjęcia |
| Zlecenie odtworzone z kopii | Bez ponownej wysyłki; znane task_id może zostać zweryfikowane i obserwowane |

Konektor klasyfikuje HTTP 400, 401, 403 i 429 jako odmowę przyjęcia, a błąd
nawiązania połączenia jako brak wysłania żądania wiadomości. Inne odpowiedzi 4xx
nie otrzymują flagi bezpiecznego ponowienia. HTTP 400/202 są opisane w zapisanym
kontrakcie UA `docs/api/uaapi_3.0.8.2.yaml`; pozostałe klasyfikacje bazują na
semantyce HTTP. Zachowanie bramy/operatora dla tych odmów trzeba potwierdzić
w rzeczywistym scenariuszu INT. Testy MockTransport nie dowodzą zachowania jego
infrastruktury. Aktualne wersje API: [oficjalna strona](https://www.gov.pl/web/e-doreczenia/interfejsy-api).

## Panel i polecenia

Administrator techniczny: Integracje → „Sprawdź możliwość wznowienia”. Ekran
pokazuje dozwolony tryb, wymaga uzasadnienia do 500 znaków i sprawdza wersję
operacji. Otwarcie strony nie wywołuje API ani nie zmienia kolejki. Powiat i UMP
nie mają uprawnienia do tego działania; otrzymują HTTP 403 z polskim komunikatem.
Administrator nie otrzymuje treści dokumentu ani możliwości pobrania PDF.

Wznowienie niewysłanej operacji:

```sh
.venv/bin/python manage.py resume_edor_unsent UUID_ZADANIA \
  --actor admin@example.invalid --reason 'Naprawiono konfigurację urzędu'
```

Polecenie sprawdza integralność zapisanych bajtów PDF, kompletną kopię danych,
tożsamość środowiska/nadawcy, aktywność obu urzędów i zgodność ADE z oryginalnym
zleceniem. Wykonuje uwierzytelnienie i potwierdzenie publicznego, aktywnego ADE
adresata. Nie wykonuje POST wiadomości. Po pomyślnej kontroli zmienia status na
QUEUED; wysyłkę wykona zwykły pracownik kolejki.

Zachowuje UUID, klucz deduplikacji, oryginalny PDF, SHA-256, treść, adresata oraz
całkowitą liczbę prób. Zeruje tylko budżet kolejnych błędów. Nie pobiera później
zmienionego dokumentu z pisma. Zmiana ADE lub środowiska wymaga odrębnego
rozstrzygnięcia, zamiast automatycznego przekierowania korespondencji.

Wznowienie znanego zadania operatora:

```sh
.venv/bin/python manage.py resume_edor_observation UUID_ZADANIA \
  --actor admin@example.invalid --reason 'Przywrócono dostęp do odczytu zadania'
```

Ten tryb nie wysyła ponownie dokumentu. Jest też dostępny w panelu. Błąd
konfiguracji lub odczytu pozostawia zlecenie zatrzymane; interfejs pokazuje
komunikat bez treści błędu operatora i bez sekretów.

Wznowienie jest zapisywane w audycie wraz z administratorem, UUID, poprzednim
stanem i uzasadnieniem. API odczyty wykonywane są poza blokadą bazy. Następnie
krótka transakcja blokuje urzędy w stałej kolejności i zlecenie, ponownie sprawdza
dane oraz datę aktualizacji. Równoczesne wznowienie może zatwierdzić tylko jeden
administrator. Zmiana zadania lub dezaktywacja urzędu podczas kontroli zatrzymuje
operację.

Tuż przed zapisem IN_FLIGHT pracownik blokuje zlecenie i sprawdza, czy nadal
ma bieżącą próbę oraz ważną dzierżawę. Jeśli stara próba zatrzymała się przed
wysyłką, a później zadanie odzyskano i wznowiono, stary pracownik nie wykona POST.
Końcowy zapis wyniku wymaga zgodnej próby i statusu PROCESSING; spóźniona próba
nie nadpisze bieżącego wyniku. Taki przypadek zapisuje audyt
integration.worker.superseded. Po zapisaniu IN_FLIGHT niepewny wynik nadal
blokuje ponowienie: samo wygaśnięcie dzierżawy nie dowodzi braku wysyłki.

## Odtwarzanie i aktualizacja

Odtworzenie SQLite i PostgreSQL dodaje restore_requires_reconciliation=true do
wszystkich zleceń EDOR, także dawnych CONFIG_ERROR i REJECTED. Te stany mogły już
zostać naprawione i wysłane w źródle po wykonaniu kopii. Flagi nie usuwa się
ręcznie. Blokada działa również wtedy, gdy ktoś ręcznie zmieni status na QUEUED.
COMPLETED z task_id nadal umożliwia bezpieczne odczyty po weryfikacji zadania.

Nie ma nowej migracji schematu; stan jest przechowywany w dotychczasowym JSON.
Po aktualizacji uruchom ponownie aplikację i pracownika. Starsze zlecenia bez
wersji mechanizmu pozostają do uzgodnienia z operatorem; nie nadajemy im
automatycznie dowodu niewysłania. Odmowa wznowienia jest zamierzona dla historii,
której nie można udowodnić.

## Dowody lokalne

- SQLite: 53 PASS, 2 SKIP PostgreSQL (55 testów, 7,010 s): konektory e-Doręczeń
  i EZD, wznowienia, wspólna kolejka i kopia z odtworzeniem do osobnego katalogu.
- PostgreSQL 18.6: 59/59 PASS (9,767 s): konektory e-Doręczeń i EZD, rzeczywiste
  równoczesne wznowienie, claim pracy, powrót starego pracownika po nowej próbie
  oraz 6 testów pg_dump/pg_restore.
- W obu przebiegach zawarto regresję wspólnego typu błędów i kolejki EZD/SMTP.
  Wcześniejszy osobny przebieg EZD: 16/16 PASS (0,180 s), przed dodaniem końcowej
  kontroli próby. Aktualnym dowodem są powyższe przebiegi 55 i 59 testów.
- Testy sprawdzają niezmienny dokument i adresy, jedną przyjętą wysyłkę po
  wznowieniu, odrzucenie niepewnych wyników, dawnych etapów, obcego środowiska,
  odtworzonej kopii, niepoprawnego PDF, obcych ról, braku CSRF oraz starego
  formularza. Żądania zewnętrzne używają MockTransport, z rzeczywistym podpisem
  JWT, biblioteką HTTP i fikcyjnym certyfikatem. Test współbieżności administratorów
  podstawia wyłącznie odczytowy klient preflight; blokady są rzeczywistym PostgreSQL.
  Osobny test dwóch połączeń PostgreSQL zatrzymuje starego pracownika przed POST,
  odzyskuje wygasłe zlecenie, wznawia i wykonuje nową próbę. Po powrocie starego
  pracownika pozostaje jeden POST, wynik nowej próby i liczba prób równa 2.
  W tym scenariuszu podstawiony klient izoluje wyłącznie zewnętrzne I/O.
- Chrome na osobnej bazie SQLite, localhost: OTP administratora → formularz
  niewysłanej operacji → czytelna odmowa bez profilu; niepewna i odtworzona
  operacja bez przycisku wznowienia; OTP powiatu → bezpośredni adres → HTTP 403
  i polski komunikat. Zrzuty obejrzano wizualnie.
- Trzy zlecenia UI są jawnie fikcyjnymi scenariuszami, utworzonymi tylko w
  `var/edor-resume-ui-20261003`. Nie przedstawiają rzeczywistych operacji operatora.
  Nie uruchomiono tam pracownika ani profilu zewnętrznego. Po testach statusy,
  liczby prób i dokumenty pozostały niezmienione.

Pliki dowodów: `evidence/edor-resume-sqlite-tests.txt`,
`evidence/edor-resume-postgres-tests.txt`, `evidence/edor-resume-ezd-regression.txt`,
`evidence/17-edor-wznowienie-bez-profilu.jpg`, `evidence/18-edor-niepewna-operacja.jpg`,
`evidence/19-edor-powiat-brak-uprawnien.jpg`, `evidence/edor-resume-ui-state.json`,
`evidence/health-after-edor-resume.json`.

Główna aplikacja pod http://127.0.0.1:8765/ została ponownie uruchomiona z tym
kodem. Health zwrócił 200; SHA-256 sześciu tabel biznesowych zgadza się ze stanem
sprzed aktualizacji. Strona publiczna w Chrome działa bez błędów konsoli.
Nie uruchomiono wysyłki ani nie zmieniono dokumentów w głównej bazie.

Nie wykonano pomyślnego wznowienia przez Chrome z rzeczywistym API. Ten scenariusz,
kontrola obu skrzynek pod kątem duplikatów oraz walidacja podpisów dowodów czekają
na INT. Pełny cel systemu pozostaje aktywny.
