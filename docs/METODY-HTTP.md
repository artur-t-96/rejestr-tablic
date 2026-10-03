# Kontrola metod HTTP

03.10.2026. Baza `5ced2a3`, suma sprawdzonego `registry/views.py` jest
w `evidence/http-method-contract-http.json`. Zmiana nie wymaga migracji.

## Problem i działanie

Pobieranie PDF przyjmowało DELETE, zwracało plik i dopisywało zdarzenie
`letter.downloaded`. Nie było jawnego ograniczenia metod w części widoków
list, kart, administracji i dokumentów. API odczytywało treść nieobsługiwanej
metody przed jej sprawdzeniem: DELETE z błędnym JSON dawało 400 zamiast 405.
Oba przypadki odtworzono testami przed poprawką; zapis jest prywatnie
w `evidence/private/http-methods-before-fix.txt`.

Widoki mają teraz jawny kontrakt metod. W API kolejność to logowanie → rola
→ metoda → JSON → operacja. Odrzucana metoda zwraca 405 i nagłówek `Allow`,
bez wykonania widoku, pobrania PDF lub dopisania audytu pobrania. Dostęp
anonimowy do chronionego API nadal daje 401, a niedozwolona rola 403.
Istniejące filtry urzędu, kontrola nadawcy i walidacja danych pozostają
w odpowiednich usługach/widokach.

Kontrakt podany niżej jest literalny: np. „GET” nie dopuszcza HEAD.
Chronione widoki HTML sprawdzają logowanie przed metodą; middleware CSRF
może odrzucić niedozwoloną metodę niebezpieczną już wcześniej, jeśli
brakuje poprawnego tokenu. Próba HTTP używała poprawnego CSRF.

## Wykonane sprawdzenia

- 75/75 szybkich testów natywnych SQLite PASS: cztery nowe testy kontraktu,
  rdzeń, walidacja API wniosków/pul/korekt, czynności przy wpisie i podpisy.
  Zapis: `evidence/http-method-regression-tests.txt`.
- Nowy test porównuje wszystkie callbacki z `config/urls.py` z kontraktem;
  nowa trasa bez zdefiniowania metod przerywa test. Każda niedopuszczona
  metoda spośród GET/HEAD/POST/PUT/PATCH/DELETE/OPTIONS/TRACE jest sprawdzana.
- Rzeczywisty serwer na 8780, odrębna kopia SQLite, prawdziwe OTP UMP
  do lokalnej poczty i CSRF: 47 tras, 45 callbacków, **306 odpowiedzi 405**
  z właściwym `Allow`. Nie była to sesja `force_login`.
- Wszystkie wiersze ośmiu tabel przed/po 306 żądań identyczne: wnioski,
  wpisy, pisma, pule, numery, sekwencje, kolejka, audyt.
- Kontrola pozytywna: GET archiwalnego pisma zwrócił identyczne bajty
  i SHA-256, dopisał dokładnie jedno zdarzenie pobrania; pozostałe siedem
  tabel pozostało bez zmian.
- Osobne rzeczywiste HTTP z poprawnym CSRF i błędnym JSON: anonimowy 401,
  administrator po OTP 403; uprawniony UMP w macierzy otrzymał 405.
- Wszystkie 27 tabel głównej bazy zachowane po próbie. Ruff/check/format
  PASS. Nie uruchamiano Dockera ani PostgreSQL, nie wywoływano operatorów.

Zbiorcze szczegółowe wyniki: `evidence/http-method-contract-http.json`.
Kod testów: `registry/test_http_methods.py`. Kontrola 405 jest pełna dla
obecnych tras i wskazanych ośmiu metod, ale **nie jest pełnym odbiorem
dozwolonych operacji, ról ani izolacji obiektów**. Ta macierz pozostaje
następnym krokiem. Dostępność publiczna i rzeczywiste integracje nadal mają
oddzielne otwarte wymagania.

## Kontrakt wszystkich tras

Poniższa tabela jest spisem kontraktu użytego w rzeczywistym teście.

| Trasa | Metody |
|---|---|
| `/` | GET, POST |
| `/logowanie/` | GET, POST |
| `/logowanie/kod/` | GET, POST |
| `/wyloguj/` | POST |
| `/panel/` | GET |
| `/panel/wnioski/` | GET |
| `/panel/wnioski/nowy/` | GET, POST |
| `/panel/wnioski/<uuid:uuid>/` | GET, POST |
| `/panel/wnioski/<uuid:uuid>/<str:action>/` | POST |
| `/panel/ewidencja/` | GET |
| `/panel/ewidencja/<uuid:uuid>/` | GET, POST |
| `/panel/ewidencja/<uuid:uuid>/przedluz/` | POST |
| `/panel/eksport/` | GET |
| `/panel/import/` | GET, POST |
| `/panel/import/pule/` | GET, POST |
| `/panel/pule/` | GET |
| `/panel/pule/nowa/` | GET, POST |
| `/panel/pule/<uuid:uuid>/` | GET, POST |
| `/panel/pisma/` | GET |
| `/panel/pisma/<uuid:uuid>/pdf/` | GET |
| `/panel/pisma/<uuid:uuid>/podpis/` | GET, POST |
| `/panel/pisma/<uuid:uuid>/wersja/` | GET, POST |
| `/panel/pisma/<uuid:uuid>/wyslij/` | POST |
| `/panel/pisma/<uuid:uuid>/ezd/` | GET, POST |
| `/panel/audyt/` | GET |
| `/panel/integracje/` | GET |
| `/panel/integracje/ezd/wplywy/` | GET, POST |
| `/panel/integracje/ezd/wplywy/<uuid:uuid>/link/` | POST |
| `/panel/integracje/ezd/wplywy/<uuid:uuid>/pdf/` | GET |
| `/panel/integracje/adresy/` | GET, POST |
| `/panel/integracje/edor/<uuid:uuid>/wznow/` | GET, POST |
| `/panel/pisma/<uuid:uuid>/dowody/<int:evidence_pk>/` | GET |
| `/panel/administracja/` | GET |
| `/panel/administracja/konta/<int:user_pk>/zaproszenia/` | GET, POST |
| `/panel/administracja/konta/<int:user_pk>/zaproszenia/<uuid:uuid>/` | GET, POST |
| `/panel/administracja/<str:kind>/nowy/` | GET, POST |
| `/panel/administracja/<str:kind>/<str:pk>/` | GET, POST |
| `/api/health/` | GET |
| `/api/session/` | GET |
| `/api/session/extend/` | POST |
| `/api/availability/` | GET |
| `/api/public-challenge/` | GET |
| `/api/requests/` | GET, POST |
| `/api/requests/<uuid:uuid>/<str:action>/` | POST |
| `/api/records/<uuid:uuid>/` | GET, PATCH |
| `/api/pools/` | GET, POST |
| `/api/pools/<uuid:uuid>/issue/` | POST |
