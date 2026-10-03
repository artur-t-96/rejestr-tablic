# Macierz zgodności i pozostały odbiór

> Raport historyczny lokalnych prób. Bieżący stan wdrożenia, rzeczywista
> poczta i wyniki produkcji: [ODBIOR-RENDER-20261003.md](ODBIOR-RENDER-20261003.md).
> Dawne blokady GitHub/Render/Microsoft opisują stan w chwili tej próby.

Stan przeglądu: 03.10.2026, odbiór trzech procesów na `4321275`
(`ODBIOR-TRZECH-MODULOW.md`), kod aplikacji identyczny z `dc3d6df`.
Odbiór baz: `ODBIOR-BAZY-I-AKTUALIZACJI.md`; retencja techniczna:
`RETENCJA-DANYCH.md`; walidacja operacji API: `API-OPERACJE.md`;
paginacja: `PAGINACJA-LIST.md`; walidacja korekt: `API-KOREKTY.md`.
Kontrakt metod wszystkich tras: `METODY-HTTP.md` (zmiana kodu po 4321275).
Role na 3c53b4f: `ROLE-I-TRASY.md` (70 par, 480 scenariuszy testowych, 442 HTTP).
Nowa zmiana po 45ab47d: dodatkowy stan własnej rezerwacji w HTML/API;
`REZERWACJE-W-SPRAWDZARCE.md`, 52 PASS/1 SKIP, 10 HTTP i cztery konteksty Chrome.
Zmiana po 2f302bd: przeplatane wolne sugestie różnych zmian tekstu;
`SUGESTIE-WYROZNIKOW.md`, 39 PASS/1 SKIP, osiem HTTP i dwa przypadki Chrome.
Zmiana po 98bb02b: IP automatycznych pism i operacji użytkownika,
`AUDYT-IP.md`, 109 PASS i 14 rzeczywistych POST dokumentów.
Zmiana po 9fce1d8: II/III tworzy i składa tylko A2; I UMP oraz decyzje
i przydziały zachowane. `ROLE-WNIOSKOW-PUL.md`: 54 PASS, 17 HTTP i Chrome.
Źródła zakresu: zapisany cel oraz
`Specyfikacja_flow_tablice.html`; demo jest odniesieniem interfejsu.
**Cały cel pozostaje aktywny.** Macierz nie jest deklaracją gotowości do
produkcji ani formalnej zgodności prawnej/dostępności.
Przegląd celu i §1–10, 67 punktów wraz z zależnościami:
`RAPORT-ODBIORU-LOKALNEGO.md`.

„Dowód lokalny” oznacza zapisany wynik wskazanego scenariusza na danych
fikcyjnych. Nie oznacza ponownego przetestowania całego wymagania w aktualnym
commicie. „Częściowo” wskazuje granicę dowodu lub brak odbioru. Dokumenty
poniżej opisują konkretne testy, ich środowisko i pliki dowodowe; wcześniejsze
raporty zachowują swoje rewizje i daty. Inwentaryzację ich plików z hashami
zapisano w `evidence/compliance-evidence-inventory.json`.

| Wymaganie celu/specyfikacji | Stan i dowód | Pozostała weryfikacja |
|---|---|---|
| Jedna instancja Wielkopolski, UMP + 34 urzędy, wielu użytkowników | Dowód lokalny: słownik 35 urzędów, relacja użytkownik–urząd; `KONTA-I-ZAPROSZENIA.md`, `WDROZENIE-URZEDOWE.md` | Urząd potwierdza słownik, TERYT i kontakty; formalny odbiór skali |
| A0 administracja bez decyzji/danych ewidencji | Dowód lokalny: testy i Chrome; aktualnie panel A0 i sześć odmów GET 403, `ODBIOR-TRZECH-MODULOW.md` | Macierz dostępu wszystkich tras obejmuje A0; pozytywne zarządzanie i zaproszenia opisuje `KONTA-I-ZAPROSZENIA.md` |
| A1 dostępność bez danych właściciela, sugestie tylko wolnych | Dowód lokalny: wolny → zbyty niedostępny → zwolniony dostępny, `ODBIOR-TRZECH-MODULOW.md`; różnorodne warianty, walidacja i wykluczenie zajętości w `SUGESTIE-WYROZNIKOW.md` | Rzeczywiste zakończenie, wygaśnięcie i błąd/ponowienie lokalnie potwierdzone w `ODBIOR-CAPTCHA.md`; odczyt czytnika pozostaje otwarty |
| A2 własny urząd, A3 całe województwo, ochrona API | Dowód lokalny: `WERYFIKACJA-PRZEKAZANIA.md`, `API-KOREKTY.md`, `API-OPERACJE.md`; pełna kontrola niedozwolonych metod 47 tras, `METODY-HTTP.md`, oraz macierz ról `ROLE-I-TRASY.md` | Utrzymać macierz `ROLE-I-TRASY.md` przy nowych trasach/zmianach; zapisów operatora nie potwierdzono |
| A2 sprawdzarka: zarezerwowany — wniosek w toku | Dodany stan własnego urzędu, A3 całe województwo; API/HTML i Chrome z dwoma powiatami/UMP/publicznie, `REZERWACJE-W-SPRAWDZARCE.md` | Publiczne i obce dane ograniczone do zajętości; bez nowego odbioru wszystkich przepływów |
| Reguły tablic indywidualnych, wspólna walidacja | Dowód lokalny i zapisane oficjalne źródła: `NUMERACJA-PRZEPISY.md` | Potwierdzenie przez urząd decyzji biznesowych opisanych w `DECYZJE.md` |
| Sprawdzenie → wniosek → rezerwacja 14 dni | Aktualny Chrome na 4321275, termin 03.10→17.10 widoczny w karcie, `ODBIOR-TRZECH-MODULOW.md` | Utrzymać dowód przy późniejszych zmianach kodu procesu |
| Wysłanie, akceptacja, odmowa z powodem, dokument odpowiedzi | Dowód lokalny: `WERYFIKACJA-PROCESOW.md`, `REZERWACJE-I-ODMOWA.md` | Rzeczywista korespondencja operatora zależna od dostępów |
| Wycofanie, automatyczne wygaśnięcie, przedłużenie UMP | Dowód lokalny: worker, atomowe audyty i Chrome; `REZERWACJE-I-ODMOWA.md` | Urzędowy timer i alerty operacyjne |
| Rejestracja pojazdu, wydanie, sprzedaż bez zwolnienia | Aktualny pełny przebieg Chrome na 4321275 i historia SQLite, `ODBIOR-TRZECH-MODULOW.md` | Pozostałe negatywne operacje w macierzy endpointów |
| Korekty UMP, powód, przed/po, niezmienny numer | Dowód lokalny: `AUDYT-I-HISTORIA.md`; nowa regresja i HTTP w `API-KOREKTY.md` | Pełna aktualna kontrola typów wejściowych pozostałych operacji API |
| Zwolnienie UMP, blokada aktywnego wniosku i kolizji reaktywacji | Dowód lokalny: testy rdzenia i `WERYFIKACJA-PROCESOW.md` | Końcowy aktualny odbiór wariantów procesu |
| Moduł II: zakresy, przydział, pismo, wydanie | Aktualny Chrome na 4321275: wniosek, kolizja bez zapisu, przydział pięciu i cztery wydania; `ODBIOR-TRZECH-MODULOW.md` | Pozostałe negatywne operacje w macierzy endpointów |
| Kolejność i pojemność pul II, P/M | Dowód lokalny, PostgreSQL i Chrome: `POJEMNOSCI-PUL.md`, `KOLEJNOSC-PUL-II.md` | Urzędowa kwalifikacja historycznych importów |
| Moduł III: obowiązkowy wniosek, urząd/stacja, okres | Aktualny Chrome na 4321275: wniosek, przydział ze stacją/okresem, jedno wydanie, `ODBIOR-TRZECH-MODULOW.md`; testy ważności | Końcowy aktualny odbiór granicznych dat |
| Liczniki pul i alert ≥80% | Aktualny Chrome: 4/5 i alert 80% dla II, 1/2 dla III; `ODBIOR-TRZECH-MODULOW.md` | Odbiór tabel przy większej liczbie urzędów/pul |
| Wyszukiwanie, filtry i dostęp do całej ewidencji | Dowód lokalny: wszystkie pozycje, filtry i paginacja; `PAGINACJA-LIST.md` | Końcowy aktualny odbiór większej skali i nowych zapisów w czasie nawigacji |
| Historia i audyt: kto, kiedy, obiekt, IP, powód, przed/po | Dowód lokalny: `AUDYT-I-HISTORIA.md`; paginacja historii/dziennika; uzupełnione IP pism i ręcznych operacji w `AUDYT-IP.md` | Kontrola kompletności wszystkich operacji; czytnik publiczny w osobnym zakresie WCAG |
| Import Excel/innego systemu, podgląd, kolizje, źródła | Dowód lokalny: `IMPORT-XLSX.md`, `IMPORT-EWIDENCJI.md`, `IMPORT-PUL.md` | Rzeczywisty plik urzędu i uzgodnienie mapowania danych |
| Eksport filtrowanych wyników CSV | Dowód lokalny: Chrome, 305 wpisów z ostatniej strony; `PAGINACJA-LIST.md` | Końcowy odbiór wszystkich wariantów filtrów i większej skali |
| PDF, szablony, numeracja, QR, archiwum i druk | Aktualnie sześć rzeczywistych PDF/sześć obejrzanych stron i dwa zgodne pobrania Chrome, `ODBIOR-TRZECH-MODULOW.md`; wcześniejsze próbki `PISMA-PDF.md` | Urząd zatwierdza treść; PDF/UA i fizyczny wydruk niepotwierdzone |
| EZD RP: API, przekazywanie dokumentów/metadanych, sprawy | Częściowo: konektor i lokalne testy, `EZD-RP.md`, `WERYFIKACJA-EZD.md` | Dostęp testowy operatora i potwierdzenie systemu urzędu; `DOSTEP-EZD-RP.md` |
| EZD → aplikacja: wpływ, identyfikacja i głęboki link | Częściowo: implementacja RPW i testy lokalne, `WPLYWY-EZD.md` | Pełny rzeczywisty wpływ i kliknięcie w interfejsie EZD |
| e-Doręczenia: auth, adresy, wysyłka, status, dowody | Częściowo: rzeczywisty konektor, testy lokalne, `E-DORECZENIA.md`, `WZNOWIENIE-E-DORECZEN.md` | Uprawnienia/ADE/klucze środowiska, pełny test operatora; `DOSTEP-E-DORECZENIA.md` |
| Podpis/pieczęć elektroniczna | Częściowo: PAdES i sprawdzony podpis DEMO, `PODPISY.md`, `WERYFIKACJA-PODPISOW.md` | Rzeczywisty profil/certyfikat urzędu; kwalifikacja i znaczniki czasu niepotwierdzone |
| Zaproszenia, logowanie, powiadomienia e-mail | Dowód lokalny MIME/OTP: `KONTA-I-ZAPROSZENIA.md`, `POWIADOMIENIA-DECYZJI.md` | Backend Graph przygotowany (0317d47), 62 PASS/2 SKIP; utworzona dedykowana skrzynka MS. Rejestracja aplikacji, ograniczony grant oraz rzeczywisty OTP pozostają do wykonania; `RENDER.md` |
| Retry, deduplikacja, niepewny wynik wysyłki i diagnostyka | Częściowo: trwałe kolejki/testy/uzgodnienie, dokumenty integracji; wszystkie wyniki dostępne przez paginację, `PAGINACJA-LIST.md` | Rzeczywiste awarie operatora i odbiór diagnostyki przez urząd |
| Atomowe rezerwacje, unikalność numeru, brak kolizji pul | Dowody lokalne SQLite/PostgreSQL; aktualne wybrane scenariusze PG na dc3d6df, `ODBIOR-BAZY-I-AKTUALIZACJI.md`; szczegóły kolejności: `KOLEJNOSC-PUL-II.md` | Docelowy profil bazy, skala i odbiór infrastruktury urzędu |
| OTP, domeny, blokady, sesja, CSRF, sekrety | Dowód lokalny: `LOGOWANIE-I-SESJE.md`, `KONTA-I-ZAPROSZENIA.md`, testy auth | Końcowy aktualny przegląd wszystkich tras i konfiguracji HTTPS |
| Rate-limit i CAPTCHA publiczna | Dowód lokalny: zużycie trzech wyzwań, naturalne wygaśnięcie, klawiatura i rzeczywiste 429/ponowienie, `ODBIOR-CAPTCHA.md` | Odbiór nowego środowiska Render; B04 lokalnie potwierdzone |
| WCAG 2.1 AA serwisu publicznego | Częściowo: konkretne testy HTML, klawiatury, 400% i kontrastu; `DOSTEPNOSC.md`, `WCAG-PUBLICZNY.md` (macierz 50 kryteriów) | **Rzeczywiste komunikaty czytnika (B05); pełne AA nadal niepotwierdzone** |
| Minimalizacja, izolacja i retencja danych osobowych | Częściowo: scope, minimalne pola, inwentaryzacja 19 klas i opcjonalny cleanup wygasłego OTP/sesji; `RETENCJA-DANYCH.md` | Polityka urzędu i realizacja zatwierdzonych zasad dla spraw, audytu i plików |
| On-premise, PostgreSQL, HTTPS, brak obowiązkowego SaaS | Częściowo: natywny profil i pliki wdrożenia, `WDROZENIE-URZEDOWE.md` | Linux/systemd/Nginx/TLS i zasoby infrastruktury urzędu nie uruchomione |
| Kopie, odtwarzanie i procedura aktualizacji | Aktualna rzeczywista próba obu baz i aktualizacji odtworzonej PG 0005→0010 na dc3d6df, `ODBIOR-BAZY-I-AKTUALIZACJI.md`; procedura: `BACKUP-POSTGRESQL.md` | Urzędowy backup zewnętrzny, alerty i próba aktualizacji docelowego profilu/danych |
| Adres, konta testowe i instrukcja lokalna | `README.md`, `LOGOWANIE-I-SESJE.md`; główna aplikacja port 8765 | Końcowy handoff na finalnej rewizji; bez ujawniania kodów OTP/sekretów |
| Raport zgodności i dokładny stan integracji | Ta macierz oraz raporty integracji | Raport końcowy po usunięciu braków lokalnych i przejściu odbioru |

## Najbliższe prace niezależne od dostępów zewnętrznych

1. Domknąć pozostałe publiczne kryteria dostępności; kontrakt metod i macierz
   ról na obecnych trasach odebrane w `METODY-HTTP.md` i `ROLE-I-TRASY.md`.
   Granice pustych formularzy, zapisów testowych i rzeczywistego HTTP są jawne.
2. Domknięcie publicznego WCAG. Retencja biznesowa według decyzji urzędu;
   inwentaryzacja i techniczne porządkowanie opisane w `RETENCJA-DANYCH.md`.
3. Złożyć końcową dokumentację po zamknięciu lokalnych braków. Trzy główne
   procesy Chrome odebrane na 4321275; późniejsza zmiana metod i pełność
   macierzy ról odebrane na 3c53b4f. Historyczne dowody zachowują zakresy.

Brak dostępów operatora nie blokuje tych prac. Materiały wymagające
reprezentowania urzędu/firmy przygotowane w dokumentach dostępów wymagają
zatwierdzenia użytkownika przed wysłaniem. Nie wykonywano takiego zgłoszenia
w tym etapie.
