# Import ewidencji indywidualnej — 03.10.2026

Ta funkcja wprowadza historyczne wpisy modułu I na podstawie uzgodnionego
wykazu. Nie tworzy nowych wniosków, rezerwacji, decyzji, PDF ani zleceń wysyłki.
Dawne numery pism pozostają oznaczeniami ze źródła; nie są nowymi dokumentami
wygenerowanymi przez system. Import pul II/III ma osobną instrukcję
`docs/IMPORT-PUL.md`.

## Format i przygotowanie źródeł

Dostęp UMP: **Import ewidencji**, `/panel/import/`. Urzędnik powiatowy
oraz administrator techniczny nie mogą importować wojewódzkiej ewidencji.
CSV UTF-8, opcjonalnie BOM, separator średnik; do 2 MB i **500 wpisów**.
Nagłówki można pobrać z formularza. Obsługiwany jest też bezpośredni XLSX
z tymi samymi kolumnami. Przygotowanie komórek, wybór arkusza, daty Excela
i ograniczenia: [Import XLSX](IMPORT-XLSX.md). Makra i starszy XLS wymagają
przygotowania zwykłego XLSX lub CSV.

| Kolumna | Znaczenie i kontrola |
| --- | --- |
| `number` | Pełny numer indywidualny P/M, ze wspólną walidacją. Spacje i wielkość liter normalizowane; Q wykluczone. |
| `owner` | Właściciel, obowiązkowy, do 180 znaków. |
| `office_id` | Identyfikator istniejącego **aktywnego** urzędu z konfiguracji; podgląd pokazuje także nazwę. |
| `status` | ALLOCATED, ISSUED, SOLD lub RELEASED. Puste oznacza ALLOCATED. Nie importuje szkiców/rezerwacji/wniosków w toku. |
| `vin` | VIN, obowiązkowy dla ISSUED/SOLD. |
| `make`, `model` | Opcjonalna marka i model, po 80 znaków. |
| `registration_date` | RRRR-MM-DD; obowiązkowa dla ISSUED/SOLD, nie przyszła. |
| `sale_date` | RRRR-MM-DD; obowiązkowa dla SOLD, nie przyszła i nie wcześniejsza niż rejestracja. |
| `buyer` | Nabywca, do 180 znaków; wymagany przy zbyciu. |
| `letter_number` | Historyczne oznaczenie pisma, do 100 znaków. |
| `address` | Opcjonalny adres właściciela, do 300 znaków. |
| `note` | Uwaga wynikająca ze źródła. |

Obowiązkowe nagłówki: `number;owner;office_id`. Pozostałe nagłówki mogą być
pominięte, gdy ich dane nie są wymagane przez status. Powtórzone lub nieznane
nagłówki, nierówna liczba wartości, uszkodzone cudzysłowy i błędne daty są
odrzucane. Dane nie są po cichu pomijane. Pola tekstowe zachowują treść po
usunięciu zewnętrznych białych znaków; znaki formuł pozostają tekstem.

Data zbycia wymaga statusu SOLD lub dawnego RELEASED. Status SOLD pozostaje
zajęty: sprzedaż nie uwalnia automatycznie numeru. RELEASED zapisuje dawną
historię, nie zmienia ani nie zwalnia innego aktywnego wpisu tego numeru.
Może istnieć kilka dawnych zwolnionych wpisów oraz co najwyżej jeden aktywny.
Źródłowe okresy i podstawy powtórzonych historii trzeba uzgodnić przed importem.
Nie wprowadzamy fikcyjnej daty przydziału lub pierwotnego urzędnika.

Nieaktywne urzędy należy wyjaśnić i skonfigurować przed importem indywidualnym.
Ta reguła została zachowana z dotychczasowego importu; nie jest taka sama jak
obsługa nieaktywnych historycznych adresatów w imporcie pul. Nie poprawiaj
starszych numerów lub źródeł automatycznie, aby ominąć błędy.

## Przebieg i odpowiedzialność

1. Uzgodnij wykaz z oryginalną ewidencją i pismami. Wykonaj kopię bazy.
2. Wczytaj CSV lub XLSX. Podgląd pokazuje wszystkie 13 pól na dwóch tabelach, po
   100 wpisów na stronie, nazwę urzędu i polski status. Przejrzyj wszystkie
   strony. Podgląd i jego błędy nie zapisują danych biznesowych ani audytu.
3. Wyjaśnij każdy błąd. Cały plik jest blokowany, także gdy część wierszy
   jest poprawna. Zapis częściowy nie jest dostępny.
4. Podaj uzasadnienie/podstawę importu, np. oznaczenie uzgodnionego wykazu,
   i jawnie potwierdź zgodność wszystkich wpisów ze źródłami.
5. Zatwierdź konkretny podgląd. Jest związany z kontem, sesją, wersją i sumą
   dokładnych bajtów pliku, dla CSV **łącznie z BOM**, dla XLSX także
   z wybranym arkuszem. Ważność wynosi 15 minut.
   Inny lub błędny podgląd zastępuje poprzedni; stara karta nie zatwierdzi
   nowszego pliku. Dawny formularz sprzed aktualizacji trzeba wczytać ponownie.
6. Serwer ponownie sprawdza źródło, aktualne urzędy i kolizje. Cały import
   i logi powstają atomowo. Błąd po pierwszym wpisie wycofuje wszystkie wpisy
   i audyty tego importu. Aktywne numery chroni unikalny indeks bazy.

Log `plate.imported` zawiera wszystkie dane wiersza, nazwę i SHA-256 pliku, format i arkusz,
autora, urząd danych, czas i uzasadnienie. Nieznana dawna data przydziału jest
jawnie oznaczona. Oryginalne bajty CSV/XLSX i źródłowych pism należy przechowywać
w archiwum urzędu z osobną kopią; ten import zapisuje odwołanie, nie oryginalny
plik. Nie uznaje obecnego czasu importu za datę historycznego przydziału.

Ponowne zatwierdzenie tego samego pliku jest odrzucane po jego SHA-256 (dla XLSX razem z arkuszem), także
przy samych zwolnionych wpisach i zmianie nazwy pliku. Zatwierdzanie źródeł
jest serializowane na urzędzie głównym; nie używa globalnej blokady zwykłych
wniosków. Zmiana BOM, kolejności lub treści daje inną sumę: **nie jest to
pełne rozpoznawanie semantycznie powtórzonej historii**. Dane zwolnione z
innego wykazu wymagają kontroli operatora i źródeł; nie są automatycznie scalane.

## Eksport i kopia zapasowa

Eksport CSV honoruje filtry i zakres urzędu, zapisuje BOM i średniki.
Wartości mogące uruchomić formułę arkusza są zabezpieczane prefiksem apostrofu;
nie usuwamy tego znaku automatycznie podczas importu. Takie pola trzeba
uzgodnić ze źródłem. To nie jest bezwarunkowy eksport/import bez zmiany każdego
możliwego tekstu.

Eksport nie jest kopią całego systemu: nie zawiera dokumentów, audytu,
wniosków, kolejki ani daty przydziału. Wpisy z rezerwacją/wnioskiem w toku
oraz nieprawidłowe starsze numery mogą pojawić się w eksporcie i będą odrzucone
przez historyczny import. Odtwarzanie całej instalacji wykonuj przez
`backup_registry` / `restore_registry`, nie przez CSV.

## Dowody wcześniejszego etapu CSV

Poniższe wyniki dotyczą wcześniejszego wdrożenia CSV. Bieżące rozszerzenie
XLSX i końcowe wyniki są opisane w [Import XLSX](IMPORT-XLSX.md).

- SQLite **50 PASS / 2 SKIP PostgreSQL**, 52 testy, 1.474 s:
  `evidence/record-import-tests.txt`. Import, wszystkie pola i BOM, daty,
  nagłówki, limity, kolizje, role, CSRF, podgląd i token Unicode, ważność,
  stara karta/legacy formularz, paginacja, HTML, audyt i rollback oraz regresje
  rdzenia, alfabetu i dostępności formularzy.
- PostgreSQL **15 PASS**, 0.392 s:
  `evidence/record-import-postgres-final.txt`. Dwa ukończone podglądy aktywnych
  numerów → jeden zapis, jedna kolizja, dwa wpisy/dwa audyty. Ten sam plik
  zwolnionej historii w dwóch transakcjach → jeden wpis/jeden audyt, druga
  próba odrzucona. To są rzeczywiste połączenia/blokady, nie symulacja bazy.
  Pierwsze uruchomienie miało błędny selektor starszej klasy testowej;
  poprawiony końcowy przebieg obejmuje 15 testów. Nie była to awaria kodu.
- Chrome, osobna baza: OTP UMP, uszkodzony nagłówek, dwie karty z różnymi
  plikami, odmowa ze starej karty. Siedem tabel biznesowych i audyt bez zmian
  przed zatwierdzeniem. Właściwy plik zapisał dwa fikcyjne historyczne wpisy;
  stary P4ZOLW nie powstał. Bez nowych wniosków, pism, numeracji lub wysyłek.
- Rzeczywisty eksport pobrany w Chrome zawiera siedem wpisów. Wszystkie
  **13 pól** dwóch nowych wpisów porównano ze źródłem i bazą; daty 2025-01-01
  i 2025-02-01 zachowane. Nie była to próba wszystkich możliwych wartości CSV.
- Publiczne wyszukiwanie: M9JELEN z pojazdem zbytym niedostępny, P4PAST
  zwolniony dostępny, bez właściciela/VIN/nabywcy w wyniku.
- OTP Gniezna → własny wpis/daty i rozwinięty audyt; Gniezno bez importu.
  OTP Piły → ten sam link zwraca polski 404. Zrzuty 80–86 w `evidence/private/`.
  Podgląd i końcowy własny wpis sprawdzono wizualnie.
- Rzeczywista kopia i odtworzenie SQLite do nowego katalogu: wszystkie
  siedem tabel biznesowych oraz audyt identyczne, w tym nowe wpisy i ich
  pochodzenie. Sesje/OTP unieważnione. Odtworzonej aplikacji nie uruchamiano.
- Siedem tabel głównej bazy bez zmian. Maszynowy raport:
  `evidence/record-import-ui-proof.json`. PostgreSQL testowy zatrzymany.

Bez migracji schematu, Dockera i zewnętrznej korespondencji. Repozytorium
nie ma Git remote/hosted CI ani produkcyjnej ścieżki wdrożenia. Nadal otwarte:
rzeczywiste źródła urzędu i kompletność migracji, pełne WCAG/czytniki,
rzeczywiste API, infrastruktura urzędu
oraz cały końcowy odbiór systemu. Ten etap nie zamyka celu.
