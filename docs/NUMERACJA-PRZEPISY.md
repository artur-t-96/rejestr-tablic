# Numeracja: źródła i odbiór poprawki alfabetu

Stan 03.10.2026. Jest to dokument implementacji i dowodów, nie opinia prawna
ani odbiór całego systemu. Pełny goal pozostaje aktywny.

## Oficjalne źródła i zakres odczytu

| Źródło | Sprawdzone fragmenty i wynik |
| --- | --- |
| [Rozporządzenie 2024/1709](https://api.sejm.gov.pl/eli/acts/DU/2024/1709/text.html) | § 30–32 i załącznik 13: 25 liter bez Q, długość części indywidualnej, sekwencje zmniejszonych i tymczasowych, P/M. |
| [Nowelizacja 2025/939](https://api.sejm.gov.pl/eli/acts/DU/2025/939/text.pdf) | Cały akt, 1 strona, także render. Zmienia § 31 ust. 3 i § 32 ust. 2: indywidualne mogą używać wybranej litery województwa bez wyczerpania pierwszej. ELI wskazuje wejście 30.07.2025. |
| [Nowelizacja 2026/891](https://api.sejm.gov.pl/eli/acts/DU/2026/891/text.pdf) | Cały akt, 2 strony, także render. Zmiany procedury i adresu doręczeń elektronicznych oraz wyróżników powiatów poza Wielkopolską. Nie zmienia alfabetu ani wyboru P/M dla indywidualnych. |
| [Prawo o ruchu drogowym, tekst ujednolicony](https://eli.gov.pl/eli/DU/1997/602/uj/pol/pdf) | Odczyt art. 73a na stronach 129–130; render strony 130. Pobrany dokument ma 322 strony i datę redakcyjną 20.08.2026. Nie przeprowadzono audytu wszystkich artykułów ani dat wejścia wszystkich zmian. |
| [Profesjonalna rejestracja, tekst jednolity 2023/2616](https://api.sejm.gov.pl/eli/acts/DU/2023/2616/text.html) | § 14: format z wyróżnikiem powiatu i literą P w dalszej części; numer nadaje starosta. To inny schemat niż tymczasowe P0 0001. |
| [Nowelizacja profesjonalnej rejestracji 2026/1128](https://api.sejm.gov.pl/eli/acts/DU/2026/1128/text.pdf) | Treść normatywna na stronie 1, także render: odesłanie do aktualnego rozporządzenia, opłaty, nowe formularze i nazwa powiatu. Nie zmienia § 14 numeracji. Nowych formularzy profesjonalnej rejestracji nie wdrażano w tym etapie. |

Metadane ELI rozporządzenia 2024/1709 pobrano ponownie. Wskazują wyłącznie
nowelizacje 2025/939 i 2026/891. Metadane profesjonalnej rejestracji wskazują
nowelizację 2026/1128. Manifest URL, rozmiarów i SHA-256:
`evidence/plate-numbering-legal-sources.json`; oryginały i rendery:
`evidence/private/legal-*`. Nie pomijano weryfikacji TLS przy pobieraniu.

## Zmienione zachowanie

`validate_part` odrzuca Q na każdej pozycji części indywidualnej o długości
3, 4 lub 5. Nadal dopuszcza legalne B, D, I, O, Z i cyfry na dwóch ostatnich
pozycjach. Komunikat i instrukcja na stronie publicznej wyjaśniają wyłączenie Q.
P i M są prezentowane jako równorzędne wybory województwa dla modułu I.

Walidacja obejmuje HTML, publiczne API, formularz i usługę wnioskowania,
podgląd oraz zatwierdzenie importu. Ponowne sprawdzenie przed złożeniem,
akceptacją, pierwszym wydaniem i przywróceniem zapobiega przejściu starszego
niepoprawnego numeru do tych etapów. Odmowa lub zwolnienie nie wymagają
zmiany niepoprawnego numeru w historii. To nie jest automatyczna migracja
ewidencji ani unieważnienie wcześniej wydanej tablicy.

## Dowody weryfikacji

- `python manage.py test registry.tests_plate_alphabet registry.tests.CoreTests --noinput`:
  **32 PASS**, 0.980 s; zapis `evidence/plate-alphabet-tests.txt`.
- 11 nowych testów sprawdza wszystkie 25 liter, Q we wszystkich pozycjach,
  normalizację, format cyfr, oba formularze, HTML/API, usługę, import,
  wybór M i blokadę starszych niepoprawnych szkiców/akceptacji/wydania/przywrócenia.
  Symulacja dawnego Q w testach jest jawna; nie zmienia danych działającej aplikacji.
- Chrome, osobna istniejąca baza `var/business-ui-20261003`: ABQ + M + 9 →
  komunikat bez wyniku dostępności; BIOZ + M + 9 → M9BIOZ dostępny i link do
  wniosku; formularz przenosi numer; M9ABQ z fikcyjnym właścicielem i znakiem
  TEST/ALFABET/01 → błąd pola, bez zapisu. Rendery ekranów 63 i 64 sprawdzono wizualnie.
- Zrzuty: `evidence/private/62-alphabet-q-error.png`,
  `63-alphabet-m-valid.png`, `64-alphabet-request-rejected.png`.
- `manage.py check`, `makemigrations --check --dry-run`, Ruff i
  `git diff --check`: PASS. Nie jest potrzebna migracja schematu.
- Porównano wszystkie wiersze sześciu tabel biznesowych obu baz przed i po:
  bez zmian, nie tylko zgodna liczba. Zapis:
  `evidence/plate-alphabet-data-preservation.json`.

W głównej bazie zachowano 5 wniosków, 5 wpisów, 12 pism, 1 pulę, 30 numerów
puli i 3 liczniki. Osobna baza zachowała odpowiednio 9, 5, 18, 5, 543 i 3.
W głównej bazie wykryto wcześniejszy przydzielony numer demonstracyjny
P8UIQA; pozostał bez zmian razem z dokumentami. Pierwsze wydanie jest teraz
blokowane. Ewentualna korekta odbywa się przez uzasadnione zwolnienie UMP
i nowy wniosek, nie przez zmianę nieedytowalnego numeru lub starych PDF.

## Otwarte rozstrzygnięcia i praca

1. Unikalność: specyfikacja porównuje pełny numer, art. 73a ust. 4 mówi o
   wyróżniku indywidualnym, § 32 ust. 1 o identycznych tablicach. Przeczytanie
   obu przepisów nie zastępuje uzgodnienia ich zastosowania z urzędem.
   Nie zmieniono modelu unikalności ani danych na podstawie samego brzmienia jednego przepisu.
2. Kategoria III: rekomendowany roboczo profil tymczasowy wynika z zestawienia
   kompetencji UMP z art. 73a ust. 1 pkt 2 i procesu w specyfikacji. Jest to
   wniosek z porównania, nie potwierdzenie intencji autora specyfikacji.
   Profesjonalnych tablic do jazd testowych nie można uznać za tę samą kategorię.
3. Rozszerzenie roboczego profilu tymczasowego po 9999 i kontrolę M w pulach
   wdrożono w kolejnym etapie, z dowodami w `docs/POJEMNOSCI-PUL.md`.
   Osobny import wcześniejszych przydziałów wdrożono w `docs/IMPORT-PUL.md`;
   pozostają uzgodnienie i wprowadzenie rzeczywistych źródeł, potwierdzenie
   kategorii III oraz pozytywny scenariusz M na pełnej bazie III. Ten zakres
   nie dowodzi pełnej zgodności modułów II/III z przepisami.
4. Pozostają rzeczywiste API, pełny odbiór ról, dostępności, podpisów,
   wdrożenia urzędowego i końcowy raport zgodności wszystkich wymagań.

Nie uruchamiano Dockera, pełnej lokalnej bramki integracyjnej ani testów na
infrastrukturze urzędu. Repozytorium nadal nie ma Git remote, hosted CI ani
produkcyjnej ścieżki wdrożenia; etap jest dostarczeniem lokalnym.
