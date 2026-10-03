# Kolejność układów tablic zmniejszonych — 03.10.2026

Nowy przydział modułu II sprawdza, czy wcześniejsze układy numeracji są
wyczerpane. Dotychczas system generował układy w poprawnym porządku, lecz
pozwalał wskazać pozycję następnego układu bez wcześniejszych numerów w bazie.
Przykład: P01A było możliwe przy brakującym P999. Taki nowy przydział jest
teraz blokowany zarówno w panelu, API, jak i przy decyzji o wniosku.

## Podstawa i zakres

[Rozporządzenie 2024/1709](https://api.sejm.gov.pl/eli/acts/DU/2024/1709/text.html),
§ 30 ust. 2 pkt 2, ustala siedem kolejnych układów tablic zmniejszonych.
§ 31 ust. 1 określa wyłączenia liter, a ust. 3 warunek użycia drugiej litery
województwa. Odczytano ponownie te fragmenty oraz całe nowelizacje
[2025/939](https://api.sejm.gov.pl/eli/acts/DU/2025/939/text.pdf) i
[2026/891](https://api.sejm.gov.pl/eli/acts/DU/2026/891/text.pdf).
Zmiany nie zastępują kolejności z § 30 ust. 2 pkt 2. ELI wskazuje akt jako
obowiązujący i te dwie nowelizacje. Manifest URL, metadanych i SHA-256:
`evidence/small-layout-legal-sources.json`. Pobranie systemowym curl zachowało
weryfikację TLS; nie wyłączano jej po błędzie łańcucha CA domyślnego Pythona.

Implementacja traktuje przejście do kolejnego układu jako wymagające pełnego
pokrycia wcześniejszych układów w ewidencji. Jest to zastosowanie przepisu
do procesu przydziału, nie opinia prawna ani potwierdzenie kompletności danych
urzędu. Nie zmieniano kategorii III ani kompetencji organów.

| Pozycje dla jednego prefiksu | Układ | Liczba numerów |
| --- | --- | ---: |
| 1–999 | trzy cyfry | 999 |
| 1000–2979 | dwie cyfry i litera | 1980 |
| 2980–4599 | cyfra, litera i cyfra | 1620 |
| 4600–6579 | litera i dwie cyfry | 1980 |
| 6580–10179 | cyfra i dwie litery | 3600 |
| 10180–13779 | dwie litery i cyfra | 3600 |
| 13780–17379 | litera, cyfra i litera | 3600 |

## Zachowanie

- Kontrola liczy faktycznie zapisane, poprawne i unikalne numery modułu II
  danego prefiksu we wszystkich urzędach, także z wygasłych pul. Deklarowany
  koniec zakresu, pozycja ordinal, inny prefiks lub inny moduł nie uzupełniają
  brakujących numerów.
- Jeden nowy zakres może kończyć wcześniejszy układ i zaczynać następny,
  również kilka kolejnych układów. Przykład: przy zapisanych P001–P998
  pozycje 999–1001 zapisują P999, P01A, P01C.
- Kontrola korzysta z jednego odczytu zbiorczego dla wcześniejszych układów.
  Nie pobiera wszystkich numerów do pamięci aplikacji. Dla zakresu cyfrowego
  nie wykonuje tego dodatkowego odczytu.
- Kolizja całego proponowanego zakresu jest sprawdzana wcześniej, a unikalny
  indeks i transakcja pozostają zabezpieczeniem przed konkurencyjnym zapisem.
  Brak pojemności wycofuje decyzję/przydział, PDF, numerację i audyt czynności.
- Warunek wyczerpania P przed nowym M pozostaje. Po jego spełnieniu układy M
  liczą własne wcześniejsze numery, niezależnie od pełnej ewidencji P.
- Import wcześniejszych przydziałów nadal zapisuje fakty historyczne, także
  układy literowe przy niepełnej historii cyfr. Nie zmieniono dawnych pul,
  wydania ich numerów ani plików PDF. Brakujące źródła należy uzgodnić
  i wprowadzić przez import, nie tworzyć fikcyjnych przydziałów urzędu.

## Weryfikacja

- SQLite: **35 PASS / 1 SKIP**, 36 testów, 2.527 s. Dziewięć nowych testów, 11 wcześniejszych
  pojemności, sześć HTTP pul oraz dziewięć importu historycznego.
  Pominięto nowy wyścig wymagający PostgreSQL. `evidence/small-layout-order-tests.txt`.
- Natywny PostgreSQL: **22/22 PASS**, 2.823 s. Dziesięć nowych i 11 wcześniejszych
  testów pojemności, także istniejący wyścig dwóch wydań jednego numeru.
  `evidence/small-layout-order-postgres-tests.txt`.
- Sprawdzono wszystkie sześć przejść układów: brak ostatniego wcześniejszego
  numeru blokuje zapis; uzupełnienie pozwala przydzielić pierwszy następny.
  Także dziura w pierwszym układzie mimo pełnego drugiego, M po pełnym P,
  zakres przechodzący kilka układów, API/HTML i rollback decyzji wniosku.
- Dwie odrębne transakcje PostgreSQL przechodzą kontrolę pojemności przed
  zapisem (bariera po faktycznym odczycie). Równoczesny przydział 999–1001:
  jeden pełny sukces, jedna kolizja, trzy nowe numery, jedno pismo, jeden
  przyrost numeracji i po jednym audycie przydziału oraz dokumentu.
- Chrome na osobnej kopii SQLite: oryginalne 30 numerów zachowano, dopisano
  968 fikcyjnych numerów wyłącznie jako przygotowanie scenariusza. UMP przez
  nowe OTP wskazało 1000–1001; błąd 998/999 i wszystkie siedem tabel biznesowych
  identyczne jak przed próbą. Po poprawieniu początku na 999 powstała jedna
  pula z P999/P01A/P01C, jeden audyt przydziału i jedno pismo, bez zadania wysyłki.
- Pismo DRT/ump/2026/000003: SHA-256 zgodne z bazą, jedna strona A4,
  poprawny zakres, liczba, adresat i okres. Oryginalny PDF wyrenderowano
  i obejrzano; nie podpisywano ani nie wysyłano go do zewnętrznego urzędu.
  Jest nieoznaczony tagami PDF; ten odbiór nie dowodzi jego dostępności
  dla czytnika ekranu.
- `evidence/small-layout-order-ui-proof.json`: stan odmowy i przydziału,
  sumy danych, numer i SHA-256 PDF. Zrzuty 111/112 i PDF/render 113/114 pozostają
  prywatne. Końcowy ekran oraz całą stronę PDF obejrzano wizualnie.
- Ruff, Django check, kontrola migracji i diffu przechodzą. Bez migracji
  schematu, Dockera i zmiany głównej ewidencji. Testowy PostgreSQL zatrzymano.

Nie wykonano odbioru historycznych danych urzędu, operatorów ani infrastruktury Linux.
Kategoria III i pozytywny scenariusz M przy pełnych 299790 numerach III pozostają
otwarte. Cały cel i pozostałe wymagania z STATUS.md nadal wymagają realizacji.
