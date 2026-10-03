# Serie i wyczerpanie pojemności pul

Stan 03.10.2026. Implementacja lokalna i dowody fikcyjnych scenariuszy; pełny
odbiór systemu i klasyfikacja modułu III przez urząd pozostają otwarte.

## Reguły i źródła

[Rozporządzenie 2024/1709](https://api.sejm.gov.pl/eli/acts/DU/2024/1709/text.html),
§ 30 ust. 2 pkt 6, określa serię cyfrową tablic tymczasowych oraz jej kontynuację.
§ 31 ust. 1 i 3 określa wyłączenia liter i warunek użycia drugiej litery
województwa. [Zmiana 2025/939](https://api.sejm.gov.pl/eli/acts/DU/2025/939/text.pdf)
wyłącza z tego ostatniego warunku tablice indywidualne. Oba fragmenty odczytano
ponownie w tym etapie. Zakres przeglądu nowelizacji i nierozstrzygnięte kwestie
opisuje `docs/NUMERACJA-PRZEPISY.md`.

Moduł III używa nadal roboczej rekomendacji kategorii tymczasowej. Specyfikacja
nie podaje formatu, a urząd nie potwierdził kategorii. Ten etap realizuje pełną
pojemność wybranego profilu, nie potwierdza jego zastosowania do rzeczywistych
„tablic do badań” ani profesjonalnej rejestracji.

| Pozycja w prefiksie P8 | Numer |
| --- | --- |
| 1 | P80001 |
| 9999 | P89999 |
| 10000 | P8001A |
| 10998 | P8999A |
| 10999 | P8001C |
| 29979 | P8999Y |

Litery serii: `ACEFGHJKLMNPRSTUVWXY`. Numery 001–999 przechodzą w ramach
każdej kolejnej litery; zera i niedopuszczalne litery nie powiększają pojemności.
Pierwsze 9999 pozycji zachowuje dotychczasowe numery. Limit pojedynczego
przydziału wynosi nadal 10 000 pozycji, więc pełną pojemność przydziela się
kilkoma pulami. Nie jest potrzebna migracja schematu ani zmiana archiwalnych PDF.

## Kontrole przed zapisem

Kontrolę wszystkich sześciu przejść pomiędzy układami modułu II uzupełniono
w kolejnym etapie: [Kolejność pul II](KOLEJNOSC-PUL-II.md). Opis i wyniki niżej
dotyczą wcześniejszego etapu kontroli III oraz zmiany P na M.

- Kontynuacja III od pozycji 10000 wymaga zapisania wszystkich 9999 numerów
  cyfrowych danego prefiksu. Jeden nowy przydział może uzupełnić koniec serii
  cyfrowej i rozpocząć literową; wcześniej sprawdzana jest kolizja całego zakresu.
- Nowa pula II z M wymaga zapisanych wszystkich 17 379 poprawnych numerów P.
- Nowa pula III z M wymaga wszystkich 299 790 numerów pod P0–P9, obejmujących
  serię cyfrową i literową. Wybór M w module I pozostaje dostępny bez tej blokady.
- Liczy się rzeczywista ewidencja unikalnych `PoolSlot.number`, zgodna z formatem
  danej kategorii. Sam koniec zakresu, deklaracja liczby lub najwyższy numer
  nie dowodzą pokrycia pojemności. Historyczne i wygasłe pule nadal liczą się
  jako przydzielone; oznaczenie wydania nie zwalnia ich numerów.
- Niespełnienie warunku wycofuje decyzję i cały zapis: bez nowej puli, numerów,
  odpowiedzi PDF, powiadomienia i zwiększenia licznika pisma.

Unikalny indeks numeru oraz dotychczasowa transakcja chronią kolizję między
dwoma przydziałami. Kontrola pojemności nie otwiera opcji usuwania historycznych
numerów. Nie przeprowadzono w tym etapie osobnego wyścigu dwóch decyzji
przechodzących granicę serii.

## Dowody

- SQLite: 51 PASS, 2.153 s — 11 nowych testów pojemności, obsługa pul w HTTP,
  powiadomienia i rdzeń. `evidence/pool-capacity-tests.txt`.
- Host-native PostgreSQL: 12 PASS, 1.029 s — 11 testów pojemności z rzeczywistymi
  zapytaniami regex oraz istniejący test dwóch równoczesnych wydań tego samego
  numeru. `evidence/pool-capacity-postgres-tests.txt`.
- Test pozytywny M w II zapisuje 17 378 poprawnych numerów P, potwierdza odmowę,
  dodaje ostatni i potwierdza przydział M001. Pula historyczna jest wygasła.
- Dla III sprawdzono wszystkie wygenerowane 29 979 unikalnych wyróżników i ich
  format pod każdą cyfrą P. Sprawdzono odmowę M dla niepełnej ewidencji oraz
  pozytywną kontynuację konkretnego prefiksu. Nie zapisano w teście pełnej
  bazy 299 790 numerów i nie wykonano pozytywnego przydziału M w III.
- Chrome, osobna kopia `var/pool-capacity-ui-20261003`: fikcyjne przydzielenie
  9997 numerów P8 przez usługi aplikacji, nowy wniosek powiatu o cztery numery,
  OTP UMP, M8 odrzucone przy 10004/299790. Porównanie wszystkich wierszy siedmiu
  tabel przed i po odmowie potwierdza brak zmian.
- Poprawiona decyzja P8, pozycje 9998–10001: wniosek W/2026/00011 zaakceptowany,
  numery P89998, P89999, P8001A i P8002A. Gniezno przez OTP widzi własną pulę
  i wydaje P8001A ze sprawą TEST/CAPACITY/WYDANIE/01; wykorzystanie 1/4.
- PDF DRT/ump/2026/000011 ma poprawny SHA-256, zakres i skończony okres.
  Jedną stronę wyrenderowano i sprawdzono wizualnie. Powiadomienie autora
  powstało jako QUEUED z zerową liczbą prób i poprawną sumą niezmiennej treści.
  Nie uruchamiano dla niego wysyłki zewnętrznej.
- Raport: `evidence/pool-capacity-ui-proof.json`; zrzuty 66–68 i PDF/render 69
  w `evidence/private/`. Główne sześć tabel biznesowych zachowano w całości,
  porównując sumy wszystkich wierszy: `evidence/pool-capacity-primary-preserved.json`.

Fikcyjna pula historyczna nie jest dowodem rzeczywistych przydziałów UMP.
Osobny proces PostgreSQL po testach zatrzymano; Docker nie był używany.

## Wdrożenie istniejącej ewidencji

Przed pracą na danych urzędu trzeba uzgodnić i wprowadzić historyczne pule,
również wygasłe, wraz z numerami i pochodzeniem przydziałów. W kolejnym etapie
wdrożono osobny import historycznych wykazów II/III: `docs/IMPORT-PUL.md`.
Uzgodnienie rzeczywistej ewidencji pozostaje otwartym wymaganiem wdrożeniowym.
Nie wolno odblokowywać M
przez dopisanie fikcyjnych numerów, ustawienie maksymalnego końca zakresu ani
uznanie brakującej historii za wyczerpaną pojemność.

Pozostają: potwierdzenie kategorii III i zasad historycznych przydziałów,
uzgodnienie i import rzeczywistych źródeł, pozytywny scenariusz M w pełnej bazie III,
rzeczywiste integracje, odbiór infrastruktury i pełny raport zgodności.
