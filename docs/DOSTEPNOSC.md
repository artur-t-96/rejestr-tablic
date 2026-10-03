# Dostępność interfejsu — etap weryfikacji

Stan: 03.10.2026. Docelowe wymaganie specyfikacji to WCAG 2.1 AA. Pełna zgodność pozostaje **niepotwierdzona**; poniższe wyniki dowodzą tylko wskazanego zakresu.

## Zmiany i ich cel

- Osiemnaście ekranów otrzymało opisowe tytuły kart. Szczegóły wniosku, wpisu, puli i podpisu zawierają identyfikator dokumentu, bez nazwiska właściciela. Ekrany wpływów EZD, wznowienia i braku uprawnień miały już osobne tytuły.
- Arkusz stylów i skrypt mają wersjonowane adresy. Kontrola głównej aplikacji ujawniła stary skrypt w pamięci podręcznej Chrome; zmiana adresu zapewnia pobranie poprawionej obsługi fokusu po aktualizacji.
- Wskaźnik fokusu zmieniono z żółtego na granatowy: kontrast z białym tłem wzrósł z 2,15:1 do 7,31:1. Obramowania pól mają ponad 3:1. Dziesięć konkretnych par kolorów sprawdzono obliczeniowo, bez uogólniania na wszystkie stany i CAPTCHA.
- Formularz z błędami pokazuje wspólne podsumowanie. Fokus przechodzi do niego po załadowaniu strony, również po użyciu fragmentu `#main`. Link błędu prowadzi do właściwego pola. Django zachowuje powiązanie błędu przez `aria-invalid` i `aria-describedby`. Komunikaty błędów mają rolę alertu, pozostałe komunikaty rolę statusu.
- Publiczny wynik otrzymuje nazwany region i fokus po sprawdzeniu. Link pomijający menu prowadzi do `main`. Obsługa działa także przy zwykłym przesłaniu formularza i bez JavaScript: błędy i linki są w HTML, natomiast automatyczne ustawienie fokusu wymaga JavaScript.
- Nieaktywne pola wniosku są ukrywane i wyłączane. Moduł I nie wymaga liczby numerów puli; dla II/III liczba i uzasadnienie nadal są wymagane na serwerze. Numer i VIN mają błędy przy właściwych polach. Potwierdzenie zapisania wniosku o pulę nie deklaruje rezerwacji indywidualnego numeru.
- Nagłówek, formularze, długie teksty i przyciski zawijają się przy małej szerokości. Tabele przewijają się w nazwanym regionie, który otrzymuje fokus klawiatury tylko wtedy, gdy faktycznie przekracza szerokość. Dodano brakujące podpisy tabel. Tryb wymuszonych kolorów zachowuje obramowania oraz wskaźnik fokusu.

Podstawa do oceny: [tytuły stron](https://www.w3.org/WAI/WCAG21/Understanding/page-titled.html), [kontrast elementów interfejsu](https://www.w3.org/WAI/WCAG21/Understanding/non-text-contrast.html), [kontrast tekstu](https://www.w3.org/WAI/WCAG21/Understanding/contrast-minimum.html) oraz [powiadomienia o błędach formularzy](https://www.w3.org/WAI/tutorials/forms/notifications/). Są to oficjalne materiały W3C; wdrożenie wskazanych technik nie dowodzi spełnienia wszystkich kryteriów.

## Dowody

`evidence/a11y-core-regression.txt`: 38 testów, 37 PASS i 1 SKIP wymagający PostgreSQL. Zakres: siedem testów HTML/formularzy, 21 testów rdzenia i regresja ochrony publicznej. Sprawdzono HTML 17 kombinacji strony i roli: obywatel, urząd powiatowy, UMP i administrator; tytuły, jedno `h1`, `main`, identyfikatory i powiązania etykiet. Osobno szczegóły wniosku, wpisu, puli i podpisu. Nie są to testy czytnika ekranu ani dowód całego WCAG.

`evidence/a11y-browser-report.json`: rzeczywista przeglądarka Chrome w profilu użytkownika, oddzielna baza lokalna na porcie 8771. Powiększenie Chrome 400% dało rzeczywisty viewport 320 CSS px; sama funkcja override narzędzia nie zmieniła szerokości, dlatego nie stanowi dowodu testu mobilnego. Zmierzone szerokości dokumentów wynoszą 320 px, bez poziomego przewijania całej strony, dla publicznego wyniku, błędnego wniosku i szczegółów wniosków I/III.

W Chrome sprawdzono link „Przejdź do treści”, Tab do pola, wpisanie błędnego wyróżnika, podsumowanie, aktywację linku błędu klawiszem Enter, poprawny wynik i jego fokus. Urzędnik zalogował się OTP, poprawił błędny wniosek I i zapisał go bez ukrytej liczby puli; następnie zmienił moduł na III i zapisał wniosek o dwa numery. To rzeczywiste fikcyjne wnioski z PDF-ami w osobnej bazie. Nie wysyłano korespondencji do operatora.

Tabela wniosków ma region szerokości 246 px i zawartość 555 px, `tabindex=0`, dostępną nazwę i przewija się klawiszem ArrowRight. Zrzut natywnego okna potwierdza widoczny fokus przy 400%. Powiększenie oraz override przywrócono po próbie. Zrzuty są prywatne: `evidence/private/32-a11y-table-focus-400.png` i `33-a11y-wniosek-III.jpg`. Zrzut full-page przy 400% był przycięty przez narzędzie i nie jest traktowany jako pełny dowód wizualny.

`evidence/a11y-contrast-report.json`: obliczenia dziesięciu par kolorów według luminancji względnej sRGB, z rzeczywistymi wartościami CSS i progami właściwymi dla danej pary. Ruff, sprawdzenie składni JavaScript i Django check zakończyły się poprawnie. Zmiana nie wymaga migracji bazy.

## Pozostały odbiór

Otwarte: ręczna kontrola wszystkich kryteriów A/AA i wszystkich ekranów/stadiów, czytniki VoiceOver/NVDA, powiększenie tekstu 200%, odstępy tekstu, pełna kolejność fokusu każdej roli, kontrast wszystkich stanów i elementów natywnych, tryb wymuszonych kolorów w obsługiwanym systemie, urządzenia mobilne i inne przeglądarki, CAPTCHA po potwierdzeniu użytkownika, dostępność PDF/UA oraz obsługa wygaśnięcia sesji i czasu na pracę. Żadnego z tych punktów nie oznaczono jako spełnionego na podstawie samego HTML lub testów rdzenia.

Docelowa deklaracja dostępności i formalny odbiór przez urząd wymagają pełnego audytu. Ten etap usuwa konkretne przeszkody, ale nie kończy całego celu.

Aktualizacja historii: tabela zmian ma podpisy, nagłówki wierszy/kolumn i nazwany
region przewijania. Po naprawie minimalnej szerokości kart: rzeczywista szerokość
DOM 320 px, dokument 320 px, otwarty region 220 px / zawartość 330 px, tabindex=0
i ArrowRight przesuwa go o 40 px. Override zadziałał w tym przebiegu, co
potwierdzono pomiarem DOM; przywrócono go. Enter rozwija elementy details.
To dodatkowy zakres odbioru, nie ocena wszystkich kryteriów lub czytnika ekranu.
Dowody i ograniczenia: `AUDYT-I-HISTORIA.md`.

## Aktualny odbiór publiczny według 50 kryteriów (03.10)

`WCAG-PUBLICZNY.md` zawiera macierz wszystkich kryteriów A/AA i konkretne
granice dowodu. Przejścia klawiatury, odstępy tekstu (również 320 px),
natywne 200% Chrome, formularz/błędy/wynik oraz widoczne ograniczenia.
Instrukcja została powiązana z polem i błędem; 32 PASS/1 SKIP PostgreSQL.
Axe-core 4.13.0 bez naruszeń w zapisanych przebiegach; pozostawił gradient do
ręcznej oceny. Obliczenia końców gradientu spełniły 4,5:1. Brak zakończenia
CAPTCHA i czytnika ekranu nadal wyklucza deklarację pełnej zgodności.
