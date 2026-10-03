# Ochrona publicznego wyszukiwania

Stan: 03.10.2026. Implementacja i testy serwera wykonane lokalnie, bez Dockera.
Pełny audyt WCAG, test urządzeń mobilnych i odbiór infrastruktury urzędu są otwarte.

## Mechanizm

Publiczny formularz HTML i GET `/api/availability/` współdzielą licznik na
REMOTE_ADDR: domyślnie 30 prób w oknie 60 sekund. Po pierwszych 10 próbach każde
kolejne sprawdzenie wymaga nowego jednorazowego wyniku ALTCHA v2. Brak weryfikacji
zwraca 403; twardy limit zwraca 429 i Retry-After. Poprawny PoW nie znosi limitu.
Niepoprawne zapytania również zużywają budżet; przy odmowie nie uruchamia się
sprawdzania ewidencji. Wstępne otwarcie pustej strony nie zużywa limitu.

Zastosowano oficjalną bibliotekę Python altcha 2.1.0 oraz widget 3.2.4. Weryfikacja
PBKDF2/SHA-256 z kosztem 5000 i prefiksem 00 odbywa się na instancji aplikacji.
Losowe wyzwanie jest podpisane HMAC, ważne 5 minut i zapisane w bazie. Wynik jest
powiązany z losowym kontekstem sesji oraz IP i zużywany w transakcji z blokadą.
Zmienione parametry, fałszywe wyniki, obca sesja/IP, wygaśnięcie i replay są
odrzucane. Koszt i algorytm do weryfikacji pochodzą z zapisanej kopii serwera.
Długość payloadu i zakres licznika są ograniczone przed obliczeniem KDF.

PoW zwiększa koszt masowego odpytywania; nie jest dowodem tożsamości ani gwarancją
rozpoznania wszystkich botów. Nie zastępuje kontroli wolumenu na reverse proxy,
monitorowania, testu obciążenia i doboru progów do użytkowników za wspólnym NAT.

Podstawa: [oficjalna biblioteka Python](https://github.com/altcha-org/altcha-lib-py),
[integracja widgetu](https://altcha.org/docs/integration/widget/),
[opis PoW](https://altcha.org/docs/how-it-works/).

## Samodzielne wdrożenie i prywatność

Widget, polskie tłumaczenia, zewnętrzny CSS i jeden worker są dostarczane z
własnego katalogu static. Nie używa się CDN, konta, API key ani usługi Cloud lub
Sentinel. Skrypt nie kontaktuje się z dostawcą podczas weryfikacji. Kolektor
Human Interaction Signature jest wyłączony. Odnośnik do strony projektu pozostaje
atrybucją; nie jest automatycznie otwierany.

Manifest w `registry/static/registry/altcha/manifest.json` zawiera wersję, źródło
npm, sprawdzoną sumę integrity archiwum i SHA-256 plików. Licencja MIT została
zachowana. Nie wykonywano skryptów instalacyjnych npm ani globalnej instalacji.

Aplikacja używa własnego ciasteczka sesji do powiązania wyzwania. W bazie jest
HMAC powiązania, bez jawnego IP ani losowego sekretu kontekstu sesji. Payload PoW
jest przesyłany w POST formularza lub nagłówku API; nie umieszczaj go w URL.
Formularz POST wymaga CSRF. Odpowiedzi wyszukiwania i wyzwania mają no-store.
Konfiguracja i logowanie serwera nie powinny archiwizować ciał POST ani tego
nagłówka.

Endpoint `/api/public-challenge/` wydaje do 10 nowych wyzwań/minutę/IP. Własny
sekret HMAC jest wyprowadzany z klucza aplikacji z osobną etykietą; nie jest
wysyłany do przeglądarki. Odtworzenie SQLite lub PostgreSQL unieważnia wszystkie
niewykorzystane wyzwania, niezależnie od unieważnienia sesji.

## Konfiguracja administratora

Zmienne środowiska:

- PUBLIC_QUERY_LIMIT=30 — twardy limit na minutę;
- PUBLIC_CAPTCHA_THRESHOLD=10 — liczba prób bez dodatkowej weryfikacji;
- PUBLIC_CAPTCHA_COST=5000 — koszt PBKDF2.

Wymagane jest 0 < próg < limit <= 1000 i koszt 100–20000. Nie ma przełącznika
wyłączającego ochronę produkcyjną. Tryb testowy widgetu nie jest włączany.
Testy jednostkowe obniżają koszt do 10 wyłącznie w override_settings. Końcowa osobna
instancja Chrome ma próg 1, limit 30 i rzeczywisty koszt 5000, aby szybko pokazać
wymaganą weryfikację.

Reverse proxy musi przekazać prawidłowy adres klienta przez zaufaną konfigurację
serwera aplikacji. Aplikacja celowo nie ufa dowolnemu X-Forwarded-For z żądania.
Przed wdrożeniem należy sprawdzić cały łańcuch proxy; bez tego wszystkie osoby
mogą dzielić limit adresu proxy. Nie wystawiaj serwera aplikacji obok proxy.

CSP pozostaje ograniczona do self. Wersja external używa workera i arkusza z
własnego hosta, bez blob:, unsafe-inline ani unsafe-eval. Produkcja wymaga HTTPS;
localhost jest kontekstem bezpiecznym w obsługiwanych przeglądarkach.

Po instalacji zależności wykonaj `manage.py migrate` (migracja 0006 dodaje tabelę
wyzwań bez zmiany tabel biznesowych), następnie collectstatic według instrukcji
wdrożenia. Po aktualizacji uruchom ponownie proces aplikacji.

Retencja danych ochrony:

```sh
# Podgląd, bez usuwania:
.venv/bin/python manage.py purge_security_state

# Usunięcie wyłącznie wygasłych wyzwań i liczników starszych niż 24 godziny:
.venv/bin/python manage.py purge_security_state --apply
```

Administrator powinien uruchamiać ten proces raz dziennie. Harmonogram nie został
zainstalowany na laptopie ani serwerze urzędu. Polecenie nie usuwa spraw,
dokumentów, danych kont ani audytu.

## API

Po 403 z code=CAPTCHA_REQUIRED klient pobiera challenge_url z odpowiedzi,
zachowując ciasteczko własnej sesji. Oblicza rozwiązanie zgodne z ALTCHA v2
(parameters/signature + solution) i przesyła base64 JSON w X-Altcha-Payload przy
następnym GET `/api/availability/?part=...`. Jedno rozwiązanie umożliwia jedno
sprawdzenie. Należy respektować 429 i Retry-After, również dla endpointu wyzwania.
Nie używaj pozornego sukcesu widgetu jako wyniku weryfikacji serwera.

## Dostępność i wyniki

Formularz zachowuje wpisany wyróżnik po odmowie. Widget ma polską nazwę checkboxa,
objaśnienie celu i widoczną informację o potrzebie weryfikacji. Nie wymaga
rozpoznawania obrazków ani słuchania dźwięku. Uruchomienie jest jawne (auto=off).
Bez JavaScript po progu wyświetla instrukcję uzyskania informacji w urzędzie.
Te elementy nie stanowią potwierdzenia pełnej zgodności WCAG. Należy jeszcze
sprawdzić czytniki ekranu, klawiaturę, powiększenie, kontrast i wydajność słabszych
urządzeń. Wymagania dotyczące CAPTCHA:
[W3C, kryterium 1.1.1](https://www.w3.org/WAI/WCAG21/Understanding/non-text-content).

- SQLite: 32 PASS, 1 SKIP PostgreSQL, 0,507 s — 9 testów nowej ochrony,
  21 regresji rdzenia i 2 testy kopii.
- PostgreSQL 18.6: 37/37 PASS, 2,798 s — powyższy rdzeń/ochrona,
  rzeczywisty replay dwóch transakcji i 6 testów pg_dump/pg_restore.
- Testy używają prawdziwego PoW biblioteki, podpisu HMAC, bazy i transakcji;
  nie podstawiają wyniku weryfikacji. Koszt testów jednostkowych jest obniżony.
- Test zgodności JavaScript/Python: rzeczywisty plik `pbkdf2.js` uruchomiony
  host-native w Node.js, dwa syntetyczne wektory PBKDF2/SHA-256 z kosztem 5000
  (znany licznik 17 i prefiks aplikacji 00), weryfikacja HMAC i rozwiązania w
  oficjalnej bibliotece Python oraz odrzucenie zmienionego klucza. Sumy wszystkich
  plików widgetu odpowiadają manifestowi. Polecenie:
  `.venv/bin/python scripts/verify-altcha-worker.py` (Node.js na PATH).
  Test jest offline, bez sesji aplikacji, bazy, sieci i interakcji z przeglądarką;
  nie jest potwierdzeniem ukończenia CAPTCHA w Chrome ani pomiarem wydajności
  urządzeń obywateli. Dowód: `evidence/altcha-worker-interoperability.json`.
- Chrome: dwa poprawne zapytania, trzecie bez wyniku ewidencji, polski checkbox
  i instrukcja; brak błędów/warnings w konsoli. Zrzut obejrzano wizualnie.
- Końcowy Chrome po otrzymaniu zgody: trzy zużyte dowody, naturalne pięć
  minut do wygaśnięcia, klawiatura, anulowanie wskaźnikiem, rzeczywiste 429
  pobrania wyzwania i udane ponowienie. Kod 772378a poprawia dostęp Tab
  do atrybucji. `ODBIOR-CAPTCHA.md` i `final-public-acceptance-proof.json`
  oddzielają te próby od wcześniejszego przygotowania i testów offline.
  Odczyt VoiceOver oraz pełny odbiór AA pozostają niepotwierdzone.

Dowody: `evidence/public-protection-sqlite-tests.txt`,
`evidence/public-protection-postgres-tests.txt`, `evidence/16-publiczna-weryfikacja.jpg`.
Główna aplikacja otrzymała migrację po utworzeniu prywatnej kopii. Weryfikacja
health i zachowania danych jest w `evidence/health-after-public-protection.json`.
Pełny cel, rzeczywiste API operatorów i odbiór urzędowy pozostają w toku.
