# Dostęp do całych list

Stan: 03.10.2026. Usunięto ucinanie wniosków, ewidencji i pism do 300 oraz
zadań integracji i wpływów EZD do 100 pozycji. Każda z tych pięciu list ma
strony po 50 pozycji. Zakres uprawnień i filtry są nakładane przed liczeniem
oraz podziałem na strony. Kolejność: data utworzenia malejąco, następnie ID
malejąco, także przy jednakowych datach.

Nawigacja podaje zakres, liczbę wszystkich wyników i numer strony. Pozwala
przejść do następnej, poprzedniej, pierwszej i ostatniej strony. Zachowuje
parametry wyszukiwania, statusu i urzędu. Nowe filtrowanie nie przesyła starego
numeru strony. Fragment `#list-results` kieruje fokus do listy, poza zwykłą
kolejnością Tab. Przycisków nie jest tyle, ile wszystkich stron.

Pusty wynik pokazuje liczbę 0. Niepoprawny tekst numeru strony otwiera pierwszą
stronę, a numer poza zakresem ostatnią, zgodnie z `Paginator.get_page`.
Filtrowany eksport CSV obejmuje wszystkie dopasowane wpisy, niezależnie od
parametru `page`.

Listy pism/wyników/RPW nie pobierają bajtów dokumentów, podpisanych PDF,
załączników dowodowych ani payloadów wysyłki. Pobranie rzeczywistego dokumentu
pozostaje osobną operacją z własną kontrolą dostępu. Relacje i metadane dowodów
są pobierane zbiorczo, bez dodatkowego zapytania na każdy wiersz.

## API wniosków

`GET /api/requests/` nadal zwraca `items`, teraz najwyżej 50 na stronę.
Obsługuje te same filtry `q` i `status` co lista HTML oraz parametr `page`.
Odpowiedź zawiera również:

```json
{
  "items": [],
  "count": 305,
  "page": 1,
  "pages": 7,
  "page_size": 50,
  "next": "/api/requests/?q=PAGINACJA%2F&status=REJECTED&page=2",
  "previous": null
}
```

To szkic struktury; `items` w rzeczywistym niepustym wyniku zawiera obiekty
wniosków. Klient pobierający pełną listę musi podążać za `next`, aż otrzyma
`null`. Liczniki i linki dotyczą wyłącznie danych dostępnych danemu
użytkownikowi. Format POST tworzącego wniosek pozostaje ten sam.

Strony odzwierciedlają bieżącą bazę, bez utrzymywania snapshotu między
żądaniami: nowy wpis może przesunąć granicę stron. Stabilny porządek rozwiązuje
remisy dat, lecz nie jest gwarancją niezmiennego wielostronicowego odczytu
podczas równoczesnych zapisów.

## Weryfikacja

`evidence/list-pagination-tests.txt`: 69 testów, 68 PASS i jeden SKIP
wymagający PostgreSQL. Zakres: nowe listy, dostępność HTML, przekazanie urzędu,
wpływy EZD, wygasanie i walidacja API korekt. Nowe testy sprawdzają 305 pozycji
na siedmiu stronach i 155 na czterech, jednakowe daty, wszystkie ID dokładnie
raz, wszystkie role, nadawcę/odbiorcę dokumentu, zakres filtrów, pełny eksport,
błędne strony oraz niezmienność danych. Liczba zapytań jest ograniczona i SQL
list nie zawiera binarnych kolumn. Ruff PASS. Bez migracji; PostgreSQL nie
uruchamiano w tym etapie.

`evidence/list-pagination-browser-report.json`: rzeczywisty Chrome na osobnej
kopii SQLite. Gniezno loguje się jednorazowym kodem, filtruje 305 wniosków,
przechodzi Enter na drugą stronę i do siódmej, odczytuje `TEST-LISTA/000`,
zmienia filtr i wraca do pierwszej. Analogicznie odczytuje najstarszą
ewidencję, pismo, wynik integracji i RPW 1000/2026. Przy 320 px dokument ma
320 px szerokości, region nawigacji 246 px, przyciski pierwsza/poprzednia
zawijają się i mają widoczny fokus. Override przywrócono.

`evidence/list-pagination-export-proof.json`: rzeczywisty plik pobrany w Chrome
z siódmej strony, 305/305 oczekiwanych fikcyjnych właścicieli, tylko Gniezno i
status zwolniony. `evidence/list-pagination-api-proof.json`: rzeczywisty HTTP,
osobne logowanie OTP i siedem odpowiedzi API, wszystkie 305 UUID dokładnie raz
w oczekiwanej kolejności, poprawne `next`/`previous`.

Kopia zawierała celowo stworzone historyczne wiersze list. Bajty PDF w tych
wierszach skopiowano z istniejącego archiwum wyłącznie jako fixture; nie
potwierdzają poprawności nowych pism ani wpływu EZD. Fikcyjne wyniki integracji
utworzono jako zakończone, bez uruchamiania workera wysyłki i bez żądań do
operatora. Dziewięć tabel kopii oraz stare audyty zachowane po nawigacji;
dodano dwa logowania i zdarzenie eksportu. Główna baza nie służyła do
tworzenia tych wierszy.

Ten zakres nie dowodzi pełnego WCAG, retencji, dostępu do rzeczywistych usług
ani końcowego odbioru całego systemu. Cel pozostaje aktywny.
