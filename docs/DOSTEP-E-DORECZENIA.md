# Przygotowanie dostępu INT — materiały do zatwierdzenia

**Nie wysłano zgłoszenia, nie zaakceptowano regulaminu, nie zarejestrowano firmy ani urzędu.** Poniższy materiał jest projektem do uzupełnienia prawdziwymi danymi uprawnionego podmiotu i zatwierdzenia przez użytkownika. Brak danych nie zatrzymuje implementacji pozostałych elementów systemu.

## Oficjalna ścieżka

[Instrukcja dla integratorów](https://www.gov.pl/web/e-doreczenia/integracja-uslugi-e-doreczen-z-systemami-klasy-ezd) wskazuje zgłoszenie 2a i adres `test.edoreczenia@cyfra.gov.pl`. [Oryginalny formularz 2a](https://www.gov.pl/attachment/9ae9a474-2470-43a1-9ff5-248481d014d1) zawiera dane podmiotu, adresy IP, osoby kontaktowe i oświadczenie o przestrzeganiu regulaminu z miejscem na podpis.

[Dostęp dla podmiotów publicznych i niepublicznych](https://www.gov.pl/web/e-doreczenia/srodowisko-testowe-dla-podmiotow-publicznych-i-niepublicznych) stanowi odrębną ścieżkę 2b dla testowego podmiotu i ADE; obowiązują wymagania podpisu i ewentualnego pełnomocnictwa. Potwierdź z COI właściwy wariant dla producenta systemu dziedzinowego korzystającego z UA/SE API. Nie należy składać wniosku w imieniu UMP bez umocowania.

## Informacje do uzupełnienia

| Pozycja | Wartość przygotowana / brak |
|---|---|
| System | Dyna Rejestr Tablic |
| Opis | System dziedzinowy ewidencji wyróżników tablic i przydziałów pul dla województwa, z korespondencją urzędową i powiązaniem dokumentów ze sprawami EZD |
| Zakres testów | UA API v3: uwierzytelnianie, wysyłka jednego PDF, zadania, statusy i dowody; SE API v4: wyszukiwanie urzędów i potwierdzanie ADE |
| Dane testowe | Wyłącznie fikcyjne dokumenty i podmioty testowe |
| Podmiot wykonujący integrację | [pełna nazwa prawna firmy, adres, NIP, KRS — do podania] |
| Podmiot integrowany | [własny podmiot testowy albo upoważniony urząd — do ustalenia] |
| Adresy IP wyjściowe | [stałe publiczne IP dostępu INT — do podania; nie wpisywać 127.0.0.1] |
| Osoba kontaktowa | [imię, nazwisko, służbowy e-mail, telefon — do podania] |
| Obsługa incydentów | [imię, nazwisko, e-mail, telefon — do podania] |
| Akceptacja regulaminu i podpis | Uprawniona osoba, po zatwierdzeniu aktualnego regulaminu |
| ADE i nazwa systemu | Nadawca i adresat testowi INT; system rejestrowany oddzielnie przy ADE |
| Certyfikat | CSR i certyfikat uwierzytelniający zarejestrowany u operatora; klucz prywatny pozostaje lokalnie |

Pola URL powrotnego/CHOOSE_SENDER_ADE z części ZSU nie są wymaganiem obecnej wysyłki UA/SE. Nie konfigurujemy tego trybu bez potwierdzenia zakresu zgłoszenia przez COI. Lokalnego serwera nie należy udostępniać publicznie tylko w celu wypełnienia pola formularza.

## Projekt wiadomości

Adresat: test.edoreczenia@cyfra.gov.pl

Temat: Dostęp INT — integracja systemu Dyna Rejestr Tablic z UA API v3 i SE API v4

Szanowni Państwo,

przygotowujemy integrację systemu dziedzinowego „Dyna Rejestr Tablic”, służącego do ewidencji wyróżników tablic oraz przydziału pul numerów i obsługi korespondencji między urzędami. System będzie instalowany na infrastrukturze podmiotu publicznego, w osobnej instancji dla każdego województwa.

Prosimy o potwierdzenie właściwej ścieżki uzyskania dostępu integratora do środowiska INT oraz utworzenia podmiotów testowych i adresów ADE. Planowany zakres obejmuje uwierzytelnianie systemu podpisaną asercją JWT, wyszukiwanie i potwierdzanie adresów przez SE API v4, wysyłkę dokumentów PDF przez UA API v3 oraz pobieranie statusów i dowodów nadania oraz odbioru. Testy będą wykonywane wyłącznie na danych fikcyjnych.

Prosimy również o potwierdzenie aktualnych adresów API i parametru audience dla JWT, procedury rejestracji certyfikatu oraz aktualnego kontraktu wyniku zadania wysyłki. W publicznym YAML UA `MessageOperationResponseWrapperStatus` ma rozbieżność pomiędzy polami required i properties.

Dane firmy, kontaktu, adresów IP i podpisane zgłoszenie zostaną uzupełnione przed wysłaniem przez uprawnioną osobę.

Z poważaniem,
[imię i nazwisko, funkcja, pełna nazwa firmy, telefon]

## Co konkretnie blokuje test rzeczywisty

Brakuje zatwierdzonego i wysłanego zgłoszenia, przyznanych uprawnień INT, dwóch testowych ADE, zarejestrowanej nazwy systemu oraz zgodnego klucza i certyfikatu. Dokumentacja API jest publiczna, ale te uprawnienia nie wynikają z samego pobrania dokumentacji. Żadnych danych przedsiębiorstwa nie wysłano automatycznie.
