# e-Doręczenia — konfiguracja i zakres konektora

Stan na 03.10.2026: kod UA API v3 i SE API v4 oraz testy kontraktowe są zaimplementowane. **Nie wykonano uwierzytelnionego testu INT/PROD ani testu na instancji urzędu.** Brakuje przydzielonego środowiska, adresów ADE i certyfikatu zarejestrowanego systemu. Stan całego celu: prace trwają.

## Oficjalne źródła i kontrakty

- [Obowiązujące API](https://www.gov.pl/web/e-doreczenia/interfejsy-api): UA API v3, SE API v4; UA v1/v2 wycofano. Lokalny kontrakt UA: `docs/api/uaapi_3.0.8.2.yaml`, wersja `info.version` 3.0.8, pobrany z archiwum operatora. SE: `docs/api/se-api_v.4.0.5.yaml`, wydobyty z załącznika osadzonego w oficjalnym projekcie technicznym v4. Pochodzenie i SHA-256 zapisano w `docs/api/manifest.json`.
- [Materiały integracyjne i zgłoszenie 2a](https://www.gov.pl/web/e-doreczenia/integracja-uslugi-e-doreczen-z-systemami-klasy-ezd): instrukcja uwierzytelniania podpisanym JWT (01.07.2025, v1.97) i projekt SE API v4.
- [Projekt techniczny UA API 5.27](https://edoreczenia.poczta-polska.pl/wp-content/uploads/2025/09/COI-Projekt-Techniczny-UA-API_5.27-1.pdf): zadanie asynchroniczne, statusy (reguła R9), pobieranie dowodów, odczyt wiadomości.

Rozbieżności w opublikowanych materiałach wymagające potwierdzenia podczas INT:

1. YAML UA wskazuje `servers: /api/v1`, chociaż strona ministerstwa i instrukcja integracji wskazują v3. Konfigurujemy jawny adres kończący się `/api/v3`.
2. `MessageOperationResponseWrapperStatus.required` zawiera `addresseeAde` i `status`, których nie ma w `properties`. Konektor używa zdefiniowanych `messageId`, `addressee.eDeliveryAddress` i `error`; poświadcza jednego, właściwego adresata. Odmienna odpowiedź zatrzyma operację do sprawdzenia.
3. Przykład początkowy JWT zawiera `aud` z HTTP, lecz przykład Postman i zakodowany JWT używają HTTPS. Przykładowy profil używa HTTPS. Właściwy identyfikator odbiorcy tokenu należy potwierdzić z operatorem; połączenia bez TLS są zabronione.
4. `FileMetadata.alg/hash` są opcjonalne, a określenie „SHA-3” nie ustala długości ani kodowania hasza. Nie zgadujemy tych wartości: wysyłamy wymagany `fileId`, nazwę, MIME, rozmiar i bajty base64. SHA-256 dokumentu jest przechowywany lokalnie. Jeśli operator INT wymaga dodatkowych parametrów, konieczna jest udokumentowana korekta kontraktu.

## Urząd, certyfikat i profil

Każdy urząd wysyła z własnego ADE i profilu zarejestrowanego systemu. Jedna instancja rejestru nie oznacza wspólnego upoważnienia do wszystkich skrzynek. Najpierw uzyskaj dostęp zgodnie z `docs/DOSTEP-E-DORECZENIA.md`.

1. Dodaj system w module uprawnień dostawcy. Zachowaj dokładną nazwę systemu, adres ADE i certyfikat wydany/zaakceptowany dla systemu.
2. Umieść klucz prywatny RSA (co najmniej 2048 bitów) i certyfikat X.509 PEM w prywatnym katalogu poza repozytorium. Certyfikat musi odpowiadać kluczowi i być ważny czasowo. To certyfikat uwierzytelniający integrację, **nie podpis kwalifikowany pisma**.
3. Skopiuj `docs/api/edor-config.example.json` do prywatnej lokalizacji. Zastąp fikcyjny ADE, nazwę systemu i ścieżki rzeczywistymi danymi środowiska INT. Dodaj osobne wpisy dla innych urzędów. Klucz wpisu, np. `ump`, to `Office.id`.
4. Ustaw uprawnienia katalogu 0700, plików 0600. Opcjonalne pole `private_key_password_file` wskazuje prywatny plik hasła do zaszyfrowanego klucza. Hasła, PEM ani tokeny nie mogą trafić do logów i Git.
5. Ustaw `EDOR_CONFIG_FILE` na bezwzględną ścieżkę pliku JSON i uruchom ponownie aplikację oraz pracownika kolejki. Opcjonalny `ca_file` wskazuje zatwierdzony zestaw CA dla TLS; walidacji TLS nie można wyłączyć w konfiguracji.
6. W administracji ustaw ADE urzędów. ADE nadawcy musi być identyczny z profilem, a adresat musi mieć inny poprawny ADE. Zweryfikuj nazwę i tożsamość urzędu w BAE; system nie przypisuje adresów automatycznie na podstawie podobnej nazwy.

Przykładowy profil zawiera wyłącznie placeholders. Nie jest działającym dostępem. Zgodność klucza i certyfikatu nie potwierdza rejestracji systemu ani uprawnień u operatora.

## Uwierzytelnianie i obsługiwane operacje

RFC 7523: JWT RS256 z `iss/sub=ADE.SYSTEM.NAZWA_SYSTEMU`, `aud` realm, bieżącymi `iat/nbf`, `exp` po 300 s i losowym `jti`. Żądanie tokenu używa `client_credentials`, `client_assertion_type`, podpisanej asercji i `login_hint=ADE.<adres>`. Token ma cache w pamięci procesu, do wygaśnięcia z marginesem 5 s, z kluczem obejmującym certyfikat i profil. Nie jest zapisywany do bazy ani plików. Oddzielny proces ma własny cache; dla ciągłej obsługi wykorzystuj stałego pracownika, zamiast częstego uruchamiania nowych procesów. Włącz synchronizację czasu hosta.

| Cel | Wywołanie |
|---|---|
| Wyszukanie podmiotu publicznego | SE `POST /search/bae_search`, do 20 wyników na stronę, aktualna wersja danych (`index=1`) |
| Potwierdzenie aktywnego ujawnionego ADE adresata | SE `POST /search/eda-confirmation` |
| Wysłanie jednego PDF do jednego urzędu | UA `POST /{ADE}/messages`, HTTP 202 z `messageTaskId` |
| Sprawdzenie zadania | UA `GET /{ADE}/messages/tasks/{taskId}/status` |
| Ustalenie identyfikatora wiadomości | UA `GET /{ADE}/messages/tasks/{taskId}` |
| Status nadania/doręczenia | UA `GET /{ADE}/messages/{messageId}?format=metadata` |
| Lista dowodów | UA `GET /{ADE}/messages/{messageId}/evidences` |
| Oryginalne bajty dowodu | UA `GET /{ADE}/evidences/purde/{evidenceId}` |

Odczyt statusu używa `metadata`; nie pobiera trybu `full/fullExtended`, który może oznaczać otwarcie wiadomości. Konektor nie odpytuje dowolnych URL z pola `externalData`. Żądania Bearer trafiają wyłącznie do skonfigurowanych API; przekierowania są wyłączone. Treści błędów operatora i nagłówki autoryzacji nie trafiają do logu aplikacji.

## Kolejka i odtwarzanie

Wysyłka w panelu Pisma utrwala PDF, SHA-256, treść, tytuł, nadawcę, adresata, środowisko i identyfikator sprawy. Ponowne kliknięcie wskazuje to samo zadanie. Późniejsza zmiana pisma lub ADE urzędu nie modyfikuje tego zlecenia.

Pracownik:

```sh
.venv/bin/python manage.py process_integrations
```

Polecenie jednorazowo obsługuje do 100 gotowych operacji. Zaplanuj uruchamianie zgodnie z instrukcją instalacji. Przyjęte zadanie jest najpierw obserwowane po 60 s, następnie status wiadomości co 5 minut. Sprawdzenie poprawnego statusu zeruje licznik kolejnych błędów odczytu. Obserwacja nie powoduje ponownej wysyłki.

- `MONITORING`: zadanie przyjęte albo wiadomość nadal oczekuje na status/dowody.
- `EDOR_DELIVERED`: API zwróciło „Doręczona” i zarchiwizowano dowód odbioru (E.1 lub biznesowy BP.OP/BP.OX).
- `EDOR_DEEMED`: „Uznana za doręczoną” i dostępny dowód biznesowy. Stan pozostaje odrębny od faktycznego odbioru.
- `EDOR_REJECTED` / `EDOR_FAILED`: negatywny status i odpowiadający dowód operatora.
- `RETRY`: błąd odczytu, brak połączenia przed wysłaniem albo HTTP 429; narastające opóźnienie, maksymalnie 5 kolejnych błędów.
- `REVIEW_REQUIRED`: niepewny POST, błąd kontraktu/identyfikacji, przerwany pracownik lub zmiana celu. Automatyczna ponowna wysyłka jest zablokowana.
- `CONFIG_ERROR`, `REJECTED`, `RETRY_EXHAUSTED`: potrzebna poprawa konfiguracji lub sprawdzenie wyniku.

Dokumentowane statusy pokazują wynik API wraz z zachowanym dowodem. **Nie potwierdzają lokalnej walidacji podpisu kryptograficznego dowodu.** Oryginały są zapisane w bazie z SHA-256, kontrolowane przed pobraniem i w kopii zapasowej. Dostęp do pobrania ma właściwy urząd oraz UMP według uprawnień do pisma. Administrator techniczny nie pobiera dokumentów biznesowych.

Gdy znane zadanie wymaga wznowienia obserwacji, administrator techniczny może wykonać:

```sh
.venv/bin/python manage.py resume_edor_observation UUID_ZADANIA \
  --actor admin@example.invalid --reason 'Uzasadnienie po sprawdzeniu konfiguracji'
```

Polecenie odczytuje i weryfikuje zadanie przez API, a następnie wznawia wyłącznie odczyty. Nie działa dla niepewnego POST bez potwierdzonego identyfikatora zadania. W takim przypadku ustal wynik z operatorem; **nie edytuj ręcznie statusu na QUEUED i nie twórz drugiej wysyłki**.

Odtworzenie kopii zawsze wstrzymuje kolejkę, w tym obserwowane zadania. Przywrócona baza może być starsza niż wynik u operatora. Potwierdzone zadanie można sprawdzić i wznowić powyższym poleceniem.

Jednoznacznie niewysłane nowe zlecenie można po naprawie konfiguracji wznowić
przez panel administratora (Integracje → „Sprawdź możliwość wznowienia”) lub
`manage.py resume_edor_unsent UUID --actor admin@example.invalid --reason 'Uzasadnienie'`.
Wznowienie sprawdza profil i ADE, zachowuje oryginalny dokument oraz identyfikator,
a wysyłkę pozostawia pracownikowi. Niepewne i starsze zapisy oraz odtworzona
kopia nie umożliwiają ponownej wysyłki. Reguły, procedura aktualizacji i wyniki:
`docs/WZNOWIENIE-E-DORECZEN.md`.

## Obowiązkowy scenariusz INT

1. Zarejestruj własne testowe podmioty i system, skonfiguruj dwa ADE INT; nie używaj danych rzeczywistych ani ADE produkcyjnych.
2. Potwierdź parametry JWT, właściwe endpointy i odpowiedzi rozbieżnych elementów kontraktu.
3. Wyszukaj odbiorcę w panelu, porównaj tożsamość podmiotu i potwierdź aktywne ADE.
4. Wyślij fikcyjne pismo z konta nadawcy; zachowaj lokalny SHA-256 PDF, identyfikator zadania i wiadomości, czas oraz odpowiedź statusową bez sekretów.
5. Odbierz pismo w testowej skrzynce adresata, porównaj SHA-256 rzeczywistego załącznika, odczytaj status i pobierz oryginalne dowody nadania/odbioru. Zweryfikuj sumy pobranych plików.
6. Sprawdź kontrolowane przerwanie pracownika, ponowne kliknięcie i wznowienie odczytów. Potwierdź w obu skrzynkach brak duplikatu.
7. Oddzielnie wykonaj walidację podpisów dowodów według aktualnego formatu/trust listy dostawcy. Zapisz dowody, środowisko i ograniczenia w raporcie.

## Ograniczenia i dalsze prace

Obecny zakres to korespondencja elektroniczna między urzędami, jeden PDF do 10 MB i treść do 5000 znaków. Obsługa PUH, masowej wysyłki, odbioru nowych spraw ze skrzynki oraz webhooków nie jest wdrożona. Nie ma jeszcze walidacji podpisów XML/PDF dowodów, oceny kwalifikowanego podpisu/znaczników czasu ani udowodnionych testów INT. Niepewnej wysyłki bez taskId nie można automatycznie uzgodnić. Bezpieczne wznowienie jednoznacznie niewysłanych nowych zleceń jest zaimplementowane i sprawdzone lokalnie; wymaga jeszcze testu INT. Pozostałe ograniczenia pozostają w rejestrze prac całego celu.
