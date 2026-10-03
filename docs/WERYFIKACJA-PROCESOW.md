# Ręczny odbiór procesów — 03.10.2026

Cały cel pozostaje **W TOKU**. Ten etap potwierdza indywidualny przebieg opisany
poniżej, ponowną rezerwację i wycofanie oraz wybrane przypadki izolacji urzędów.
Nie jest pełnym odbiorem wszystkich ról, trzech modułów ani usług operatorów.

## Środowisko

Chrome użytkownika, Django 5.2.17 / CPython 3.12.14, osobna baza SQLite
`var/business-ui-20261003/registry.sqlite3`, 35 urzędów i fikcyjne konta.
Adres odbioru: `http://localhost:8774/`. Osobne nazwy ciasteczek sesji/CSRF
w prywatnej konfiguracji zapobiegały kolizji z innymi aplikacjami localhost.
To konfiguracja testu, a nie profil instalacji urzędowej.

Sześć tabel biznesowych głównej bazy `var/registry.sqlite3` zachowało liczby
i SHA-256 z poprzedniego etapu. Wiadomości OTP trafiały wyłącznie do lokalnej
skrzynki plikowej; nie wysyłano pism do urzędu ani operatora. Bez Dockera.

## Przebieg w Chrome

| Czynność | Wynik |
| --- | --- |
| Obywatel wyszukuje ZOLW, cyfra 7 | P7ZOLW dostępny; sprawdzenie nie rezerwuje |
| Gniezno loguje się przez OTP | Urząd i rola wynikają z konta |
| Błędny VIN we wniosku | Brak zapisu, dane zachowane, fokus i opis błędu |
| Gniezno zapisuje poprawiony wniosek | W/2026/00004, rezerwacja do 17.10.2026, PDF |
| Gniezno składa wniosek | Status oczekujący i audyt; screenshot 45 |
| Piła otwiera bezpośredni link do sprawy | HTTP 404; własny panel bez spraw Gniezna |
| UMP akceptuje | Przydział i pismo zwrotne; screenshot 46 |
| Gniezno zapisuje rejestrację i pojazd | Status wydany, dane i powód zmiany |
| Gniezno zapisuje zbycie | Status pojazd zbyty, nabywca, data, historia; screenshot 47 |
| Obywatel sprawdza po zbyciu | Niedostępny, bez danych osobowych; screenshot 48 |
| UMP koryguje właściciela i uwagę | Wartości przed/po i powód w bazie |
| UMP zwalnia z uzasadnieniem | Wpis i historia pozostają; screenshot 49 |
| Obywatel sprawdza po zwolnieniu | Dostępny; po poprawce jedna karta wyniku; screenshot 50 |
| Gniezno ponownie rezerwuje ten sam numer | W/2026/00005, nowy wpis; poprzedni zachowany |
| Gniezno składa i wycofuje nowy wniosek | Historia numeru RESERVED → SENT → RELEASED; screenshot 52 |

Screenshoty 45–52, wyciągi audytu i dwa PDF-y są w ignorowanym
`evidence/private/`. Oba wpisy P7ZOLW zachowane, żadnego aktywnego.
Maszynowy raport: `evidence/business-flow-report.json`.

## Poprawki wynikające z odbioru

- `e3f095d`: główny wynik HTML/API honoruje wskazaną cyfrę, także 0. Bez wyboru
  nadal dziesięć kart; sugestie wskazują wolne alternatywy. Chrome: cyfra 7
  po zwolnieniu pokazuje jedną kartę. Polski ekran 404 umożliwia powrót
  do panelu. Piła nadal ma 404 dla sprawy Gniezna, bez potwierdzenia jej
  istnienia; kliknięty powrót prowadzi do własnego pustego panelu.
- `2e42a63`: złożenie i wycofanie zapisują osobne `plate.submitted` oraz
  `plate.withdrawn`, razem ze zmianą wniosku w tej samej transakcji.
  Nowy przebieg sprawdzono w Chrome i bazie. Historycznych zdarzeń nie
  dopisywano wstecz; pierwszy wniosek odbioru powstał przed poprawką audytu.

## Testy i dokumenty

- 37 PASS: wybór cyfry HTML/API, 0/7, brak wyboru, prefiks M, zarezerwowany
  numer, wolne sugestie, prywatność, błędne cyfry, 404, rdzeń i ochrona publiczna.
  `evidence/availability-selection-tests.txt`.
- 31 PASS po poprawce historii: audyt widoczny na stronie numeru, wycofanie
  szkicu, wymagany powód, odrzucenie ponownego złożenia bez drugiego zdarzenia,
  rollback obu statusów i wersji przy awarii audytu, regresja wyboru i rdzenia.
  `evidence/plate-lifecycle-history-tests.txt`.
- Zestawy częściowo się pokrywają: nie są 68 odrębnymi scenariuszami.
- Ruff i kontrola diffu PASS. W tym etapie bez ponowienia PostgreSQL lub
  pełnych testów integracyjnych.
- Oba PDF-y po jednej stronie, SHA-256 zgodny z bazą, tekst zawiera właściwy
  numer i referencję. W tym etapie nie wykonano kontroli wizualnej tych
  konkretnych PDF-ów; wcześniejszy odbiór szablonów opisuje PISMA-PDF.md.

## Pozostały zakres

W Chrome wymagają pełnego odbioru administracja, moduły II/III, import/eksport,
odmowa, przedłużenie, wygasanie i pozostałe niedozwolone operacje.
Testy backendu nie zastępują odbioru interfejsu.

Dalsze uwagi UI: techniczne nazwy zdarzeń oraz formularz pojazdu wyświetlany
powiatowi przy zwolnionym wpisie. Serwer odrzuca taką edycję; interfejs powinien
jasno pokazywać dostępne czynności.

Aktualizacja: formularz w niedostępnych stanach i czytelne pochodzenie
importowanego wpisu poprawiono w `CZYNNOSCI-WPISU.md`. Techniczne nazwy
starszych zdarzeń i pełny odbiór historii pozostają do dalszego dopracowania.

Aktualizacja odbioru odmowy, przedłużenia i wygasania: `REZERWACJE-I-ODMOWA.md`.
Osobna kopia SQLite, rzeczywista odmowa UMP z PDF, przedłużenie o siedem dni,
wygaszenie przez proces w tle przed odczytem w Chrome i wynik publiczny.
Powyższa lista ograniczeń opisuje wcześniejszy etap; odbiór pozostałych modułów,
importów oraz kont ma osobne raporty wskazane w README.

Aktualizacja historii: techniczne nazwy przeniesiono do szczegółów; polskie
opisy i tabela pól przed/po wraz z paginacją są odebrane w `AUDYT-I-HISTORIA.md`.
Pozostałe granice pełnego audytu opisuje STATUS.md.

Aktualne reguły prawne, pełne WCAG, kwalifikowane podpisy, dostęp INT/EZD RP,
rzeczywiste API, odbiór Linux/HTTPS/SMTP i raport zgodności całego zakresu
pozostają otwarte. Etap nie dowodzi gotowości produktu do eksploatacji w urzędzie.
