# Odbiór lokalny Dyna Rejestr Tablic

Stan przeglądu: 03.10.2026. Uruchomiona lokalna rewizja:
`855358b7ab48059ff03d711c7d61b7eb4dd78e6c`. Późniejszy commit `0317d47`
dodaje pocztę Microsoft Graph; przygotowane CI i profil Render: `7fcd58e`.
64 wybrane testy poczty/profilu OK (2 SKIP PostgreSQL), ruch Graph symulowany.
Utworzono rzeczywistą odrębną skrzynkę, lecz aplikacja/certyfikat i Mail.Send
nie są jeszcze skonfigurowane. `RENDER.md` opisuje aktualne polecenie
publikacji użytkownika: etap Render został zatwierdzony mimo otwartego B05.
Prywatność repozytorium i akceptacja zasad Microsoft oczekują odpowiedzi.
Rewizję uruchomionego serwera podaje `/api/health/`; późniejszy commit
raportu i dowodów nie zmienia kodu aplikacji.
**Cel nie jest jeszcze zakończony: pełna dostępność publiczna pozostaje
niepotwierdzona.** Raport rozróżnia wykonane scenariusze, implementację
konektorów i zależności od rzeczywistego środowiska urzędu.

## Uruchomiona aplikacja i konta

Adres: <http://127.0.0.1:8765/>. Konto obywatela nie jest wymagane.

| Konto fikcyjne | Dostęp |
|---|---|
| `admin@example.invalid` | A0: urzędy, konta, szablony, diagnostyka i ograniczony audyt |
| `ump@example.invalid` | A3: decyzje, ewidencja województwa, przydziały i korekty |
| `gniezno@example.invalid` | A2: dane i operacje własnego urzędu |
| `pila@example.invalid` | A2: drugi urząd do sprawdzenia izolacji |

Logowanie: wpisz e-mail, zamów kod i odczytaj lokalną wiadomość:

```sh
.venv/bin/python manage.py local_mail ump@example.invalid
```

Nie ma stałego hasła ani kodu w raporcie. Kod jest jednorazowy i ważny
10 minut. Instrukcja instalacji oraz uruchomienia bez Dockera: `../README.md`.
Dane SQLite i pliki prywatne znajdują się w `var/`; restart nie zeruje danych.

## Ocena wymagań celu i specyfikacji

„Lokalny dowód” oznacza wykonanie opisanych scenariuszy na danych fikcyjnych.
Nie oznacza testu wszystkich możliwych danych ani środowiska urzędu.
„Zależność” wskazuje implementację z lokalnymi testami oraz dokładnie
opisany, niewykonany test zewnętrzny. „Otwarte” oznacza niezamknięty lokalny
odbiór. Każdy dowód zachowuje własną datę, rewizję i granice.

| ID / źródło | Wymaganie | Ocena i dowód |
|---|---|---|
| Z01 · cel 1, spec. 1 | Jedna instancja Wielkopolski, jeden UMP i 34 urzędy | Lokalny dowód: bieżąca baza 1 MAIN, 31 COUNTY, 3 CITY; `KONTA-I-ZAPROSZENIA.md`, `WDROZENIE-URZEDOWE.md`. |
| Z02 · cel 1, spec. 2 | Wielu użytkowników w każdym urzędzie | Lokalny dowód: konta powiązane FK z urzędem, tworzenie przez A0, brak limitu jednego konta; `KONTA-I-ZAPROSZENIA.md`. |
| Z03 · cel 1 | Instalacja na infrastrukturze urzędu, brak wymaganej naszej chmury | Przygotowany profil PostgreSQL/Gunicorn/Nginx/systemd; natywny Gunicorn/PG sprawdzony na macOS. Linux i TLS urzędu: zależność, `WDROZENIE-URZEDOWE.md`. |
| Z04 · cel 1, spec. 1 | Moduły I, II i III | Lokalny dowód trzech procesów Chrome: `ODBIOR-TRZECH-MODULOW.md`. |
| Z05 · cel 1, spec. 2–3 | Serwis publiczny i panele A2/A3/A0 | Lokalny dowód wszystkich ról, administracji i procesów; `ROLE-I-TRASY.md`, `KONTA-I-ZAPROSZENIA.md`, `ODBIOR-TRZECH-MODULOW.md`. |
| F01 · cel 2, spec. 8 | Backend i trwała baza | Django, bieżące migracje 0001–0010; SQLite lokalnie, PostgreSQL w profilu urzędu; `ODBIOR-BAZY-I-AKTUALIZACJI.md`. |
| F02 · cel 2, spec. 4.3/7 | Logowanie e-mail/OTP, bez kont obywateli | Lokalny dowód OTP w Chrome/HTTP; `LOGOWANIE-I-SESJE.md`. Zewnętrzny SMTP: zależność. |
| F03 · cel 2, spec. 2/7 | Konta przez administratora, zaproszenia, domeny i aktywność urzędu | Lokalny dowód A0, trwałe zaproszenia, kontrola całej domeny i istniejących sesji; `KONTA-I-ZAPROSZENIA.md`. |
| F04 · cel 2, spec. 3 | Uprawnienia w API i izolacja office_id | 47 tras, 70 par metoda–trasa, 480 scenariuszy testowych oraz 442 rzeczywiste HTTP; `ROLE-I-TRASY.md`. Kontrola rodzaju wniosku uzupełniona: II/III tylko A2, osiem odmów tworzenia/złożenia bez zapisów i zachowane I UMP; `ROLE-WNIOSKOW-PUL.md`. |
| F05 · spec. 3 | A0 bez decyzji i danych ewidencji, audyt A2 własnych akcji | Lokalny dowód odmów i zakresu audytu; `ROLE-I-TRASY.md`, `AUDYT-I-HISTORIA.md`. Kontrolę wiersza „Wniosek o nową pulę” uzupełnia `ROLE-WNIOSKOW-PUL.md`; sama wcześniejsza macierz tras nie wykryła różnicy między I i II/III. |
| F06 · spec. 4.1/9 | Wspólna walidacja numeru i unikalność pełnego numeru | Wspólna walidacja, częściowy unikalny indeks aktywnych numerów; testy SQLite/PG. Rozbieżności regulacyjne jawne w `NUMERACJA-PRZEPISY.md` i `DECYZJE.md`. |
| F07 · cel 2, spec. 4.2 | Sprawdzenie wybranej cyfry lub wszystkich 0–9 | Lokalny HTML/API i Chrome; `REZERWACJE-W-SPRAWDZARCE.md`, `SUGESTIE-WYROZNIKOW.md`. |
| F08 · spec. 4.2 | Wynik publiczny tylko dostępny/niedostępny, bez właściciela | Lokalny dowód po zbyciu i zwolnieniu oraz macierz ról; `ODBIOR-TRZECH-MODULOW.md`, `ROLE-I-TRASY.md`. |
| F09 · spec. 4.2 | Sugestie innych cyfr, skrócenia, wydłużenia i podmiany, wyłącznie wolne | Poprawione generowanie, wykluczenie wyników i zajętości; `SUGESTIE-WYROZNIKOW.md`. Niepoprawne sześcioliterowe przykłady specyfikacji nie znoszą reguły 3–5 znaków. |
| F10 · spec. 4.2 | Wynik informacyjny, instrukcja urzędu, bez rezerwacji | Lokalny dowód i porównanie tabel po zapytaniu; `SUGESTIE-WYROZNIKOW.md`, `ODBIOR-TRZECH-MODULOW.md`. |
| F11 · spec. 4.3 | A2 widzi własne „zarezerwowany — wniosek w toku” | Lokalny dowód dwóch powiatów, UMP i anonimowego użytkownika; `REZERWACJE-W-SPRAWDZARCE.md`. |
| F12 · cel 2, spec. 4.3 | Wniosek z właścicielem, pojazdem jeśli znany i znakiem sprawy | Lokalny pełny proces I w Chrome i ścisła walidacja API; `ODBIOR-TRZECH-MODULOW.md`, `API-OPERACJE.md`. |
| F13 · cel 2, spec. 4.3/9 | Atomowa rezerwacja 14 dni i kolizja dwóch urzędów | Lokalny Chrome z terminem oraz rzeczywiste równoległe transakcje PG; `ODBIOR-TRZECH-MODULOW.md`, `ODBIOR-BAZY-I-AKTUALIZACJI.md`. |
| F14 · spec. 4.3/4.5 | Złożenie i lista własnych wniosków | Lokalny Chrome/HTTP; DRAFT→SENT, historia numeru i wniosku; `ODBIOR-TRZECH-MODULOW.md`, `API-OPERACJE.md`. |
| F15 · cel 2, spec. 4.4 | Weryfikacja UMP, akceptacja i odmowa z powodem | Lokalny dowód zgody i odmowy, zwolnienia po odmowie; `ODBIOR-TRZECH-MODULOW.md`, `REZERWACJE-I-ODMOWA.md`. |
| F16 · spec. 4.4/8 | Ewidencja numer→właściciel→pismo→data | Lokalny dowód przydziału, archiwum pism i kart; `ODBIOR-TRZECH-MODULOW.md`, `PISMA-PDF.md`. |
| F17 · cel 2, spec. 4.4 | Pojazd, rejestracja i wydanie | Lokalny Chrome i API, obowiązkowy VIN/data przy wydaniu; `ODBIOR-TRZECH-MODULOW.md`, `API-OPERACJE.md`. |
| F18 · cel 2, spec. 4.4/4.5 | Zbycie, nabywca i brak automatycznego zwolnienia | Lokalny Chrome SOLD i publiczna niedostępność; `ODBIOR-TRZECH-MODULOW.md`. |
| F19 · cel 2, spec. 4.5 | Wycofanie i wygasanie rezerwacji | Lokalny Chrome, natywny watcher bez ruchu WWW, test dwóch workerów PG; `REZERWACJE-I-ODMOWA.md`. |
| F20 · cel 2 | Przedłużenie rezerwacji przez UMP | Lokalny Chrome, uzasadnienie i przed/po terminu; `REZERWACJE-I-ODMOWA.md`. |
| F21 · cel 2, spec. 4.6 | Korekty UMP z powodem i historią wszystkich zmienionych pól | Lokalny Chrome, ścisły PATCH, ochrona wersji i niezmienny numer; `API-KOREKTY.md`, `AUDYT-I-HISTORIA.md`. |
| F22 · spec. 4.6 | A2 tylko własny pojazd/zbycie, zmiana urzędu zachowuje historię | Lokalny dowód i testy przekazania; `WERYFIKACJA-PRZEKAZANIA.md`, `CZYNNOSCI-WPISU.md`. |
| F23 · cel 2, spec. 4.6 | Zwolnienie tylko UMP, powód, aktywny wniosek i kolizja przywrócenia | Lokalny przebieg zwolnienia i testy rdzenia/operacji; `WERYFIKACJA-PROCESOW.md`, `API-KOREKTY.md`. |
| F24 · cel 2, spec. 5 | Pula II bezpośrednio lub po wniosku, zakres/lista, termin, pismo | Lokalny Chrome/HTTP i import wykazów; `ODBIOR-TRZECH-MODULOW.md`, `IMPORT-PUL.md`, `API-OPERACJE.md`. |
| F25 · cel 2, spec. 5 | Brak nakładania pul i ponownego wydania numeru, również współbieżnie | Unikalne sloty i transakcje, rzeczywisty PG, kolizja bez częściowego zapisu; `ODBIOR-BAZY-I-AKTUALIZACJI.md`, `KOLEJNOSC-PUL-II.md`. |
| F26 · cel 2, spec. 5 | Rejestrowanie wydania, pozostałe numery, procent i alert ≥80% | Lokalny Chrome 4/5 i alert II, 1/2 III; `ODBIOR-TRZECH-MODULOW.md`. |
| F27 · cel 2, spec. 6 | III zawsze na wniosek, liczba, uzasadnienie, urząd, opcjonalna stacja | Lokalny pełny proces III i walidacja bezpośredniego przydziału; `ODBIOR-TRZECH-MODULOW.md`, `API-OPERACJE.md`. Tworzenie i złożenie wyłącznie A2, także przy starym szkicu UMP: `ROLE-WNIOSKOW-PUL.md`. |
| F28 · cel 2, spec. 6 | Okres III, przydział/odmowa, pismo i e-mail autora | Lokalny proces z okresem, pismem i rzeczywistym plikiem MIME; `POWIADOMIENIA-DECYZJI.md`, `ODBIOR-TRZECH-MODULOW.md`. Odbiór zewnętrznego e-maila: zależność. |
| F29 · cel 2, spec. 4.6 | Wyszukiwanie numeru/właściciela/VIN, filtry urzędu i statusu | Kod filtrowania wspólny dla ewidencji/eksportu; lokalne testy i Chrome list; `PAGINACJA-LIST.md`. |
| F30 · cel 2, spec. 4.6 | Eksport wszystkich filtrowanych wyników CSV | Rzeczywiste pobranie 305 wierszy z ostatniej strony; `PAGINACJA-LIST.md`. |
| F31 · cel 2, spec. 9 | Import Excel/innego systemu, podgląd, mapowanie, kolizje i atomowość | Lokalny XLSX/CSV, 13 pól, arkusze, źródła, replay i PG; `IMPORT-XLSX.md`, `IMPORT-EWIDENCJI.md`, `IMPORT-PUL.md`. Plik urzędu: zależność. |
| F32 · cel 2, spec. 8/9 | Historia i pełny audyt kto/co/kiedy/IP/obiekt/przed/po/powód | Lokalny dowód prezentacji, zakresów i paginacji; uzupełnione IP pism/wznowień/OTP, `AUDYT-I-HISTORIA.md`, `AUDYT-IP.md`. Zdarzenia systemowe bez żądania nie otrzymują wymyślonego IP. |
| B01 · cel 2, spec. 9 | Minimalizacja danych osobowych | Bez PESEL/REGON, własny zakres A2, A3 województwo, A0 bez biznesowych wartości; `RETENCJA-DANYCH.md`, `ROLE-I-TRASY.md`. |
| B02 · cel 2, spec. 7/9 | Ochrona sesji, OTP, domeny, blokada prób i CSRF | Lokalny OTP, wygasanie/ostrzeżenie, przedłużenie, stale formularze i odmowy; `LOGOWANIE-I-SESJE.md`, `KONTA-I-ZAPROSZENIA.md`. |
| B03 · cel 2/3, spec. 9 | Sekrety poza Git, uprawnienia plików, HTTPS | Chronione profile/klucze, przypięte zależności i profil HTTPS; `ZALEZNOSCI.md`, `WDROZENIE-URZEDOWE.md`. Rzeczywisty certyfikat/Nginx: zależność. |
| B04 · cel 2, spec. 4.2/9 | Rate-limit i CAPTCHA po progu | Lokalny dowód: trzy zużyte wyzwania, naturalne wygaśnięcie, klawiatura, anulowanie oraz rzeczywisty błąd i ponowienie w Chrome; `ODBIOR-CAPTCHA.md`, `OCHRONA-PUBLICZNA.md`. |
| B05 · cel 2, spec. 9 | WCAG 2.1 AA serwisu publicznego | **Otwarte**: macierz wszystkich 50 kryteriów i wykonane automaty/ręczne próby w `WCAG-PUBLICZNY.md`; stany CAPTCHA uzupełnione w `ODBIOR-CAPTCHA.md`; rzeczywiste ogłoszenia czytnika niepotwierdzone. |
| B06 · spec. 9/10 | Retencja do ustalenia | Inwentaryzacja 19 klas, podgląd i opcjonalne porządkowanie techniczne; biznesowa polityka: decyzja urzędu, `RETENCJA-DANYCH.md`. |
| D01 · cel 3, spec. 4/7 | Generowanie i archiwizacja rzeczywistych PDF | Sześć ostatnich PDF/stron obejrzanych, wcześniejsze długie próbki, hashe i archiwum; `ODBIOR-TRZECH-MODULOW.md`, `PISMA-PDF.md`. |
| D02 · cel 3, spec. 4/7 | Pobranie i druk | Dwa pobrania identyczne z archiwum oraz natywny podgląd druku jednej strony; `ODBIOR-TRZECH-MODULOW.md`, `PISMA-PDF.md`. Drukarka fizyczna nie była testowana. |
| D03 · cel 3, spec. 7 | Edytowalne szablony i zmienne | Lokalna walidacja, nowe PDF, aktualizacja tylko pierwotnych wzorów; `PISMA-PDF.md`. Treść urzędowa wymaga zatwierdzenia. |
| D04 · cel 3, spec. 8 | Numeracja i powiązanie pisma ze sprawą/historią | Liczniki roczne per urząd, UUID, QR, link, rollback, PG i zachowane stare dokumenty; `NUMERACJA.md`, `PISMA-PDF.md`. |
| I01 · cel 3, spec. 7 | Konektor EZD RP, dokument i metadane, powiązanie spraw | Kod i lokalne testy kontraktu; rzeczywiste API: zależność, `EZD-RP.md`, `DOSTEP-EZD-RP.md`. |
| I02 · cel 3, spec. 4.4/7 | EZD→aplikacja, wpływ i link do konkretnego wniosku po logowaniu | Kod RPW/archiwum/linku i lokalne testy; rzeczywisty wpływ i kliknięcie w EZD: zależność, `WPLYWY-EZD.md`. |
| I03 · cel 3 | e-Doręczenia: uwierzytelnianie i wyszukiwanie ADE | Kod JWT i SE API, lokalne testy; INT/ADE/certyfikat: zależność, `E-DORECZENIA.md`, `DOSTEP-E-DORECZENIA.md`. |
| I04 · cel 3, spec. 7 | e-Doręczenia: wysyłka, status, dowody nadania/odbioru | Kod UA, trwała kolejka i archiwum dowodów, testy MockTransport; rzeczywisty scenariusz operatora: zależność, `WERYFIKACJA-E-DORECZENIA.md`. |
| I05 · cel 3, spec. 6/7 | Poczta: OTP, zaproszenia, pisma i powiadomienia | Kod SMTP oraz rzeczywisty lokalny MIME; test skrzynki urzędu: zależność, `KONTA-I-ZAPROSZENIA.md`, `POWIADOMIENIA-DECYZJI.md`. |
| I06 · cel 3, spec. 7 | Podpisywanie i weryfikacja dokumentu | Rzeczywisty PAdES DEMO, import podpisu, oryginał, CA/odwołanie i testy zmian; profil urzędu/kwalifikacja: zależność, `PODPISY.md`, `WERYFIKACJA-PODPISOW.md`. |
| I07 · cel 3 | Błędy, retry, deduplikacja i niepewne wysyłki | Lokalny kod/testy, trwałe stany REVIEW_REQUIRED, wznowienie bez drugiego POST, PG; `WZNOWIENIE-E-DORECZEN.md`, `WSPOLBIEZNOSC-PODPISU.md`, `EZD-RP.md`. |
| I08 · cel 3 | Historia i diagnostyka operacji zewnętrznych | Lokalny panel, audyt i pełne listy wyników; `PAGINACJA-LIST.md`, `AUDYT-IP.md`. Fixture operatora nie jest dowodem doręczenia. |
| I09 · cel 3 | Oficjalna dokumentacja i procedura dostępów testowych | Kontrakty, źródła i przygotowane treści zgłoszeń; `DOSTEP-EZD-RP.md`, `DOSTEP-E-DORECZENIA.md`. Zgłoszeń nie wysłano. |
| I10 · cel 3/5 | Oddzielny stan kodu, testów lokalnych, API i instancji urzędu | Rozdzielone w poniższej tabeli; żadna integracja zewnętrzna nie jest oznaczona jako zweryfikowana. |
| P01 · cel 4 | Dobór technologii, fikcyjne dane, bez Dockera | Django/host-native, oddzielne kopie testowe; `README.md`, `DECYZJE.md`. |
| P02 · cel 4 | Weryfikacja numeracji w aktualnych oficjalnych źródłach | Zapisane źródła ELI i ich hashe z 03.10.2026, alfabet/P/M/pojemności; `NUMERACJA-PRZEPISY.md`, `POJEMNOSCI-PUL.md`. Nie jest to pełna opinia prawna. |
| P03 · cel 4, spec. 10 | Założenia, rozbieżności i decyzje urzędu | `DECYZJE.md`: OTP, 14 dni, sprzedaż, III, dane właściciela, numeracja i integracje. Logo/prezentacja/stoisko w pytaniach specyfikacji nie są osobnym modułem tego celu programistycznego. |
| P04 · cel 4 | Zachowanie źródeł i istniejącej pracy | Hashe obu HTML zachowane; główne dane porównane, brak resetu/odrzucenia WIP; bieżący zapis audytu w `../evidence/local-acceptance-audit.json`. |
| O01 · cel 5 | Role i pełny główny przebieg w Chrome | Lokalny I: sprawdzenie→wniosek→rezerwacja→decyzja→pismo→wydanie→zbycie→korekta; II/III i A0/A2 obcy; `ODBIOR-TRZECH-MODULOW.md`. |
| O02 · cel 5 | Testy izolacji, odmów i jednoczesnych przydziałów | Macierz tras/metod i testy PG; `ROLE-I-TRASY.md`, `METODY-HTTP.md`, `ODBIOR-BAZY-I-AKTUALIZACJI.md`. |
| O03 · cel 5 | Testy wygaśnięcia, PDF, importu i eksportu | Konkretne dowody wskazane w F19, F30/F31 i D01/D02; bez zamiany fixture na dowód operatora. |
| O04 · cel 5 | Kopia i rzeczywiste odtworzenie danych | SQLite i PostgreSQL, podpis DEMO, wstrzymana kolejka, sesje oraz migracja PG 0005→0010; `ODBIOR-BAZY-I-AKTUALIZACJI.md`, `BACKUP-POSTGRESQL.md`. |
| O05 · cel 5 | Instrukcje lokalne, instalacja urzędu, konfiguracja integracji i aktualizacja | `README.md`, `WDROZENIE-URZEDOWE.md`, `EZD-RP.md`, `E-DORECZENIA.md`, `PODPISY.md`, `BACKUP-POSTGRESQL.md`. |
| O06 · cel 5 | Adres, konta testowe i raport zgodności | Ten raport, `MACIERZ-ZGODNOSCI.md` i jawne dowody; końcowa deklaracja osiągnięcia celu czeka na zamknięcie B05; B04 ma lokalny dowód. |

To 67 punktów przeglądu. Encje ze szkicu specyfikacji §8 są odwzorowane
w modelach: Office, User, PlateRecord z danymi właściciela/pojazdu,
Request, Letter, Pool/PoolSlot i AuditLog. Nie wymagają osobnych tabel
Owner/Vehicle/PlateHistory, aby zachować wymagane dane i historię.
Weryfikacja 15 wierszy §3 korzysta z macierzy tras i kontroli rodzajów
wniosków, zakresów danych oraz audytu. Są to konkretne lokalne scenariusze;
nie obejmują rzeczywistego operatora e-Doręczeń ani każdej możliwej danej.
Dwie opcjonalne decyzje (administracja UMP i wniosek II)
rozstrzyga `DECYZJE.md`. Publiczne WCAG ma osobną macierz 50 kryteriów.

## Stan zależności zewnętrznych

| Zależność | Kod/test lokalny | Prawdziwe API / urząd | Brak i następny krok |
|---|---|---|---|
| EZD RP | Konektor API v2, lokalny transport testowy, RPW, PDF i metadane | Niewykonane | Potwierdzić używany EZD; zatwierdzić zgłoszenie, uzyskać instancję, klucz/SID, JRWA i repozytorium. Scenariusze: `DOSTEP-EZD-RP.md`, `EZD-RP.md`, `WPLYWY-EZD.md`. |
| e-Doręczenia | UA v3/SE v4, JWT, adresy, wysyłka/statusy/dowody, retry | Niewykonane | Zatwierdzone zgłoszenie INT, IP, dwa ADE, nazwa systemu, klucz i certyfikat operatora. Scenariusze: `DOSTEP-E-DORECZENIA.md`, `E-DORECZENIA.md`. |
| SMTP | Konektor, lokalne pliki MIME i testy błędów | Niewykonane | Zatwierdzony serwer, szyfrowanie, nadawca, konto i testowa skrzynka. Wykonać OTP/zaproszenie/pismo/powiadomienie i potwierdzić odbiór, nie samo przyjęcie SMTP. |
| Podpis/pieczęć urzędu | PAdES i import, rzeczywista kryptografia DEMO | Niewykonane | Wybrać profil urządzenia/usługi, certyfikat i zaufanie/odwołanie; wykonać podpis i niezależną walidację. DEMO nie jest podpisem kwalifikowanym. `PODPISY.md`. |
| Infrastruktura urzędu | Profil i natywny Gunicorn/PG na macOS | Niewykonane | Dostęp do serwera Linux, DNS/TLS, kont, SMTP i operatorów. Kontrola usług, proxy/IP, HTTPS, timerów, backupu, odtworzenia i SHA: `WDROZENIE-URZEDOWE.md`. |
| Dane i zasady urzędu | Fikcyjne źródła XLSX/CSV, roboczy słownik/wzory | Niewykonane | Zatwierdzić słownik/TERYT/ADE, mapowanie historycznych danych, treść pism, kategorię III i retencję; `DECYZJE.md`, dokumenty importów/retencji. |

Nie wysłano zgłoszeń w imieniu firmy lub urzędu. Publiczna dokumentacja
nie nadaje uprawnień do wykonania tych scenariuszy.

## Otwarte czynności lokalne i granice wyniku

1. CAPTCHA ma lokalny dowód: `ODBIOR-CAPTCHA.md`. Poprawiono odnośnik
   klawiatury, sprawdzono ważność, zużycie serwerowe, limit i ponowienie.
2. Rzeczywisty odczyt komunikatów pozostaje niepotwierdzony. VoiceOver
   włączono po zgodzie, lecz narzędzie nie udostępniło wyniku mowy.
   Ustawienie przywrócono. AX/aria-live nie dowodzi wypowiedzianego komunikatu.
3. Raport uzupełniono i lokalny serwer działa na wskazanej rewizji.
   Bez zamknięcia B05 nie deklarujemy pełnego AA ani osiągnięcia celu.

Fizyczna drukarka, PDF/UA, testy na innych urządzeniach i formalny odbiór
urzędowy nie są potwierdzone przez Chrome ani generator PDF. Test danych
fikcyjnych i zwykła paginacja nie są pomiarem docelowej wydajności.
Nie sumujemy nakładających się zestawów testów jako liczby unikalnych testów.
Zdrowie serwera nie zastępuje odbioru funkcjonalnego.

Repozytorium lokalne nie ma remote, CI ani istniejącej ścieżki deploymentu.
Nie powstał PR ani wdrożenie produkcyjne. Zapisany raport jest materiałem
odbioru lokalnego i przygotowania dalszej instalacji, nie certyfikatem gotowości
do eksploatacji w urzędzie.
