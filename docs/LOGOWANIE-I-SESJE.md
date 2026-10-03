# Logowanie, powrót do sprawy i nieaktualne formularze

Stan: 03.10.2026. Zakres tego etapu: powrót po OTP i bezpieczne odrzucenie nieaktualnego formularza. Nie jest to pełny audyt bezpieczeństwa ani dostępności sesji.

## Zachowanie

Wejście do chronionego wniosku bez zalogowania prowadzi do logowania OTP. Po poprawnym kodzie aplikacja otwiera ten sam wniosek, a nie pulpit. Zamówienie nowego kodu zachowuje docelowy ekran. Kod błędny, wykorzystany lub wygasły nie daje dostępu.

Cel powrotu musi być względnym adresem zaczynającym się od `/panel/`. Adresy zewnętrzne, protokoły, znaki sterujące, odwrotne ukośniki i nadmiernie długie wartości są odrzucane. Walidacja odbywa się przed zamówieniem kodu i ponownie przed przekierowaniem po OTP. Samo przekierowanie nie nadaje uprawnień: urząd nadal nie może odczytać sprawy innego urzędu.

Sesja Django zachowuje dotychczasowy okres 3600 sekund i cookie HttpOnly/SameSite=Lax, z Secure i HTTPS w profilu urzędowym. Poprawne OTP zmienia identyfikator sesji i token CSRF. Formularz otwarty przed ponownym logowaniem może mieć nieaktualny token. Serwer odrzuca jego zapis HTTP 403 i pokazuje polski komunikat z instrukcją powrotu do formularza. Odrzucona operacja nie jest automatycznie ponawiana. API zwraca polski błąd JSON, bez wewnętrznej przyczyny CSRF. Odpowiedź ma `Cache-Control: no-store`.

Jeśli formularz został odrzucony, wróć przyciskiem Wstecz w przeglądarce. Zabezpiecz potrzebne niezapisane dane zgodnie z procedurą urzędu, zanim odświeżysz stronę. Następnie zaloguj się i ponownie sprawdź formularz. Zachowanie pól przy powrocie Wstecz zależy od przeglądarki i nie jest gwarantowane. System nie przechowuje tu szkicu ani danych właściciela w localStorage.

## Weryfikacja

`evidence/authentication-regression.txt`: 36 PASS, bez pominięć. Osiem testów logowania i CSRF oraz regresja siedmiu testów dostępności i 21 testów rdzenia. Obejmują rzeczywiste wygenerowanie OTP w testowym backendzie poczty, zmianę identyfikatora sesji, bezpieczny powrót, odmowę przekierowań zewnętrznych, izolację spraw urzędów, wygaśnięcie rekordu sesji oraz odrzucenie starego tokenu po OTP bez zapisu wniosku. Nie uruchamiano PostgreSQL; ten zakres nie zmienia blokad ani modelu danych.

`evidence/authentication-browser-report.json`: osobna baza na porcie 8772, fikcyjne konto Gniezna, rzeczywista przeglądarka Chrome w profilu użytkownika. Bezpośredni link do W/2026/00003 → OTP → ten sam wniosek. Następnie nowy formularz w pierwszej karcie → wylogowanie i ponowne OTP w drugiej → zapis starego formularza → polski HTTP 403. Odczyt bazy potwierdził trzy dotychczasowe wnioski, brak sprawy TEST/CSRF/2026 oraz brak rezerwacji P9ZOLW. Zrzuty pozostają prywatne, z uwagi na dane interfejsu przeglądarki i lokalne dane pokazowe.

Wygaśnięcie sesji sprawdzono testem po zmianie daty ważności jej rekordu. Nie wykonano godzinnego oczekiwania w Chrome ani automatycznego odzyskania niezapisanych danych.

## Pozostałe wymagania

Ostrzeżenie i przedłużanie opisano w kolejnym etapie poniżej. Otwarte pozostają odzyskanie szkicu po ponownym uwierzytelnieniu z ochroną przed zmianą konta oraz kontrola tego procesu czytnikiem ekranu. Te poprawki nie dowodzą pełnej zgodności WCAG 2.1 AA.

Oficjalne podstawy: [sesje Django 5.2](https://docs.djangoproject.com/en/5.2/topics/http/sessions/), [ustawienie własnego widoku odmowy CSRF](https://docs.djangoproject.com/en/5.2/ref/settings/#csrf-failure-view) i [WCAG 2.1 — czas na wykonanie czynności](https://www.w3.org/WAI/WCAG21/Understanding/timing-adjustable.html).

## Ostrzeżenie i przedłużanie czasu pracy — 03.10.2026

Domyślny czas logowania nadal wynosi godzinę. Aktywna karta sprawdza rzeczywisty termin w tabeli sesji około co 20 sekund i po powrocie do karty. Dwie minuty przed terminem pokazuje ostrzeżenie. Sam odczyt nie zapisuje sesji, nie przesuwa terminu i nie tworzy zdarzenia przedłużenia. Uprawnienia w API i ważność sesji są kontrolowane przez serwer, niezależnie od zegara przeglądarki.

„Przedłuż czas logowania” w ostrzeżeniu lub „Przedłuż logowanie” w nagłówku wykonuje POST z ochroną CSRF. Potwierdzone przedłużenie odnawia termin w bazie, bez zmiany identyfikatora sesji i tokenu formularza. Wpisane dane pozostają na stronie, a fokus wraca do ostatnio używanego elementu treści. Każde przedłużenie jest audytowane. Nie ma limitu dziesięciu przedłużeń; test potwierdza możliwość co najmniej dziesięciu.

Kontrola porównuje konto, rolę i urząd z kontekstem otwartego ekranu. Zmiana tego kontekstu w innej karcie blokuje przedłużenie starego ekranu. Po potwierdzonym wygaśnięciu lub zmianie konta skrypt blokuje wysłanie starego formularza, pozostawiając pola w tej karcie. Link logowania otwiera nową kartę. Nie odświeżamy automatycznie starego tokenu po ponownym logowaniu ani nie wysyłamy starych danych jako inne konto. Pełne odzyskanie szkicu pozostaje osobnym zadaniem.

Przy problemie połączenia nie pokazujemy fikcyjnego potwierdzenia przedłużenia. Bez JavaScript dostępny jest formularz przedłużenia z normalnym przeładowaniem strony; należy wcześniej zapisać pracę. Tego wariantu nie sprawdzono w przeglądarce z wyłączonym JavaScript. Przy dużym powiększeniu ostrzeżenie ogranicza wysokość do obszaru widoku i przewija się klawiaturą we własnym regionie.

Dowody: `evidence/session-control-regression.txt` — 46 PASS (10 testów sesji, 8 logowania, 7 dostępności i 21 rdzenia). Po końcowych zmianach: `evidence/session-control-final-regression.txt` — 17 PASS dla sesji i HTML/dostępności. Sprawdzono brak odnowienia przy GET, dziesięć przedłużeń, CSRF, zachowanie tokenu i możliwość zapisu po przedłużeniu, odmowę dla wygasłej sesji, nieaktywnego urzędu, innego konta lub zmienionego urzędu, lokalny powrót i wszystkie role. Nie uruchamiano PostgreSQL w tym etapie; model danych i mechanizmy blokad nie zmieniły się.

W Chrome na osobnej bazie skrócono termin pojedynczej sesji, bez zmiany domyślnej polityki godzinnej. To przyspieszony scenariusz, nie godzinne oczekiwanie. Ostrzeżenie → Enter → faktyczny nowy termin w bazie → zachowane pola i fokus; przy 400% rzeczywisty viewport 320 px, region szerokości 288 px i wysokości mieszczącej się w widoku, przewijany klawiszem ArrowDown. Powiększenie przywrócono do 100%. Raport: `evidence/session-control-browser-report.json`; zrzuty pozostają prywatne.

Osobno doprowadzono testową sesję do faktycznego wygaśnięcia. Chrome pokazał komunikat, pozostawił wpisane pola i zablokował próbę wysłania formularza, kierując fokus na ostrzeżenie. Odczyt bazy potwierdził trzy dotychczasowe wnioski oraz brak obu nowych numerów i spraw użytych w próbach. Nie zmieniano terminu sesji w głównej bazie. Odzyskanie starego formularza po kolejnym logowaniu nie było przedmiotem tej próby.

W3C opisuje wariant ostrzeżenia dającego co najmniej 20 sekund na proste przedłużenie oraz możliwość co najmniej dziesięciu przedłużeń. Przy normalnej pracy aktywnej karty nasz próg 120 sekund daje zapas na odczyt stanu. Nie jest to deklaracja formalnej zgodności: czytniki ekranu, uśpienie urządzenia, ograniczanie pracy kart w tle, awarie sieci, wszystkie obsługiwane przeglądarki i pełny audyt WCAG pozostają do sprawdzenia.


## Konta i domeny — uzupełnienie 03.10.2026

Zaproszenia tworzy A0; są przetwarzane przez osobną trwałą kolejkę.
Lista domen jest sprawdzana przy zamawianiu i użyciu OTP oraz przy aktywnej
sesji. W profilu urzędowym brak listy blokuje dostęp urzędników.
Szczegóły operacji, audytu i dowodów: `KONTA-I-ZAPROSZENIA.md`.
