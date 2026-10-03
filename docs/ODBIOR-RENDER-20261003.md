# Odbiór Dyna Rejestr Tablic na Render — 03.10.2026

## Wynik i adresy

Działająca aplikacja: **https://dyna-rejestr-tablic.onrender.com**.
Kod: prywatne [repozytorium GitHub](https://github.com/artur-t-96/rejestr-tablic).
Lokalna aplikacja również odpowiada pod http://127.0.0.1:8765/;
jej historyczna rewizja odbioru to `855358b7ab48059ff03d711c7d61b7eb4dd78e6c`.
Render obejmuje dodatkowo pocztę Microsoft, profil HTTPS/proxy i klientów PG18.
Uruchomienie natywne opisuje [README](../README.md), profil urzędu
[WDROZENIE-URZEDOWE.md](WDROZENIE-URZEDOWE.md).

Wyniki poniżej pochodzą z rzeczywistej usługi Render na
`59c6ce90ad68566da140c7647e3a4c8cde6bd9b3`, nie z lokalnej symulacji.
PR [#1](https://github.com/artur-t-96/rejestr-tablic/pull/1),
[#2](https://github.com/artur-t-96/rejestr-tablic/pull/2) oraz
[#3](https://github.com/artur-t-96/rejestr-tablic/pull/3) są scalone.
Hosted CI dla rewizji odbioru:
[PR](https://github.com/artur-t-96/rejestr-tablic/actions/runs/37128964010),
[main](https://github.com/artur-t-96/rejestr-tablic/actions/runs/37129212494)
— sukces wszystkich trzech zadań. PostgreSQL: 478 testów bez pominięć;
SQLite: 478 testów, 29 pominiętych przypadków PostgreSQL; pakiet klientów
PostgreSQL 18.6 wykonał rzeczywisty dump i restore w hosted CI.

Ten raport jest późniejszym uzupełnieniem [67 wymagań celu/specyfikacji](RAPORT-ODBIORU-LOKALNEGO.md)
i [macierzy](MACIERZ-ZGODNOSCI.md). Starsze dowody zachowują własne zakresy
oraz rewizje. Produkcyjny odbiór na fikcyjnych danych nie stanowi formalnego
odbioru prawnego, dostępności, skali ani konkretnej infrastruktury urzędu.

## Uzupełnienie walidacji i czytnika

[PR #5](https://github.com/artur-t-96/rejestr-tablic/pull/5) dostarczył polską
walidację błędnego publicznego wpisu przez serwer. Render uruchomił
`f88a82403438dd5cf6bfb44ab7f94c1dedfebf7f`, health potwierdził pełny SHA,
[CI main](https://github.com/artur-t-96/rejestr-tablic/actions/runs/37136905566)
przeszło wszystkie trzy zadania. W Chrome sprawdzono Q → błąd → odnośnik
do zachowanego pola → ANNA → wynik i sugestie, z oględzinami ekranów.
Rzeczywisty lokalny VoiceOver odczytał podstawowy formularz, błędy i wynik;
odczyt stanów CAPTCHA pozostaje częściowy. [Raport i granice dowodu](ODBIOR-CZYTNIKA-20261003.md).
Starsze scenariusze biznesowe poniżej zachowują rewizję swojego odbioru.

## Logowanie i konta demonstracyjne

Na stronie wybierz logowanie i zamów jednorazowy kod e-mail. Nie ma stałych
haseł; kod jest ważny przez 10 minut. Wszystkie poniższe adresy i aliasy
należą do użytkownika, a wiadomości trafiają do jego własnej skrzynki Outlook.
Nie zaproszono pracowników rzeczywistych urzędów.

| Adres | Rola / zakres |
|---|---|
| `artur.twardowski@b2bnetwork.pl` | ADMIN: konta, urzędy, szablony, diagnostyka |
| `artur.twardowski+dynaump@b2bnetwork.pl` | MAIN: demonstracyjny UMP |
| `artur.twardowski+dynakal@b2bnetwork.pl` | COUNTY: demonstracyjny Kalisz |
| `artur.twardowski+dynakon@b2bnetwork.pl` | COUNTY: demonstracyjny Konin, kontrola izolacji |

Pozostawiono własne konta do dalszych prób użytkownika. Tylko trzy urzędy
z 35 mają aktywowany dostęp demonstracyjny; pozostałe 32 są nieaktywne.
Domena własnych kont jest dopuszczona wyłącznie w tych trzech urzędach.
Dane oznaczono `TEST-RENDER-20261003`. To konfiguracja demonstracyjna,
nie gotowy słownik kontaktów i domen urzędów. Urząd musi zatwierdzić
konfigurację kont, treść szablonów, słownik i politykę retencji przed
wykorzystaniem rzeczywistych danych.

## Rzeczywiste scenariusze produkcyjne

| Obszar | Wykonana próba i wynik |
|---|---|
| Publiczny serwis | `P9DYN01` wolny przed wnioskiem, propozycje alternatyw; po zbyciu niedostępny, bez danych właściciela i VIN |
| Role i logowanie | Rzeczywiste OTP Microsoft i wejście w Chrome jako ADMIN, MAIN oraz oba COUNTY |
| Moduł I | W/2026/00001: rezerwacja 03.10→17.10, złożenie, akceptacja UMP, pismo, wpis, wydanie z fikcyjnym VIN, zbycie oraz uzasadniona korekta pojazdu |
| Moduł II | W/2026/00002: złożenie, przydział P001–P003, pismo, wydanie P001 i licznik 1/3 |
| Moduł III | W/2026/00003: stacja i okres; decyzja bez końca okresu odrzucona bez zmiany stanu, poprawna decyzja do 03.10.2027, pismo, wydanie P90001 i licznik 1/3 |
| Import | UMP: CSV dwóch indywidualnych wpisów oraz dwóch pul/czterech numerów; podgląd z SHA, uzasadnienie i potwierdzenie, zapis zgodny z podglądem |
| Eksport | Pobrane CSV Kalisza: dwa własne wpisy; Konina: jeden własny wpis; 13 pól, brak danych drugiego urzędu |
| Izolacja HTML/PDF | Konin: sześć odmów dostępu do wniosku, wpisu, puli i PDF Kalisza oraz funkcji importu UMP i administratora; UMP również bez dostępu do panelu ADMIN |
| Izolacja API | Natywny klient zalogowany rzeczywistym OTP Konina: obcy wpis GET/PATCH 404, wydanie obcej puli 404, decyzja COUNTY 403; listy własnych wniosków/pul puste |
| Dokumenty | Sześć rzeczywistych PDF wygenerowanych przez produkcję i pobranych po uwierzytelnieniu: trzy wnioski, decyzja I, dwa przydziały pul; sześć stron sprawdzonych wizualnie, SHA pobrań zgodne z archiwum |
| Audyt | Historia operacji, wersja wpisu I po korekcie 6; rzeczywiste logowania przypisane do publicznych adresów klienta, nie prywatnego ingress Render |
| Poczta | OTP do własnych kont oraz powiadomienie o decyzji W/2026/00003 rzeczywiście odebrane w Outlooku; zadanie DECISION_NOTICE ma ACCEPTED |
| Baza i procesy | PG18, aktualne ograniczenia unikalności/check; brak oczekujących migracji; Gunicorn, wygaszanie, integracje i zaproszenia działają |
| Restart | Oficjalny Render CLI uruchomił restart; nowa instancja `gz79c`, health 200 i zgodny pełny SHA, niezmienione dane i SHA sześciu PDF; dysk oraz kopia zachowane |

Stan końcowy prób: trzy wnioski, trzy indywidualne wpisy, cztery pule,
dziesięć slotów, dwa wydania z pul, sześć pism, cztery własne konta.
Sprzedaż `P9DYN01` nie zwolniła numeru. Model po korekcie:
`TEST MODEL PO KOREKCIE`.

Scenariusze współbieżnych rezerwacji, kolizji pul, wygaśnięcia i alertu ≥80%
mają wcześniejsze natywne dowody PG/Chrome oraz aktualny zestaw hosted CI;
nie wywoływano sztucznie wygaśnięcia produkcyjnych wniosków ani obciążenia
wszystkich urzędów. Szczegóły: [odbiór bazy](ODBIOR-BAZY-I-AKTUALIZACJI.md),
[rezerwacje](REZERWACJE-I-ODMOWA.md), [trzy moduły](ODBIOR-TRZECH-MODULOW.md).

## Kopia i odtworzenie

Na żywej bazie wykonano `backup_registry` klientem PG18.6. Kopia:
`/var/data/backups/acceptance-populated-20261003.zip`.
SHA-256 dumpu PostgreSQL w manifeście:
`4123440260d6092133cc24edc8c3c3af03d1adc6d847f55e2821f154babcf98c`.

`restore_registry` odtworzył nową, odrębną bazę
`dyna_acceptance_restore_20261003_populated`; produkcji nie nadpisano.
Manifest `verified=true`, porównane liczby rekordów i migracje, zweryfikowane
PDF. Odtworzona kopia unieważniła dwie sesje oraz dostępne kody; zadania
wymagające uzgodnienia z operatorem są wstrzymywane według procedury.
Manifest: `/var/data/restore-proof-populated-20261003/restore-manifest.json`.
Ta baza nie służy aplikacji ani workerom. Przetrwała też wcześniejsza kopia
początkowa. Restart potwierdził obecność nowej kopii i manifestu.

Próba na dysku tej samej usługi potwierdza odtworzenie, ale nie zastępuje
regularnej szyfrowanej kopii poza awariową domeną hostingu. Dla urzędu należy
uruchomić harmonogram, przechowywanie zewnętrzne, monitoring oraz okresowy
restore opisane w [BACKUP-POSTGRESQL.md](BACKUP-POSTGRESQL.md).

## Integracje: co faktycznie potwierdzono

| Integracja | Kod / lokalne próby | Rzeczywista usługa / instancja urzędu | Dokładny następny krok |
|---|---|---|---|
| Microsoft poczta | Backend Graph MIME i SMTP/TLS, ograniczenia konfiguracji, trwałe zadania | Graph i odbiór OTP/powiadomienia potwierdzone na własnym tenant użytkownika; nie na skrzynce urzędu | Dla instalacji urzędu wybrać jego SMTP lub odrębną aplikację/RBAC i wykonać odbiór wiadomości; [RENDER.md](RENDER.md) |
| EZD RP | Konektor rzeczywistego API, dokument/metadane, powiązanie spraw, RPW i link; lokalne testy kontraktu | Pełny scenariusz z API operatora i interfejsem urzędu niewykonany | Potwierdzić EZD urzędu, uzyskać testową instancję/klucz i zakres; przygotowane zgłoszenie [DOSTEP-EZD-RP.md](DOSTEP-EZD-RP.md); wykonać [WERYFIKACJA-EZD.md](WERYFIKACJA-EZD.md) oraz wpływ/link [WPLYWY-EZD.md](WPLYWY-EZD.md) |
| e-Doręczenia | JWT/certyfikat, SE wyszukiwanie, UA wysyłka/status/dowody; trwała kolejka i testy MockTransport | Pełny scenariusz operatora niewykonany; brak uprawnionego ADE i kluczy INT | Zatwierdzić i złożyć przygotowany wniosek dostępu, uzyskać ADE/INT/certyfikat: [DOSTEP-E-DORECZENIA.md](DOSTEP-E-DORECZENIA.md); wykonać [WERYFIKACJA-E-DORECZENIA.md](WERYFIKACJA-E-DORECZENIA.md) |
| Podpis dokumentów | PAdES DEMO, import/oryginał/weryfikacja, testy zmian i współbieżności | Nie potwierdzono podpisu kwalifikowanego ani profilu urzędu | Wybrać uprawniony certyfikat/profil i zaufanie urzędu, odebrać według [PODPISY.md](PODPISY.md) i [WERYFIKACJA-PODPISOW.md](WERYFIKACJA-PODPISOW.md) |

Nie wysłano zgłoszeń wymagających reprezentowania urzędu. Jawna
implementacja/test kontraktu nie jest dowodem działającego API operatora.
Brak tych dostępów nie został zastąpiony fikcyjną wysyłką.

## Pozostały odbiór urzędowy

- Pełny WCAG 2.1 AA niepotwierdzony: rzeczywisty odczyt komunikatów przez
  VoiceOver dla stanów CAPTCHA pozostaje otwarty B05; podstawowy formularz
  ma już rzeczywisty lokalny dowód [P1–P3](ODBIOR-CZYTNIKA-20261003.md). Lokalne klawiatura, kontrast, 400%,
  responsywność i CAPTCHA mają zapisane próby; [WCAG-PUBLICZNY.md](WCAG-PUBLICZNY.md)
  i [ODBIOR-CAPTCHA.md](ODBIOR-CAPTCHA.md). Użytkownik zezwolił na publikację
  mimo tego braku. PDF/UA i fizyczna drukarka również nie były odebrane.
- Docelowy Linux/Nginx/systemd/TLS, rozdzielenie ról bazy, kopie zewnętrzne,
  monitoring, HA i test skali wymagają infrastruktury urzędu;
  [instrukcja instalacji](WDROZENIE-URZEDOWE.md).
- Reguły numeracji zweryfikowano w zapisanych oficjalnych źródłach;
  [NUMERACJA-PRZEPISY.md](NUMERACJA-PRZEPISY.md) i [DECYZJE.md](DECYZJE.md)
  wskazują rozbieżności/uzgodnienia. W szczególności kategorię III i
  rzeczywiste wykazy historyczne musi potwierdzić urząd.
- Przed sprzedażą/pilotem urząd zatwierdza szablony, kontakty/domeny,
  politykę retencji, upoważnienia i mapowanie importu rzeczywistych danych.

## Dowody i granice przekazania

Prywatne pliki pozostają w lokalnym `evidence/private/`, poza Git:
`render-populated-runtime-proof.json`, `render-authenticated-api-acceptance.json`,
`render-konin-isolation-proof.json`, eksporty obu urzędów,
`render-pdf-qa/render-proof.json`, `render-decision-notice-received.json`,
`render-populated-backup-restore.json`, `render-restart-persistence-proof.json`.
Zrzuty Chrome dokumentują rzeczywiste ekrany, a hashe i JSON opisują
zakres techniczny. Sekrety/OTP i bazy nie są publikowane.

Po wydaniu tego raportu końcowa rewizja dokumentacji jest ponownie
porównywana z health, danymi i dokumentami. Właściwy pełny SHA tego wydania
oraz wynik jego CI są przekazywane w końcowym handoff, bez dopisywania
commita do jego własnej treści. Procedura kolejnych wdrożeń: [RENDER.md](RENDER.md).
