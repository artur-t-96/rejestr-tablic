# Sugestie wolnych wyróżników

Specyfikacja, sekcja 4.2 Flow 1, wymaga tego samego tekstu z innymi cyframi,
skracania, wydłużania i podmiany znaku, wyłącznie dla wolnych numerów.

## Zmiana

Przed zmianą limit 12 zwykle wypełniały inne cyfry i jeden obcięty tekst.
Przykład KOWA z cyfrą 7 zwracał dziewięć innych cyfr oraz P0KOW, P1KOW,
P2KOW. Nie pokazywał wydłużenia ani podmiany znaku. Bez wyboru cyfry
sugestie powtarzały dziesięć numerów już widocznych w wyniku.
`evidence/suggestions-before-fix.txt` dokumentuje dwa odtworzone braki.

Po zmianie lista ma najwyżej 12 unikalnych, wolnych propozycji:

- Jeśli wybrano cyfrę, najpierw wolne inne cyfry dla tego samego tekstu.
- Następnie przeplatane propozycje usunięcia, dodania i podmiany jednego znaku.
  Dla nowego tekstu preferowana jest wybrana cyfra, potem inne wolne cyfry.
- Jeśli sprawdzono wszystkie cyfry, sugerowane są tylko inne teksty,
  bez powtórzenia numerów widocznych w głównym wyniku.
- Każdy nowy tekst przechodzi dotychczasową wspólną walidację. Zachowany
  prefiks P/M, długość 3–5, wykluczenie Q i pozycje cyfr.
- Zajętość nadal pochodzi z całego województwa: rezerwacja, wysłany wniosek,
  przydział, wydanie i zbycie blokują numer; historyczny RELEASED nie blokuje.

Przeplatanie zapobiega zajęciu całej listy przez jeden rodzaj zmiany.
Nie każdy tekst ma wszystkie trzy rodzaje: trzy znaki nie mogą być skrócone,
pięć nie może być wydłużone. Przykłady KOWAL1/KOWALS w specyfikacji mają sześć
znaków i nie przechodzą jej reguły maksymalnych pięciu; walidacji nie poszerzono.
Kandydaci są mechanicznymi wariantami tekstu, bez rankingu językowego.

API i HTML używają tego samego mechanizmu. Lista nie ujawnia osoby, urzędu,
sprawy ani powodu zajętości i nie zakłada rezerwacji. Wynik jest informacyjny;
numer jest ponownie sprawdzany w transakcji tworzenia wniosku.
Nie przeszukuje się całej przestrzeni wszystkich możliwych tekstów: propozycje
obejmują najbliższe zmiany jednego znaku. Może ich być mniej niż 12.

## Weryfikacja

`evidence/suggestions-tests.txt`: 40 testów, 39 PASS/1 SKIP PostgreSQL.
Nowe przypadki: różnorodność pierwszej dwunastki, bez powtórzeń wyniku,
minimalna/maksymalna długość, część z cyframi, oba prefiksy, cyfra 0/7 i brak
wyboru, zajętość dwóch urzędów, status SOLD i historia RELEASED, brak zapisów
biznesowych, identyczne sugestie w HTML/API. Regresja wyboru, uprawnień,
alfabetu i ochrony publicznej. Generator nie dodaje nowych zapytań do bazy.

`evidence/suggestions-http-proof.json`: osiem rzeczywistych odczytów HTTP,
API GET i HTML POST z CSRF, cztery wybory na odrębnej fikcyjnej kopii.
Fixture: obcy P7KOWA przydzielony, obcy P7KOWAS zbyty, własny P7KOWB
zarezerwowany rzeczywistym `create_request`. Wszystkie trzy pominięte
w sugestiach. Nowe propozycje dla P7KOWA: P7KOW, P0KOWAS i P0KOWB,
obok dziewięciu wolnych alternatywnych cyfr. Wszystkie numery poprawne.

`evidence/suggestions-browser-proof.json`: rzeczywisty Chrome użytkownika,
KOWA/P/7 oraz A12/M/0, lista identyczna z API i fokus na wyniku. Zrzuty 142/143
obejrzane. Przez HTTP i Chrome zmienił się tylko licznik zapytań kopii;
pozostałe 26 tabel oraz wszystkie 27 tabel głównej bazy zachowane.
Hash źródeł identyfikuje testowany kod na bazie 2f302bd.

Bez migracji, operatorów, nowej próby PostgreSQL, zakończenia CAPTCHA lub
czytnika ekranu. Dowody nie potwierdzają całego WCAG ani osiągnięcia celu.
