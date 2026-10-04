# Konta urzędników i trwałe zaproszenia

Stan 03.10.2026. Ten etap obejmuje tworzenie kont przez A0, informacyjne
zaproszenie i kontrolę domen przy logowaniu. Nie jest odbiorem całego systemu
ani potwierdzeniem działania poczty urzędu.

## Działanie

A0 wybiera „Urzędy i konta → + Konto”, wpisuje adres, rolę, urząd i powód.
Adres jest normalizowany do małych liter. Duplikat różniący się wielkością
liter jest błędem formularza. Konto nie ma hasła. Aktywne nowe konto i
zaproszenie są zapisywane w jednej transakcji wraz z audytem; błąd kolejki
wycofuje również konto. Nieaktywne konto nie powoduje wysyłki. Po aktywowaniu
istniejącego konta administrator tworzy zaproszenie przez „Stan i wysyłka”.

Zaproszenie zawiera rolę, urząd i adres strony logowania. Nie zawiera OTP,
klucza, hasła ani tokenu nadającego dostęp. Urzędnik zamawia osobny kod OTP.
Zmiana konta, urzędu, listy domen lub adresu aplikacji przed wysyłką unieważnia
przygotowaną wiadomość. Suma SHA-256 chroni zapisaną treść przed wysyłką po
niezgodnej zmianie. Samo posiadanie wiadomości nie daje dostępu do danych.

Edycja konta wymaga powodu i aktualnego podpisanego formularza, ważnego
30 minut. Nieaktualny formularz nie nadpisuje późniejszych zmian. Audyt
zapisuje wcześniejsze i nowe ustawienia konta. Formularze operacji zaproszeń
są związane z administratorem, kontem i wersją zaproszenia, ważne 15 minut.

## Domeny i role

Domeny urzędu są listą JSON, np. `["urzad.gov.pl"]`. Adresy e-mail,
URL, symbole wieloznaczne oraz JSON innego typu są odrzucane. Domena jest
normalizowana, a porównanie obejmuje pełną domenę — nie jej fragment.

W profilu urzędowym pusta lista blokuje dostęp urzędników. Najpierw A0
konfiguruje listę dla urzędu. Techniczny A0 bez przypisanego urzędu zachowuje
dostęp do konfiguracji. Wyłącznie profil lokalny dopuszcza pustą listę dla
fikcyjnych danych. Skonfigurowana lista obowiązuje również lokalnie.

Kontrola działa przy zamawianiu OTP, użyciu wcześniej wydanego kodu i każdym
żądaniu aktywnej sesji. Usunięcie domeny, dezaktywacja konta/urzędu lub
niezgodna rola blokuje dostęp. Zaproszenia są dostępne wyłącznie dla A0,
z ochroną CSRF i logiem operacji; A2/A3 nie mogą nimi zarządzać.

## Kolejka i uzgadnianie

`process_account_invitations` przetwarza jedną partię do 100 wiadomości.
`--watch --interval 30` uruchamia stały proces. Lokalny launcher
`scripts/run-local.sh` uruchamia go razem z serwerem. W profilu urzędowym
`deploy/dyna-jobs.service` obejmuje ten sam krok; działanie systemd na
serwerze urzędu nadal wymaga odbioru.

- `QUEUED`: oczekuje; A0 może anulować.
- `SENDING`: proces przejął wiadomość. Inny proces jej nie wysyła.
- `LOCAL_SAVED`: rzeczywisty plik MIME zapisany lokalnie, bez SMTP.
- `ACCEPTED`: backend SMTP potwierdził przyjęcie. Nie dowodzi to odbioru.
- `CONFIG_ERROR`: brak konfiguracji przed rozpoczęciem wysyłki; po naprawie
  A0 może wznowić tę samą wiadomość.
- `REVIEW_REQUIRED`: wynik SMTP jest niepewny, treść niezgodna, proces
  przerwany albo kolejka pochodzi z odtworzonej kopii. Brak automatycznego retry.
- `CONFIRMED_SENT`: A0 zapisał potwierdzenie przyjęcia przez serwer.
- `CANCELLED`: zakończone bez dalszej wysyłki tego zaproszenia.

Dla niepewnego wyniku A0 musi zapisać powód, wynik sprawdzenia serwera i
potwierdzić weryfikację. Wznowienie jest właściwe tylko po ustaleniu, że
serwer nie przyjął wiadomości. Zapisuje się dowód opisowy, bez haseł/tokenów.
Nowe zaproszenie po zamknięciu poprzedniego może oznaczać kolejną wiadomość.
Message-ID nie zapewnia dokładnie jednej wysyłki przez SMTP.

Blokada wiersza konta i warunkowy unikalny indeks pozwalają na jedno
oczekujące/nierozstrzygnięte zaproszenie. Wysyłka jest poza transakcją.
Po upływie 2 minut przejęta operacja wymaga sprawdzenia; późno kończący się
proces nie nadpisuje wyniku uzgodnienia. Kolejka nie tworzy pism urzędowych.

Przykład dla skonfigurowanego środowiska:

```sh
.venv/bin/python manage.py process_account_invitations
.venv/bin/python manage.py process_account_invitations --watch --interval 30
```

## Kopie i wyniki weryfikacji

Migracja `0010_account_invitation` dodaje tabelę i indeks. Kopie obejmują
wiadomości i audyt. Przy odtworzeniu SQLite oraz PostgreSQL wszystkie stany
oczekujące, przejęte, wymagające konfiguracji i sprawdzenia są wstrzymywane
jako `REVIEW_REQUIRED`. Nie wznawiaj ich na podstawie samego stanu kopii:
oryginalna instancja mogła wysłać wiadomość już po wykonaniu backupu.

Finalnie: SQLite 60 testów (58 PASS, 2 pominięte wymagające PostgreSQL),
PostgreSQL 62/62 PASS. Finalne wyniki są w `evidence/account-invitation-tests-sqlite.txt` oraz
`evidence/account-invitation-tests-postgres.txt`. Obejmują transakcje,
kontrolę domen/OTP/sesji, uprawnienia, CSRF, nieaktualne formularze,
niepewne SMTP, przerwanie procesu i rzeczywiste backup/restore. PostgreSQL
sprawdza dodatkowo równoczesne tworzenie i przejęcie kolejki.
Wcześniejsze logi z oznaczeniami `initial`, `repair` i `before-*` odnoszą się
do wcześniejszych wersji testów; nie są końcowym wynikiem.

Chrome, osobna fikcyjna kopia na localhost:8775: A0 OTP → utworzenie konta
Gniezna → zaproszenie w kolejce → odmowa duplikatu → plik MIME → osobny OTP
nowego A2 → panel własnego urzędu → odmowa dostępu do zaproszeń.
Dowód: `evidence/account-invitation-browser-report.json` i zrzuty 89–92
w prywatnym katalogu evidence. Kontrola wyglądu odbyła się po poprawieniu
uruchomienia statycznych zasobów lokalnego serwera; pierwszy surowy zrzut 88
nie jest dowodem poprawnego wyglądu.

SMTP urzędu, TLS, filtracja operatora i odbiór w rzeczywistej skrzynce nie
zostały sprawdzone. Potrzebne: host/port, konfiguracja TLS i zaufania,
uprawniony nadawca, ewentualne uwierzytelnianie oraz uzgodniona skrzynka
odbiorcza do testów. Sekrety należy podać w konfiguracji serwera, bez
przesyłania ich w raporcie. Nie wysłano rzeczywistych wiadomości ani zgłoszeń.

## Usuwanie konta (04.10.2026)

Formularz konta w panelu administratora ma sekcję „Usuń konto" (wymaga powodu; własnego konta nie da
się usunąć).

- Konto, które nigdy nie pracowało w systemie, jest kasowane razem ze swoimi zaproszeniami.
- Konto z historią (wnioski, decyzje, wydania, podpisy, zdarzenia w dzienniku) jest trwale zamykane:
  traci dostęp, znika z domyślnej listy („Pokaż usunięte" je przywraca do widoku), adres e-mail jest
  zastępowany znacznikiem `usuniete-<id>@usuniete.invalid`, a imię i nazwisko zostają. W historii
  występuje jako „Imię Nazwisko (konto usunięte)".
- Dziennik audytowy jest niezmienny, więc dawny adres w starych zdarzeniach konta jest ukrywany przy
  wyświetlaniu, nie kasowany z bazy. Treść i adres zaproszeń zamkniętego konta są usuwane.
- Zdarzenia: `admin.user_deleted`, `admin.user_closed`. Testy: `registry/test_account_removal.py`.
