# Rejestr realizacji celu

## Bieżący stan — 03.10.2026

Render działa: https://dyna-rejestr-tablic.onrender.com. Prywatny GitHub,
PR #1–#5 scalone, hosted CI zielone. Odbiór czterech ról, trzech modułów,
rzeczywistej poczty Microsoft, PDF, importu/eksportu, izolacji i kopii
na osobnej bazie opisuje [raport Render](ODBIOR-RENDER-20261003.md).
Konfiguracja i droga aktualizacji: [RENDER.md](RENDER.md).

Raport [67 wymagań](RAPORT-ODBIORU-LOKALNEGO.md) zachowuje historyczne
rewizje lokalnych prób; nowy raport uzupełnia ich zakres o produkcję.
[Rzeczywisty odczyt VoiceOver P1–P3](ODBIOR-CZYTNIKA-20261003.md) sprawdzono
lokalnie i dostarczono poprawkę polskiej walidacji. Odczyt stanów CAPTCHA
pozostaje częściowy, więc pełnego WCAG nadal nie potwierdzono.
Nie potwierdzono rzeczywistych API EZD RP,
e-Doręczeń, kwalifikowanego podpisu ani infrastruktury konkretnego urzędu.
Dokładne dostępy i kroki są wskazane w raporcie. Nie zgłaszano się
w imieniu urzędu bez jego upoważnienia.

Po przeglądzie funkcji względem specyfikacji dodano usprawnienia pracy UMP i
urzędów: [USPRAWNIENIA-PRACY-URZEDOW.md](USPRAWNIENIA-PRACY-URZEDOW.md).

Poniżej zachowano chronologię wcześniejszych prac. Sformułowania o
oczekiwaniu na publikację, aplikację Microsoft i CI dotyczą dawnych etapów.

## Dalszy etap zatwierdzony przez użytkownika (03.10)

Po pełnym odbiorze lokalnym użytkownik polecił dodać projekt na swój GitHub
i wdrożyć aplikację przez `https://dashboard.render.com/`.
Kolejność jest warunkiem: najpierw zakończenie implementacji i napraw lokalnie,
następnie publikacja GitHub, następnie Render i sprawdzenie docelowej instancji.
Nie tworzyć repozytorium ani usług w chmurze przed osiągnięciem gotowości lokalnej.
Domyślnie przygotować prywatne repozytorium i przekazywać wyłącznie kod oraz
dokumentację; sekrety, bazy i prywatne dowody pozostają poza Git.
Nie uznawać niezweryfikowanych integracji zewnętrznych za działające.
Render jest dodatkowym celem hostingu; wymaganie instalacji na infrastrukturze
urzędu pozostaje w mocy. Osiągnięcie celu rozszerzonego wymaga również
adresu Render, zgodnej rewizji, kontroli trwałości danych/usług oraz próby
rzeczywistego przepływu w Chrome po wdrożeniu. Na tym etapie publikacji nie wykonano.

## Profil Render przygotowany lokalnie (03.10)

- Blueprint, osobny profil, WhiteNoise, trwały dysk, wspólne WWW/kolejki
  i startup z migracjami przygotowane; nie utworzono zasobów ani GitHub remote.
- Oficjalny JSON Schema PASS; 17/17 skupionych testów PASS; collectstatic
  i składnia PASS. Nowy wheel ma kontrolowany hash i zachowaną licencję;
  wcześniejsze wersje zależności pozostają zachowane.
- `RENDER.md` oddziela lokalne próby od niewykonanej chmury. Wymagane SMTP,
  rzeczywista domena/sekrety i potwierdzone CIDR-y proxy; brak zgadywania IP.
  Urzędowy profil on-prem pozostaje osobny. B05 nadal otwarty.

## Końcowy odbiór CAPTCHA (03.10, kod 772378a)

- Otrzymano zgodę na oczekujące czynności. Trzy dowody rzeczywiście zużyte
  przez serwer, po ogrzaniu licznika bezpośrednio przed POST.
  Naturalne wygaśnięcie, anulowanie wskaźnikiem z dodatnią kontrolą,
  błąd 429 i udane ponowienie sprawdzono w Chrome.
- Poprawiono dostęp Tab do atrybucji i usunięto redundantne logo.
  Space/Tab/Enter, fokus wyniku, kontrast i wąski zweryfikowany widget
  sprawdzone. 17 PASS/1 SKIP PG; składnia JS PASS.
- VoiceOver tymczasowo włączony, ale wynik mowy niedostępny w narzędziu.
  AX i fokus nie są dowodem ogłoszenia. Ustawienia macOS i Chrome przywrócone.
- Wszystkie 27 tabel głównych zachowane; kopie zmieniły tylko stan ochrony.
  `ODBIOR-CAPTCHA.md` i `final-public-acceptance-proof.json` opisują zakres,
  wykluczone niejednoznaczne próby i aktualną rewizję lokalnego serwera.

## Wnioski o pule tylko dla urzędów wnioskujących (03.10)

- Poprawiony wiersz macierzy §3: UMP nie tworzy ani nie składa II/III,
  także ze starego szkicu. I UMP, II/III powiatu, decyzje i bezpośredni
  przydział II zachowane. Formularze i linki odpowiadają uprawnieniu.
- 54/54 testy PASS; 17 rzeczywistych operacji HTTP, w tym osiem odmów
  z identycznymi 27 tabelami. Trzy zapisy w Chrome, siedem obejrzanych
  zrzutów; finalna próba potwierdza brak złożenia szkicu III przez UMP.
- Główna baza, stare audyty i PDF zachowane; bez migracji i Dockera.
  `ROLE-WNIOSKOW-PUL.md` oddziela dwie rewizje prób przeglądarkowych.
  Publiczne CAPTCHA/czytnik oraz końcowy raport pozostają otwarte.

## IP w audycie pism i operacji użytkownika (03.10)

- Przegląd rzeczywistej specyfikacji wykazał brak IP automatycznych pism,
  ręcznych wznowień e-Doręczeń i błędu transportu OTP. Przekazywanie poprawione;
  bez migracji, dopisywania dawnych danych lub zmiany deduplikacji wysyłki.
- 109/109 testów PASS, w tym CSRF, IPv4/IPv6, numeracja, rollback PDF,
  wznowienie bez kolejnej wysyłki i role. Testy operatora korzystają z
  MockTransport; nie są dowodem rzeczywistego API.
- 14 rzeczywistych POST z dwiema sesjami OTP na osobnej kopii SQLite:
  dziesięć pism z IP, zachowane 58 starszych audytów, 12 PDF i 27 tabel
  głównej bazy. Próba HTTP dotyczy dokumentów, nie wznowień operatora.
- `AUDYT-IP.md` opisuje zakres i korektę dwóch dawnych asercji HTML,
  które nie rozróżniały formularza sesji od operacji biznesowej.
  Cel pozostaje aktywny; publiczne CAPTCHA/czytnik wymagają odpowiedzi.

## Różnorodne wolne sugestie (03.10)

- Odtworzone dwa braki: dwunastkę wypełniały inne cyfry i jeden skrócony tekst;
  bez wyboru cyfry powtarzano numery już widoczne w wyniku.
- Pierwsze propozycje przeplatają skrócenie, wydłużenie i podmianę znaku,
  po innych cyfrach wybranego tekstu. Wspólna walidacja i zajętość całego
  województwa, najwyżej 12 wolnych unikalnych numerów, bez powtórzeń wyniku.
- 40 testów: 39 PASS/1 SKIP PostgreSQL. Osiem rzeczywistych HTTP z CSRF,
  Chrome P7KOWA i M0A12; zajęty obcy przydział/zbycie i własna rezerwacja
  nie trafiły do sugestii. Dwa zrzuty obejrzane, fokus wyniku zachowany.
- Tylko licznik zapytań kopii zmieniony; 26 pozostałych i 27 głównych tabel
  zachowane. Bez migracji, operatorów, nowych PG/WCAG/czytnika.
- `SUGESTIE-WYROZNIKOW.md` dokumentuje zakres. Cel nadal aktywny.

## Natywne anulowanie kliknięcia publicznego (03.10)

- Chrome na 18d8829, osobna kopia: naciśnięcie przycisku, przesunięcie poza
  niego i puszczenie nie przesłało formularza; wartość ANNA zachowana,
  wszystkie 27 tabel identyczne, także licznik zapytań.
- Dodatnie kliknięcie zwróciło wynik i fokus; zmieniło tylko licznik zapytań.
  Pozostałe 26 tabel kopii i 27 głównych bez zmian. Zrzuty 140/141 obejrzane.
- Bez zmiany kodu aplikacji, testu dotyku, CAPTCHA lub czytnika.
  `WCAG-PUBLICZNY.md` i `evidence/public-pointer-proof.json` wskazują zakres.
- VoiceOver pozostawiono wyłączony; prośba o zgodę na tymczasowe włączenie
  jest oczekująca. CAPTCHA nadal wymaga potwierdzenia działania.
  Cel pozostaje aktywny.

## Status rezerwacji w sprawdzarce (03.10)

- Uzupełniono wymaganie Flow 2: własny RESERVED/SENT ma komunikat
  „Zarezerwowany – wniosek w toku”. UMP widzi całe województwo;
  A2 tylko dodatkowy stan własnego urzędu. Publicznie i dla A0 bez szczegółów.
- 53 testy: 52 PASS/1 SKIP PostgreSQL. Rzeczywisty HTTP z czterema OTP/CSRF:
  10 odczytów HTML/API w pięciu kontekstach, 17 tabel kopii bez zmian w odczytach.
- Chrome: Gniezno, Piła, UMP i po wylogowaniu wynik publiczny;
  pełny komunikat przy 320 px, fokus wyniku, pięć obejrzanych screenshotów.
- Całość próby zachowała 15 tabel kopii, dane kont poza last_login i istniejący audyt;
  dopisano tylko siedem zdarzeń logowania OTP. Wszystkie 27 tabel głównych
  zachowane. Bez migracji, Dockerów i wywołań operatorów.
- `REZERWACJE-W-SPRAWDZARCE.md` opisuje zakres i granice dowodów.
  Publiczne WCAG i końcowy odbiór celu pozostają otwarte.

## Role wszystkich tras na 3c53b4f (03.10)

- 47 tras/70 dozwolonych par trasa–metoda; 96 przypadków × pięć
  kontekstów = 480 testowych scenariuszy. Istniejące obiekty wszystkich
  modułów, oba kierunki nadawcy, dowody, wpływy i zaproszenia.
- 12/12 testów PASS, w tym maskowanie biznesowych wartości audytu A0.
  Pozytywne zapisy odizolowane rollbackiem; odrębne granice walidacji form.
- Rzeczywisty OTP/CSRF: 442 HTTP, 276 odmów zachowujących 17 tabel;
  obcy powiat bez obcych danych. 38 dodatnich zapisów nie powtarzano w HTTP.
- Wszystkie 27 tabel głównej bazy zachowane. Bez nowego kodu aplikacji,
  migracji, PG i wywołań operatorów. `ROLE-I-TRASY.md` opisuje granice.

## Metody HTTP wszystkich tras (03.10)

- Odtworzone przed poprawką: DELETE pobierał PDF i dopisywał audyt;
  nieobsługiwana metoda API czytała błędny JSON przed odpowiedzią 405.
- Jawne metody widoków; API: logowanie → rola → metoda → treść → operacja.
- 75/75 testów SQLite PASS. Rzeczywisty OTP/CSRF i HTTP: 47 tras,
  306 odpowiedzi 405/Allow, osiem tabel bez zmian; poprawny PDF GET
  zachował bajty/hash i dopisał dokładnie jedno zdarzenie pobrania.
- Osobne HTTP potwierdza anonimowy 401, administrator po OTP 403,
  uprawniony UMP 405. Wszystkie 27 tabel głównej bazy zachowane.
- `METODY-HTTP.md`: pełny kontrakt metod. Dozwolone operacje i pełna
  macierz ról nadal wymagają odbioru; bez PG/operatorów/migracji.

## Odbiór trzech procesów na 4321275 (03.10)

- Chrome, odrębna kopia: wszystkie trzy wnioski, złożenie i akceptacja UMP.
  Moduł I także pojazd/wydanie/zbycie, korekta z historią oraz zwolnienie.
- Zbycie zachowało publiczną niedostępność; dopiero UMP zwolnił numer.
  II: kolizja bez zapisu, P031–P035, cztery wydania i alert 80%.
  III: stacja/okres, P30001–P30002, jedno wydanie i lokalne powiadomienie.
- Sześć GET Piły 404 i sześć administratora 403, potwierdzone w serwerze;
  osiem tabel bez zmian. Nie jest to pełna macierz endpointów/metod/ról.
- Sześć rzeczywistych PDF/sześć stron: hashe, numeracja, QR, granice i
  kontrola wizualna PASS; dwa pobrania Chrome identyczne z archiwum.
- Wszystkie 27 tabel głównej bazy i źródłowe HTML zachowane. Bez operatorów,
  nowego PG/podpisu lub migracji. `ODBIOR-TRZECH-MODULOW.md` opisuje zakres.

## Odbiór baz i aktualizacji na dc3d6df (03.10)

- 18/18 PostgreSQL PASS: współbieżne rezerwacje/pule/wydania, wygaszanie,
  kolejka, numeracja i rzeczywiste pg_dump/pg_restore. Bez pominięć.
- Rzeczywiste kopie/odtworzenia SQLite i PostgreSQL; wszystkie 27/23 tabel
  źródeł zachowane. W odtworzonych bazach sprawdzone tylko oczekiwane zmiany
  uwierzytelniania i wstrzymania kolejki, kolumna po kolumnie.
- Aktualizacja odtworzonej PG z 0005 do 0010: pięć migracji, cztery wzory
  i cztery zdarzenia audytu; dokumenty i pozostałe dane biznesowe zachowane.
- Chrome: nowe OTP UMP, panel, wstrzymana kolejka, archiwum i pobranie podpisanego
  PDF z identycznym SHA-256. Ponowna weryfikacja kryptograficzna DEMO przeszła.
- Prywatny serwer/PG zatrzymane. `ODBIOR-BAZY-I-AKTUALIZACJI.md` podaje
  zakres dowodów i ograniczenia. Pełny odbiór ról/procesów pozostaje otwarty.

## Inwentaryzacja i retencja techniczna (03.10)

- Odczytowy raport 19 klas danych: liczby/daty, bez identyfikatorów,
  danych osobowych, treści i BLOB-ów. Nieznana kategoria bez surowej wartości.
- Opcjonalne `purge_security_state --include-auth`: OTP i sesje wygasłe ponad
  dobę wcześniej; podgląd domyślny, zapis jawny, jedna transakcja. Istniejący
  zakres/timer nie rozpoczyna usuwania uwierzytelniania bez nowej opcji.
- 32 PASS/1 SKIP wymagający PostgreSQL; rzeczywisty test poleceń na kopii,
  dwie stare sesje/dwa kody usunięte, ponowienie zero, reszta danych zachowana.
- Główna baza bez usuwania, bez migracji. `RETENCJA-DANYCH.md` wskazuje zakres
  techniczny, pliki i formularz decyzji urzędu dla retencji biznesowej.

## Odbiór publicznej dostępności (03.10)

- Instrukcja formatu wyróżnika powiązana z polem; błąd zachowuje własny opis.
- Chrome: klawiatura, odstępy tekstu, 320 px, natywne 200%, widoczny stan
  CAPTCHA bez rozwiązania i komunikat 429. Osiem tabel obu baz bez zmian.
- 33 testy: 32 PASS/1 SKIP wymagający PostgreSQL. Axe-core 4.13.0 bez
  naruszeń w zapisanych przebiegach; gradient sprawdzony obliczeniowo.
- `WCAG-PUBLICZNY.md`: macierz 50 kryteriów, dowody i otwarte sprawdzenia.
  Pełna zgodność, czytniki i zakończenie CAPTCHA pozostają niepotwierdzone.

## Walidacja operacji API (03.10)

- Ścisłe typy wniosków, decyzji i pul, identyfikator wydania bez obcinania
  ułamków; sprawa wydania do 100 znaków w API i wspólnej usłudze HTML.
- Powtórzone klucze i niefinitywne wartości JSON odrzucane. Decyzja i
  bezpośredni przydział sprawdzają rolę UMP przed odczytem/obsługą danych.
- 81/81 testów SQLite PASS; 49 rzeczywistych sprawdzeń HTTP z OTP/CSRF.
  Wszystkie trzy moduły, odmowa, wycofanie, kolizje i izolacja urzędów.
- Osiem głównych tabel bez zmian w czasie testów; bez nowego Chrome/PG,
  wysyłki zewnętrznej lub migracji. Szczegóły: `API-OPERACJE.md`.

## Dostęp do całych list (03.10)

- Paginacja pięciu list i API wniosków, po 50 wyników. Zakres uprawnień oraz
  filtry przed paginacją; stabilna kolejność czasu i ID, linki zachowują filtry.
- Eksport obejmuje cały wynik. Listy nie pobierają binarnych treści dokumentów
  i dowodów. Starsze dane nie są ucinane do 300/100.
- 69 testów: 68 PASS/1 SKIP wymagający PostgreSQL; Ruff PASS. Bez migracji.
- Chrome: ostatnie strony wszystkich pięciu list, Enter, reset po zmianie
  filtra, fokus i zawijanie nawigacji przy 320 px. Rzeczywisty eksport 305
  wpisów i HTTP siedmiu stron API. Dziewięć tabel kopii bez zmian.
- Fixture list jest fikcyjny, bez rzeczywistego wpływu EZD lub wysyłki.
  Szczegóły i granice: `PAGINACJA-LIST.md`.

## Walidacja korekt API (03.10)

- Test potwierdził usuwanie daty sprzedaży przez niepoprawny tekst daty,
  wraz z niezamierzoną zmianą statusu. Jawna walidacja teraz zwraca HTTP 400.
- Ścisłe typy obiektu, pól, uzasadnienia i wersji; poprawna data albo jawne
  wyczyszczenie, bez automatycznego zamieniania JSON na tekst.
- 54 testy: 53 PASS/1 SKIP wymagający PostgreSQL, Ruff PASS. Bez migracji.
- 12 scenariuszy rzeczywistego HTTP z OTP/CSRF na odrębnej fikcyjnej kopii;
  negatywne korekty nie zmieniają ośmiu tabel. Brak zewnętrznego SMTP/API.
- Szczegóły: `API-KOREKTY.md`, `evidence/api-record-validation-http.json`.

## Potwierdzony postęp pierwszego etapu

- Działająca aplikacja lokalna, 35 urzędów, 4 konta testowe, logowanie OTP.
- 23 testy rdzenia PASS, w tym dwa rzeczywiste testy współbieżności bazy plikowej.
- W Chrome: publiczne sprawdzenie, logowanie A2/A3, wniosek z rezerwacją, złożenie i akceptacja UMP z pismem PDF.
- Snapshot i odtworzenie do osobnego katalogu, kontrola bazy i zapisanych PDF.
- Szczegółowy zakres dowodów i ograniczenia: `docs/WERYFIKACJA-ETAP-1.md`.

## Kolejny etap — konta, domeny i zaproszenia (03.10)

- A0 tworzy aktywne konto wraz z trwałym zaproszeniem i audytem w jednej
  transakcji; stan wysyłki i uzgodnienia są widoczne w panelu.
- Duplikat e-mail różniący się wielkością liter zwraca błąd formularza;
  aktualizacje konta wymagają powodu i aktualnej wersji formularza.
- Domeny są pełną listą, sprawdzaną przy zamawianiu/użyciu OTP i każdej sesji.
  Profil urzędowy blokuje dostęp urzędników bez skonfigurowanej listy.
- Niepewne SMTP, przerwane procesy i odtworzona kolejka wymagają uzgodnienia;
  brak automatycznego retry. Równoczesne enqueue/worker sprawdzone na PostgreSQL.
- Finalnie: SQLite 60 testów, 58 PASS i 2 pominięte wymagające PostgreSQL;
  PostgreSQL 62/62 PASS. Ruff, kontrola migracji i składni launchera PASS.
- Chrome na odrębnej kopii: A0 → nowe fikcyjne konto → kolejka → odmowa
  duplikatu → rzeczywisty lokalny MIME → osobny OTP nowego A2 → własny panel
  → odmowa dostępu do zaproszeń. Siedem tabel biznesowych kopii bez zmian.
- Migracja 0010 po backupie zachowała siedem tabel biznesowych głównej bazy,
  wszystkie konta i urzędy. Na głównej bazie nie utworzono fikcyjnego nowego konta.
- Szczegóły i dowody: `KONTA-I-ZAPROSZENIA.md`,
  `evidence/account-invitation-browser-report.json`. Nie wykonano SMTP urzędu,
  odbioru w zewnętrznej skrzynce ani wdrożenia systemd/Linux. Cel nadal aktywny.

## Kolejny etap — bezpośredni import XLSX (03.10)

- Moduł I i pule II/III przyjmują XLSX z tymi samymi kolumnami co CSV;
  jawny wybór arkusza, daty Excela 1900/1904, tekstowe oznaczenia z zerami.
- Audyt i karty danych pokazują format, arkusz oraz sumę oryginalnego pliku.
  Oryginały wykazów archiwizuje urząd; podgląd nie jest archiwum źródeł.
- Formuły, ukryte/scalone komórki, zewnętrzne odsyłacze, encje XML,
  nadmierne rozmiary i błędne współrzędne są odrzucane bez częściowego zapisu.
- Końcowe testy: SQLite 42 PASS/3 SKIP, PostgreSQL 45 PASS; III także przez
  formularz HTTP. Wyścigi w tym zestawie są wcześniejszymi scenariuszami CSV.
- Chrome, osobna kopia: dwa wpisy z wybranego arkusza, daty i 13 pól zachowane;
  pula II z dwoma numerami i lukami, historyczne wydanie oraz karta źródła.
- Backup/restore zachował siedem tabel biznesowych i audyt. Główna baza
  bez zmian. Bez migracji, Dockera lub korespondencji zewnętrznej.
- Zależności z hashami i notices: 36 paczek macOS/Linux, 56 notices; Linux
  nie został uruchomiony. Instrukcja i granice: `IMPORT-XLSX.md`.

## Kolejny etap — odmowa i terminy rezerwacji (03.10)

- Lokalny launcher uruchamia wygaszanie co 30 sekund bez potrzeby ruchu WWW.
  Jednorazowa komenda używana przez timer urzędowy pozostaje zgodna.
- Wygaszenie zapisuje statusy wpisu i wniosku oraz dwa zdarzenia audytu
  atomowo, z dawnym terminem, bez usuwania historycznych PDF.
- Bezpośrednie widoki i odczyty API odświeżają zaległy stan; wygasły wniosek
  pokazuje objaśnienie i zachowane pismo bez formularza decyzji/wycofania.
- SQLite: 48 testów, 46 PASS/2 SKIP wymagające PostgreSQL; PostgreSQL 48 PASS,
  także dwa rzeczywiste procesy transakcyjne, rollback i oczekiwanie na blokadę.
- Chrome na kopii: odmowa bez powodu zablokowana, odmowa z PDF, przedłużenie
  UMP o siedem dni, wygaśnięcie przez osobny worker przed odczytem przeglądarki,
  brak czynności na wygasłym wniosku, oba numery wolne publicznie bez logowania.
  Termin skrócono tylko dla fikcyjnego P6TERM w kopii; zegar laptopa bez zmian.
- Jednostronicowy PDF odmowy wyrenderowany i odczytany wizualnie. Backup/restore
  zachował siedem tabel biznesowych i audyt kopii, sesje i OTP unieważnione.
  Siedem tabel biznesowych głównej bazy bez zmian. Bez migracji i wysyłek.
- Szczegóły: `REZERWACJE-I-ODMOWA.md`. Cel całego systemu pozostaje aktywny;
  ten zakres nie dowodzi gotowości API operatorów, Linuxa lub pełnego WCAG.

## Kolejny etap — czytelna i dostępna historia (03.10)

- Polskie opisy zdarzeń, obiekt/identyfikator/urząd, autor i powód. Zmiany
  pól pokazują tabelę przed/po, z właściwym znaczeniem statusu, datami i strefą.
  Kod i pierwotne wartości pozostają w rozwijanych szczegółach technicznych.
- A0 nadal nie otrzymuje wartości biznesowych. A2 dziennik nadal ogranicza
  do własnych operacji; scope spraw i ochrona po przekazaniu urzędu zachowane.
- Usunięto ucinanie historii do 100 i dziennika do 300 zdarzeń: po 50 na
  stronę, zakres uprawnień przed paginacją, jednoznaczny porządek czasu i ID.
- SQLite: 42 testy, 41 PASS/1 SKIP wymagający PostgreSQL; szczegóły HTML,
  escaping, niezmienność audytu, role, trzy strony, historyczne statusy i sesje.
  PostgreSQL nie ponawiano; brak zmiany transakcji lub schematu.
- Chrome: Gniezno czyta historię wniosku i numeru, rozwija Enter; 320 px
  ujawniło rozszerzanie karty, naprawione. Strona 320/320 px, tabela w regionie
  220/330 px, fokus i ArrowRight przesuwają zawartość. Override przywrócono.
- A0 ma metadane bez właściciela i wartości przed/po; starsza strona dziennika
  odczytana w Chrome. Siedem tabel biznesowych i istniejące audyty kopii bez
  zmian; dodano tylko dwa logowania. Bez migracji, nowych pism i wysyłek.
- Szczegóły: `AUDYT-I-HISTORIA.md`. Pełny audyt czytników/WCAG, infrastruktury
  oraz rzeczywistych integracji pozostaje otwarty. Cel nadal aktywny.

## Kolejny etap — kolejność układów modułu II (03.10)

- Weryfikacja § 30 ust. 2 pkt 2 ujawniła możliwość nowego przydziału literowego
  przy brakujących numerach wcześniejszego układu. Dodano kontrolę wszystkich
  sześciu przejść, na podstawie faktycznych numerów danego prefiksu i modułu.
- Jeden zakres może uzupełnić koniec wcześniejszego układu i zacząć kolejny.
  Import historyczny i wydanie dawnych przydziałów pozostają obsługiwane.
- SQLite: 35 PASS/1 SKIP; PostgreSQL: 22 PASS, w tym dwie rzeczywiste transakcje
  przechodzące kontrolę przed zapisem: jeden przydział, jedno pismo i numeracja.
- Chrome na osobnej fikcyjnej kopii: 998/999 blokuje 1000–1001 bez zmian
  siedmiu tabel biznesowych; zakres 999–1001 przydziela P999/P01A/P01C.
  SHA-256, treść i render jednostronicowego pisma sprawdzone.
- Dowody i źródła: `KOLEJNOSC-PUL-II.md`. Bez migracji schematu. Kategoria III,
  rzeczywiste źródła i API, dostępność oraz infrastruktura pozostają otwarte.
  Cały cel nadal aktywny.

## Do wykonania / potwierdzenia

Aktualizacja 03.10: pełny pozytywny przebieg indywidualny oraz ponowna
rezerwacja/wycofanie sprawdzone w Chrome na osobnej bazie. Pozostałe role,
moduły i gałęzie nadal wymagają odbioru. Dowody i poprawki wyszukiwania,
polskiego 404 oraz audytu złożenia/wycofania: `WERYFIKACJA-PROCESOW.md`.

Aktualizacja 03.10: w Chrome sprawdzono wnioski, przydział i wydanie pul II/III,
kolizję, różną liczbę, alert 80%, izolację i 501. numer po poprawce paginacji.
Daty formularzy naprawione; 34 testy PASS: `WERYFIKACJA-PUL.md`.

Aktualizacja 03.10: obowiązkowy termin końca III w formularzu/usłudze/bazie,
trwałe powiadomienie autora przy obu decyzjach i stały lokalny worker.
62 testy SQLite i 15 skupionych PostgreSQL PASS. Chrome: brak końca → odmowa
zapisu, akceptacja i odmowa → dwa rzeczywiste MIME w lokalnej skrzynce,
po jednej próbie. Migracja zachowała dane głównej bazy. SMTP urzędu i wznowienia
pozostają do odbioru: `POWIADOMIENIA-DECYZJI.md`.

- Zweryfikować rdzeń i interfejs wszystkich ról, wszystkie przejścia statusów.
- Zweryfikować izolację API, konkurencyjne rezerwacje i kolizje pul.
- Dokończyć przepływ EZD RP, podpisy i walidację dowodów; uzyskać dostępy i zweryfikować rzeczywiste API. Konektory EZD i e-Doręczeń oraz materiały do zgłoszeń są już częściowo zaimplementowane i opisane niżej.
- Dokończyć kwalifikowaną ocenę podpisów i znaczników czasu oraz konfigurację certyfikatów urzędu; lokalny PAdES i import są opisane niżej.
- Audyt WCAG i pełny odbiór ochrony publicznej. Limit i ALTCHA są zaimplementowane; ukończenie scenariusza CAPTCHA w Chrome oczekuje na potwierdzenie.
- PDF: renderowanie i kontrola wszystkich typów pism, szablonów i długich danych.
- Odbiór backupu i przełączenia na infrastrukturze urzędu; lokalne kopie i odtworzenie SQLite oraz PostgreSQL są już sprawdzone.
- Dokumentacja wdrożenia on-premise, konfiguracji, aktualizacji, retencji.
- Przegląd bezpieczeństwa, profil produkcyjny PostgreSQL i audyt końcowy wszystkich wymagań. Lokalna weryfikacja PostgreSQL jest opisana niżej.
- Zakończyć raport zgodności, konta testowe i instrukcje przekazania.

Aktualizacja 03.10: odczytano obie nowelizacje rozporządzenia o tablicach,
potwierdzono wyłączenie Q i wybór P/M dla indywidualnych. Wspólna walidacja
oraz ponowne kontrole starszych wniosków/wydania/przywrócenia są wdrożone;
32 testy PASS, Chrome: błąd Q i poprawny M9BIOZ. Sześć tabel biznesowych
obu baz bez zmian. Jeden dawny przydzielony wpis demonstracyjny z Q zachowano.
Kategoria III, dalsze serie tymczasowe i uruchamianie M w pulach pozostają
otwarte. Dowody i źródła: `NUMERACJA-PRZEPISY.md`.

Żaden powyższy punkt nie jest potwierdzony samym istnieniem pliku implementacji. Cel pozostaje aktywny.

## Kolejny etap — EZD RP API v2

- Pobrane oficjalne kontrakty API v1/v2 i manifest SHA-256.
- Konektor uwierzytelniania, odczytu sprawy, tworzenia sprawy, zapisu PDF, metadanych oraz pobrania PDF z porównaniem SHA-256.
- Osobne profile urzędów, kontrola nadawcy, niezmienna kopia dokumentu w kolejce, dziennik etapów, bezpieczne retry i blokada niepewnych POST.
- Uzgodnienie przez administratora z odczytem API i weryfikacją PDF. Odtworzona kolejka wstrzymana do uzgodnienia.
- Instrukcja `docs/EZD-RP.md` i przygotowana treść zgłoszenia `docs/DOSTEP-EZD-RP.md`.
- 41/41 testów lokalnych; w Chrome formularz EZD i proces korespondencji do skrzynki plikowej. Dowody i granice: `docs/WERYFIKACJA-EZD.md`.
- Nadal brak rzeczywistego testu API: nie przydzielono dostępu. Zdarzenia wpływu/korespondencja wychodząca EZD, e-Doręczenia i podpisy nie są jeszcze zakończone.

## Kolejny etap — e-Doręczenia UA v3 / SE v4

- Kontrakty operatora i COI wraz z manifestem SHA-256; zapisane rozbieżności dokumentacji.
- Uwierzytelnianie JWT RS256, konfiguracja i certyfikat per urząd, cache tokenu w pamięci procesu.
- Wyszukiwanie adresów urzędów, potwierdzanie aktywnego ADE, wysyłka jednego PDF i obserwacja zadania bez ponownego wysłania.
- Oddzielne statusy przyjęcia zadania, nadania, doręczenia, uznania za doręczoną i niepowodzenia. Archiwizacja oryginalnych dowodów z SHA-256 i kontrola uprawnień do pobrania.
- 63/63 testy lokalne, w tym 21 nowych testów e-Doręczeń i rozszerzenie testów odtwarzania kolejki oraz integralności kopii. Szczegóły: `docs/WERYFIKACJA-E-DORECZENIA.md`.
- Chrome: formularz wyszukiwania i blokada wysyłki przy braku konfiguracji; nie dodano fikcyjnego sukcesu wysyłki do działającej aplikacji.
- Prawdziwy snapshot lokalnej bazy i odtworzenie do osobnego katalogu: sesje/OTP unieważnione, kolejka wstrzymana.
- Materiały `docs/DOSTEP-E-DORECZENIA.md` gotowe do uzupełnienia i zatwierdzenia. Nie wysłano zgłoszenia ani nie zaakceptowano regulaminu.
- Nadal brak testu INT/PROD; brakuje dostępu, ADE i zarejestrowanego certyfikatu. Nie wykonano walidacji podpisów dowodów. Bezpieczne wznowienie jednoznacznie niewysłanej operacji uzupełniono w etapie opisanym niżej; test operatora pozostaje otwarty.

Pozostałe wymagania całego celu nadal są otwarte. Ten etap nie jest odbiorem gotowego produktu.

## Kolejny etap — podpisy PAdES i archiwum

- Podpis lokalnym kluczem i import podpisanego oryginału, jawne profile per urząd, kontrola treści oraz certyfikatów i CRL/OCSP.
- Raport, podpisujący, sumy kontrolne, uprawnienia, blokada podpisu po kolejce i nowe wersje z zachowaniem poprzednika.
- Rzeczywisty certyfikat demonstracyjny i scenariusz w Chrome; kontrola podpisu z bazy, render PDF oraz snapshot i odtworzenie podpisanego dokumentu.
- Dowody: `docs/WERYFIKACJA-PODPISOW.md`. Nie oceniono kwalifikowanego statusu ani znaczników czasu; nie wykonano testów sprzętu i usług urzędu.
- Pełna realizacja specyfikacji pozostaje otwarta.

## Kolejny etap — trwała roczna numeracja

- Wnioski mają zapisany stały identyfikator; nowe pisma mają kolejny numer osobno dla roku i nadawcy. Znak sprawy pozostaje osobnym polem.
- Liczniki w transakcji, unikalne indeksy, rollback błędu PDF, ochrona przed cofniętym licznikiem i kontrola numeracji w backupie.
- Migracja zachowała wszystkie 9 wcześniejszych dokumentów i 4 identyfikatory. W Chrome: wniosek → decyzja → podpis DEMO → nowa wersja z kolejnym numerem.
- W odtworzonej kopii sprawdzono kontynuację serii. Szczegóły i ograniczenia: `docs/NUMERACJA.md`.
- PostgreSQL sprawdzono w kolejnym etapie; numeracja kancelaryjna konkretnego urzędu nadal wymaga potwierdzenia.

## Kolejny etap — PostgreSQL bez kontenerów

- Osobny prywatny klaster PostgreSQL 18.6 i baza testowa; bez TCP, Dockera i globalnej usługi.
- 93/93 testy PostgreSQL PASS, w tym rzeczywiste blokady, rezerwacje, kolizje pul, numeracja i współbieżne wydawanie/claim kolejki. Regresja SQLite: 96 PASS, 2 pominięte testy PostgreSQL.
- Naprawione logowanie OTP na PostgreSQL, kolejność tablica → wniosek i blokada przy odwołaniach FK. Stara funkcja wycofania w izolowanym procesie testowym odtworzyła deadlock; poprawiony scenariusz PASS.
- Zablokowano przedłużenie i rozpatrzenie przeterminowanej rezerwacji przed wykonaniem zadania wygaszania.
- W Chrome osobna baza: OTP powiatu i UMP → nowy wniosek → złożenie → decyzja i zapis PDF.
- Instrukcja i dowody: `docs/POSTGRESQL-LOKALNIE.md`. Backup PostgreSQL sprawdzono w kolejnym etapie; docelowa infrastruktura i rzeczywiste API pozostają otwarte. Cały cel nie jest ukończony.

## Kolejny etap — kopia i odtworzenie PostgreSQL

- Kopia pg_dump z manifestem i kontrolą dokumentów/numerów w tym samym snapshotcie; strumieniowa kontrola bytea i rozpakowanie.
- Odtworzenie wyłącznie do nowej bazy, sprawdzenie sum/migracji/liczb rekordów, unieważnienie sesji i OTP, wstrzymanie aktywnej kolejki i powiązań EZD w CREATING. Błąd po utworzeniu nowej bazy blokuje jej połączenia.
- 6/6 testów native PostgreSQL oraz 5/5 regresji backupu SQLite PASS.
- W rzeczywistej kopii 4 wnioski i 8 pism; zachowany i ponownie sprawdzony podpis DEMO. Nowy numer tylko w kopii W/2026/00005; źródło pozostało bez zmian po wykonaniu snapshotu.
- Worker nie wznowił odtworzonego zadania. Chrome: nowe OTP → archiwum dokumentów → wstrzymana kolejka.
- Procedura i dowody: `docs/BACKUP-POSTGRESQL.md`. Nie sprawdzono infrastruktury urzędu, RPO/RTO, WAL/PITR ani rzeczywistych API. Pełny cel pozostaje aktywny.

## Kolejny etap — przekazanie wpisu i izolacja urzędów

- Usunięto ujawnianie bieżącego właściciela, VIN i korekt innego urzędu przez historyczny wniosek dawnego urzędu. Pierwotny wniosek i niezmienne pisma pozostają jego dokumentacją.
- Zablokowano przekazanie podczas DRAFT/SENT i wybór nieaktywnego celu; audyt i wersjonowanie pozostają w transakcji.
- 28/28 testów PostgreSQL PASS, w tym rzeczywiste oczekiwanie starego zapisu na blokadę transferu. SQLite: 27 PASS, 1 SKIP PostgreSQL.
- Chrome na osobnej bazie: Gniezno → UMP przekazuje do Piły → Gniezno bez nowych danych → Piła zapisuje pojazd → ponownie Gniezno bez nowych korekt. PDF i pochodzenie wniosku zachowane.
- Główna aplikacja uruchomiona z poprawką, health 200; dane biznesowe niezmienione. Raport: `docs/WERYFIKACJA-PRZEKAZANIA.md`.
- Pełny audyt uprawnień, dostępność, wdrożenie urzędowe i rzeczywiste integracje nadal wymagają pracy. Cel pozostaje aktywny.

## Kolejny etap — ochrona publicznego wyszukiwania

- Wspólny limit HTML/API, CAPTCHA ALTCHA v2 po progu, HMAC i jednorazowa transakcja; powiązanie z sesją/IP, kontrola replay i zmienionych parametrów. Własny host, bez CDN i usługi dostawcy, polski widget.
- Migracja 0006 dodaje wyłącznie stan wyzwań; odtworzenie kopii unieważnia dawne wyzwania. Retencja ma osobny proces z podglądem.
- 37/37 testów PostgreSQL PASS, w tym replay dwóch rzeczywistych transakcji i pg_dump/restore. SQLite: 32 PASS, 1 SKIP PostgreSQL.
- Rzeczywisty dostarczany worker JavaScript obliczył dwa syntetyczne wektory z kosztem 5000; oficjalna biblioteka Python przyjęła wyniki i odrzuciła zmienione klucze. Sprawdzono SHA-256 wszystkich plików widgetu. To test offline, osobny od otwartego scenariusza Chrome.
- Chrome potwierdził zwykłe wyniki i wymaganie weryfikacji po progu. Pełne ukończenie CAPTCHA w UI czeka na potwierdzenie wymagane przez narzędzie. WCAG/czytniki/mobilne urządzenia wymagają dalszego audytu.
- Instrukcja i zakres dowodów: `docs/OCHRONA-PUBLICZNA.md`. Cel pozostaje aktywny.

## Kolejny etap — bezpieczne wznowienie e-Doręczeń

- Trwały zapis granicy wysyłki, jawna odmowa przyjęcia i wersja mechanizmu; niepewne lub starsze etapy bez dowodu blokują ponowienie.
- Administrator w panelu lub CLI wznawia to samo niewysłane zlecenie po sprawdzeniu konfiguracji/ADE/integralności. Znane zadanie operatora umożliwia tylko odczyty. Uzasadnienie, CSRF, wersja formularza, audyt i ponowna kontrola w transakcji.
- Odtworzenie SQLite/PG oznacza wszystkie zlecenia EDOR, także CONFIG_ERROR; odtworzony stan nie dowodzi braku późniejszej wysyłki w źródle.
- 59/59 testów PostgreSQL PASS, w tym równoczesne wznowienia, powrót starego pracownika po nowej próbie, odtworzenie kopii i regresja EZD/SMTP. SQLite: 53 PASS, 2 SKIP PostgreSQL. API jest symulowane w testach; blokady i kopie są rzeczywiste.
- Sprawdzenie aktualnej próby i dzierżawy przed POST oraz warunkowy końcowy zapis wyniku chronią przed wysyłką i nadpisaniem wyniku przez spóźnionego pracownika.
- Chrome na osobnej bazie: OTP administratora → formularz → odmowa bez profilu; niepewne/odtworzone zlecenie bez akcji; powiat otrzymuje polski HTTP 403. Nie wykonano pozytywnego scenariusza z API operatora.
- Procedura i granice dowodów: `docs/WZNOWIENIE-E-DORECZEN.md`. Rzeczywiste INT, podpisy dowodów i pozostałe wymagania całego systemu pozostają otwarte.

## Kolejny etap — wpływy EZD → Dyna

- Oficjalny kontrakt API v2 ponownie pobrany: HTTP 200, ten sam SHA-256. Odczyt RPW po numerze oraz stronicowany odczyt okresu; brak domniemanego webhooka.
- Zgodność wersji/przestrzeni, niezmiennych bajtów pisma i adresata; archiwum PDF, deduplikacja, link do wniosku i chronione pobranie. Niejednoznaczne dokumenty bez automatycznego przypisania i bez treści w archiwum.
- Osobny jawny PUT identyfikatora i linku do skonfigurowanych atrybutów, ponowna kontrola RPW/SHA, dziennik prób i audyt urzędu odbiorcy. Nie tworzy dokumentu ani nie zmienia decyzji.
- 50/50 testów PostgreSQL PASS, w tym dwa równoczesne odczyty, backup z podpisanym dokumentem wpływu i regresja przekazania wpisu. SQLite: 45 PASS, 2 SKIP PostgreSQL. Operator HTTP jest symulowany.
- Chrome na osobnej bazie: UMP → lista fikcyjnych wpływów → właściwy wniosek → PDF; brak profilu blokuje odczyt i zapis linku. Piła nie widzi wpływów UMP i otrzymuje 404 przy pobraniu ich PDF.
- Migracja 0007 zastosowana po backupie; główna aplikacja z poprawką, health 200, sześć tabel biznesowych bez zmian. Bez fikcyjnych wpływów w głównej bazie.
- Instrukcja i granice: `docs/WPLYWY-EZD.md`. Rzeczywiste EZD/klikalny link, skany, korespondencja wychodząca, podpisy, on-premise i cały odbiór systemu pozostają otwarte.

## Kolejny etap — profil infrastruktury urzędu

- Osobny profil on-premise: wymaga PostgreSQL, poprawnej domeny HTTPS, pełnego SHA, niezależnych sekretów i szyfrowanego SMTP; zdalna baza wymaga verify-full/CA.
- Gunicorn na loopback, sprawdzanie zaufanego proxy i pojedynczego IP klienta; nagłówki klienta nie zmieniają liczników przez X-Forwarded-For.
- Pusta inicjalizacja 35 nieaktywnych urzędów i administratora OTP, bez spraw/pojazdów/kont pokazowych, z audytem i blokadą nadpisania istniejącej instalacji.
- Wzory Nginx, systemd, kolejki, wygasania, kopii i aktualizacji. Rola wykonawcza bez DDL/własności/administracji/członkostwa; migracje innym kontem.
- PostgreSQL: 24/24 PASS; SQLite: 23 PASS / 1 SKIP PG. Rzeczywisty proces Gunicorn + nowa baza PG + CREATE TABLE odmówione + dwa odrębne liczniki IP + health i blokada obcego hosta. Właściciel odrzucony przez preflight; backup pg_dump wykonany rolą wykonawczą.
- Dwa jawne zalecenia Django HSTS/subdomen/preload pozostają widoczne. Nie wykonano próby Nginx/TLS, systemd ani SMTP na Linuxie. Zasady retencji spraw, monitoring operacyjny, lock zależności i odbiór infrastruktury wymagają dalszej pracy.
- Instrukcja i granice dowodów: `docs/WDROZENIE-URZEDOWE.md`. Ten etap nie zamyka całego celu.

## Kolejny etap — PDF, powiązanie spraw i wzory

- Nowe pisma A4: data utworzenia, czytelne brakujące dane, adres wnioskodawcy, klikalny link i wektorowy QR do właściwej sprawy/puli. Polskie znaki, marginesy i długie akapity sprawdzone na wszystkich 12 stronach dziesięciu dokumentów.
- Walidacja szablonów przed zapisem i podczas generowania, dosłowny HTML, rollback rezerwacji/licznika po błędzie. Migracja aktualizuje tylko dokładne domyślne wzory, z audytem i zachowaniem własnych zmian urzędu.
- SQLite 36/36 PASS; PostgreSQL 37/37 PASS, w tym rzeczywiste odtworzenie numeracji i kopii z podpisanym PDF-em. Naprawiono zależność starszych testów od silnika i przywracanie aktualnego schematu po teście migracji.
- Chrome na osobnej bazie: OTP → wniosek → PDF → kliknięty link → właściwy wniosek; rzeczywisty podgląd wydruku bez wysłania na drukarkę.
- Backup przed migracją 0008; cztery wzory rev2 z audytem. Sześć tabel biznesowych i wszystkie 12 archiwalnych pism zachowane bez zmian.
- Dokumentacja: `docs/PISMA-PDF.md`. PDF/UA/czytniki, zatwierdzenie wzorów, kwalifikowane podpisy, rzeczywiste API i pełna realizacja celu pozostają otwarte.

## Kolejny etap — dostępność formularzy i reflow

- Opisowe tytuły 18 ekranów, kontrast fokusu i pól, podsumowanie błędów z linkami i fokusem, fokus wyniku publicznego, podpisy i dostępne przewijanie tabel. Układ zawija nagłówek i formularze przy małej szerokości.
- Pola nieużywane w wybranym module są wyłączone; indywidualny wniosek nie wymaga liczby puli. Dla II/III nadal wymagane liczba i uzasadnienie. Błędy numeru/VIN przypisane do pól; poprawiony komunikat dla wniosku o pulę.
- Testy: 37 PASS / 1 SKIP PostgreSQL. HTML 17 kombinacji roli/strony, walidacja, rdzeń i ochrona publiczna. Dziesięć par kolorów sprawdzonych obliczeniowo.
- Chrome, osobna baza: faktyczne powiększenie 400% / 320 CSS px, skip-link, błędy/wynik, OTP, zapis poprawionego wniosku I oraz wniosku III, klawiatura w przewijanej tabeli. Powiększenie przywrócone.
- Dokumentacja: `docs/DOSTEPNOSC.md`. Pełne WCAG A/AA, czytniki, pozostałe ekrany/stany i przeglądarki, PDF/UA, rzeczywiste API oraz odbiór urzędowy pozostają otwarte. Cel jest nadal aktywny.

## Powrót po OTP i nieaktualne formularze — 03.10.2026

- Logowanie zachowuje link do chronionego ekranu, również przy zamówieniu nowego kodu. Cel jest sprawdzany dwukrotnie i ograniczony do lokalnego panelu; uprawnienia urzędów nadal obowiązują.
- Polski HTTP 403/JSON dla odrzuconego CSRF, bez wewnętrznej przyczyny, zapisu lub automatycznego ponowienia operacji.
- 36 PASS: OTP, sesja, CSRF, dostępność i rdzeń. Chrome na osobnej bazie: link → OTP → właściwy wniosek; stary formularz po ponownym logowaniu odrzucony, bez nowego wniosku i rezerwacji.
- `docs/LOGOWANIE-I-SESJE.md`. Ostrzeganie o końcu sesji, przedłużanie i odzyskiwanie szkicu pozostają otwarte; nie wykonano godzinnego oczekiwania w Chrome ani testu czytnika ekranu.

## Ostrzeżenie przed końcem logowania — 03.10.2026

- Odczyt faktycznej daty ważności sesji bez automatycznego odnowienia; ostrzeżenie 120 sekund przed końcem, jawne przedłużenie przez POST/CSRF i audyt. Przycisk dostępny także w nagłówku.
- Przedłużenie zachowuje pola, identyfikator sesji, token formularza i przywraca fokus. Kontekst konta/roli/urzędu jest porównywany przed przedłużeniem.
- 46 PASS w regresji, następnie 17 PASS dla końcowego zakresu sesji i HTML. Dziesięć kolejnych przedłużeń, odmowy dla wygasłej sesji, CSRF i zmiany konta/urzędu.
- Chrome, osobna baza: skrócony termin sesji → ostrzeżenie → Enter → nowy termin w bazie, zachowane pola i fokus; 400%/320 px, przewijanie regionu klawiaturą; wygaśnięcie → blokada zapisu starego formularza. Powiększenie przywrócone. Żaden z fikcyjnych formularzy nie utworzył wniosku ani rezerwacji.
- `docs/LOGOWANIE-I-SESJE.md` i `evidence/session-control-browser-report.json`. Nadal otwarte: odzyskiwanie szkicu, czytniki, pełne WCAG i scenariusze uśpienia/awarii/ograniczania kart w tle. Nie wykonano godzinnego oczekiwania ani pełnego odbioru kryterium czasu.

## Odtwarzalność zależności — 03.10.2026

- Lock serwera i osobny lock narzędzi PDF/QR: dokładne wersje, zależności przechodnie, SHA-256; pliki wejściowe do planowanych aktualizacji. Zachowano wersje dotychczasowych 33 zależności serwera.
- Pobranie z hashami i wyłącznie wheel dla CPython 3.12 macOS ARM64 i Linux glibc x86-64/ARM64. To dowód dostępności paczek, nie wykonania na Linuxie.
- Czyste środowisko macOS zainstalowane offline: pip check, Django check oraz 34 testy dokumentów/podpisów/sesji PASS. Celowo zmieniony wheel odrzucony przez pip i narzędzie spisu. Narzędzia QA zainstalowane offline bez konfliktów.
- Spisy trzech platform i 52 oryginalne pliki notices; wszystkie ich hashe sprawdzone. `docs/ZALEZNOSCI.md`, `THIRD-PARTY-NOTICES.md`, `third_party/`.
- Pełny spis natywnych składników wheel/systemu, kwalifikacja dystrybucji komercyjnej, podatności, Linux/systemd/TLS, rzeczywiste integracje i pozostałe wymagania całego celu nadal są otwarte.

## Podpis i kolejka na PostgreSQL — 03.10.2026

- 10 nowych testów rzeczywistych transakcji: oba porządki podpis/kolejka osobno dla SMTP, EZD i e-Doręczeń, dwa podpisy, rollback i wolna kryptografia poza transakcją. Oczekiwanie i konkretny blokujący backend potwierdzone przez PostgreSQL.
- Końcowy przebieg 26/26 PASS obejmuje także 16 regresji podpisów. Rzeczywisty plik MIME lokalnej poczty zawiera dokładnie podpisany PDF; ponowienie tego samego pracownika nie tworzy drugiej wiadomości.
- Istniejący mechanizm przeszedł te scenariusze; nie zmieniono kodu podpisu/kolejki ani schematu. Fikcyjne certyfikaty i profile operatorów, bez wywołań rzeczywistego SMTP/API. `docs/WSPOLBIEZNOSC-PODPISU.md` i `evidence/signature-concurrency-postgres-final.txt`.
- Testy dotyczą dwóch połączeń i pisma wniosku indywidualnego; nie są pomiarem pojemności, odbiorem urzędu, podpisu kwalifikowanego ani integracji z operatorem. Cel pozostaje aktywny.

## Kontynuacja numerów i wyczerpanie pojemności — 03.10.2026

- Roboczy profil tymczasowy III obejmuje teraz 29 979 pozycji na prefiks: cyfrowe 0001–9999, następnie 001A–999Y. Początkowe numery i archiwalne pisma zachowane.
- Kontynuacja wymaga wszystkich wcześniejszych numerów cyfrowych. Nowe pule M wymagają pełnej ewidencji P danej kategorii; sam maksymalny koniec zakresu nie wystarcza. M dla indywidualnych nadal wybierane swobodnie.
- SQLite 51/51 PASS; PostgreSQL 12/12 PASS, z rzeczywistymi zapytaniami i pozytywnym przydziałem M w II. Nie wykonano pozytywnego przydziału M na pełnej bazie III ani nowego wyścigu decyzji na granicy serii.
- Chrome na osobnej fikcyjnej kopii: odmowa M bez zmiany siedmiu tabel, decyzja P8 9998–10001, cztery prawidłowe numery, wydanie P8001A przez Gniezno, wykorzystanie 1/4. PDF wyrenderowany i sprawdzony, powiadomienie autora w kolejce bez prób wysyłki.
- Wszystkie wiersze sześciu głównych tabel biznesowych zachowane. Bez migracji schematu, Dockerów i zmian danych głównej ewidencji.
- `docs/POJEMNOSCI-PUL.md`. Potwierdzenie kategorii III, historyczne pule i ich import, rzeczywiste API oraz pozostałe wymagania pełnego celu pozostają otwarte.

## Import historycznych wykazów pul — 03.10.2026

- UMP wczytuje CSV II/III, przegląda wszystkie numery i źródła, zatwierdza konkretny podgląd z uzasadnieniem. Ponowna walidacja, hash, ważność 15 minut, ochrona starej karty/replay oraz atomowy zapis całego pliku.
- Rzeczywiste numery, daty wydania, okres, urząd i źródło bez uzupełniania luk. Historia może dotyczyć nieaktywnego urzędu, liter lub M; nowe przydziały nadal podlegają kontroli pojemności. Bez nowych wniosków, pism i wysyłek.
- SQLite 51 PASS / 1 SKIP PG; PostgreSQL 26/26 PASS, w tym dwa importy po ukończonym podglądzie: jeden zapis, jedna kolizja. Po zmianie etykiet 10/10 regresji HTML pul/importu PASS. Wspólny porządek numerów w obu ścieżkach zapisu.
- Końcowa regresja importu 13 PASS / 1 SKIP PG po obsłudze uszkodzonego nagłówka CSV; także błędny token Unicode daje komunikat bez zapisu zamiast HTTP 500. Ruff/format/Django/brak nowych migracji sprawdzone.
- Chrome na fikcyjnej kopii: kolizja i podgląd bez zapisu, import dwóch pul/czterech numerów, Gniezno widzi historyczne daty i źródło, wygasły numer bez wydania, powiat bez dostępu do importu. Brakujący P032 nie powstał.
- Rzeczywista kopia i odtworzenie do nowego katalogu zachowują wszystkie sześć tabel biznesowych i audyt. Oryginalne wiersze kopii oraz główna ewidencja bez zmian. Oryginalny CSV/PDF trzeba archiwizować osobno; aplikacja przechowuje odwołanie i hash CSV.
- `docs/IMPORT-PUL.md`, `evidence/pool-import-ui-proof.json`. Pozostają rzeczywiste źródła i ich kompletność, potwierdzenie III, pełna dostępność, API operatorów i cały odbiór. Cel nadal aktywny.

## Import indywidualny — konkretne źródło i stara karta — 03.10.2026

- Usunięto możliwość zatwierdzenia nowego CSV ze starej karty. Podgląd ma wersję, konto, SHA-256 oryginalnego UTF-8/BOM i ważność 15 minut; błędny lub nowy plik unieważnia poprzedni. Wszystkie pola i strony są dostępne do sprawdzenia, z nazwami urzędów i polskimi statusami.
- Ścisły CSV, daty i zbycie, uzasadnienie/potwierdzenie, niezmienny audyt źródła. Powtórzenie dokładnie tego samego źródła blokowane także dla wyłącznie zwolnionych wpisów. Transakcja całego pliku, bez nowych wniosków/pism/wysyłek.
- SQLite 50 PASS / 2 SKIP PostgreSQL; PostgreSQL 15/15 PASS. Rzeczywiste dwa importy aktywnych numerów: jeden zapis/jedna kolizja; dwa importy tego samego zwolnionego źródła: jeden wpis i audyt.
- Chrome na osobnej kopii: błędny nagłówek, dwie karty i odmowa starego zatwierdzenia bez zmiany siedmiu tabel i audytu; właściwy import dwóch wpisów. Eksport pobrany w Chrome, wszystkie 13 pól nowych wpisów zgodne ze źródłem/bazą.
- Publicznie zbyty M9JELEN niedostępny, zwolniony P4PAST dostępny. Gniezno widzi daty i audyt, bez uprawnienia do importu. Piła ma 404 dla tego samego wpisu.
- Rzeczywisty backup/restore zachowuje wszystkie siedem tabel biznesowych i audyt; sesje usunięte, OTP oznaczone użyte. Odtworzonej aplikacji nie uruchamiano. Główne dane zachowane, bez migracji schematu i Dockera.
- `docs/IMPORT-EWIDENCJI.md`, `evidence/record-import-ui-proof.json`. Oryginalne CSV/pisma archiwizowane osobno; suma rozpoznaje te same bajty, nie wszystkie semantyczne duplikaty. XLSX wymaga konwersji. Rzeczywiste źródła, API, pełna dostępność i cały odbiór nadal otwarte; cel aktywny.

## Czynności przy wpisie — 03.10.2026

- Powiat: RESERVED/SENT/RELEASED jako dane i historia, bez formularza; bezpośredni POST daje 403 bez zmian. ALLOCATED/ISSUED/SOLD zachowują formularz pojazdu. UMP zachowuje korekty wszystkich stanów i przedłuża tylko niewygasłe RESERVED/SENT.
- Czytelne źródło importu, bez przypisywania obecnego czasu do dawnego przydziału. 37/37 testów PASS, Chrome na fikcyjnej kopii: zwolniony i oczekujący bez edycji, przydzielony z formularzem, Piła 404.
- Siedem tabel biznesowych obu baz bez zmian. `docs/CZYNNOSCI-WPISU.md` i `evidence/record-actions-browser-report.json`. Bez nowego testu PostgreSQL/backup/WCAG; cały cel aktywny.
