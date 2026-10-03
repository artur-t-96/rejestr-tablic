# Odbiór serwisu publicznego według WCAG 2.1 A/AA

Historyczny przebieg: 03.10.2026, baza `93e9b49`, uzupełniona powiązaniem instrukcji z polem.
Zakres tego przebiegu: anonimowe sprawdzanie tablic, błędne dane, wyniki,
widoczny stan wymaganej weryfikacji i limit HTTP 429. Nie obejmuje zakończenia
CAPTCHA, logowania OTP, paneli urzędników, dokumentów PDF ani formalnej
urzędowej deklaracji. **Pełna zgodność nadal nie jest potwierdzona.**
Uzupełnienie 03.10 na `18d8829`: natywne anulowanie kliknięcia formularza,
opisane poniżej i w `evidence/public-pointer-proof.json`.

Aktualizacja końcowa: kod `772378a`, `ODBIOR-CAPTCHA.md` oraz
`evidence/final-public-acceptance-proof.json`. Zgoda została otrzymana;
CAPTCHA ukończono rzeczywiście, sprawdzono wygaśnięcie, limit i ponowienie,
klawiaturę i anulowanie wskaźnika. Macierz poniżej uwzględnia te nowe próby.
VoiceOver włączono tymczasowo, jednak wypowiedziany wynik nie był dostępny
w narzędziu; przywrócono ustawienie. Pełne AA pozostaje niepotwierdzone.
Opisy starszych przebiegów poniżej zachowują historyczny zakres.

Podstawa kryteriów: [oficjalne WCAG 2.1 W3C](https://www.w3.org/TR/WCAG21/).
Automat: [axe-core, oficjalny projekt Deque](https://github.com/dequelabs/axe-core),
wersja 4.13.0 pobrana z npm z wyłączonymi skryptami instalacji. Automat wspiera
ocenę; jego wynik nie zastępuje ręcznej kontroli ani badania technologii
asystujących. Uruchomiono tagi wcag2a, wcag2aa, wcag21a, wcag21aa.

## Ustalenia i zmiana

Instrukcja była widoczna nad formularzem, lecz pole wyróżnika nie miało
powiązanego opisu. Instrukcja jest teraz help_text pola. Django tworzy
id_part_helptext i aria-describedby, a przy błędzie dodaje id_part_error.
Nie dodano podwójnej instrukcji ani nadpisania powiązania błędu.

W rzeczywistym Chrome anonimowy formularz był dostępny na osobnej kopii
SQLite, z osobnymi nazwami cookies. Klawiatura: Tab → pominięcie menu →
pola → Enter → podsumowanie błędów → link błędu → poprawka → wynik. Fokus
trafiał do main, id_part, form-errors i availability-result odpowiednio do
czynności. P5ANNA był niedostępny, dziewięć pozostałych wariantów dostępnych,
bez danych właściciela i bez zarezerwowania numeru.

Dodatkowy arkusz wyłącznie w prywatnym serwerze testowym wymuszał line-height
1.5, letter-spacing .12em, word-spacing .16em oraz margin-bottom 2em dla
akapitów. Zmierzono odpowiednio 28.5 px, 2.28 px i 38 px dla lead 19 px.
Przy 320 px dokument miał 320 px, przy 900 px miał 900 px. Wynik z najdłuższym
pięcioliterowym wyróżnikiem, instrukcje i błędy nie utraciły treści.
Pierwszy eksperyment z inline CSS został zablokowany przez CSP; NIE jest
zaliczony do testu odstępów. Skuteczny arkusz był oddzielnym lokalnym plikiem.

Natywne Chrome potwierdziło Zoom 200%, devicePixelRatio 4 i viewport 640 px
przy szerokości okna 1280 px. Przy tym powiększeniu z aktywnymi odstępami
wykonano poprawne sprawdzenie; dokument miał 640 px. Skala została przywrócona
do 100%, override viewportu wyłączony. To próba powiększenia całej strony,
nie osobne powiększenie samego tekstu w Firefox.

Stan CAPTCHA tylko odczytano: polska nazwa checkboxa i instrukcja widoczne
w natywnym drzewie dostępności. Nie zaznaczano checkboxa ani nie obliczano
rozwiązania. Przesłanie formularza w tym stanie przeniosło fokus do wymaganej
weryfikacji bez rozwiązania. Limit 429 pokazuje instrukcję ponowienia oraz
fokus na podsumowaniu; nie usuwa wpisanej wartości.

## Anulowanie kliknięcia — natywna próba na 18d8829

Na osobnej kopii i bez modyfikacji aplikacji wpisano ANNA. W rzeczywistym
Chrome naciśnięto przycisk „Sprawdź numer”, przesunięto wskaźnik na nagłówek
i puszczono poza przyciskiem. Była to natywna czynność `drag`, bez wysyłania
sztucznych zdarzeń JavaScript. Wpisana wartość pozostała, wynik i błędy
nie pojawiły się, a fokus znajdował się na przycisku. Jeszcze przed kolejnym
kliknięciem porównano wszystkie 27 tabel: identyczne liczby i hashe,
w tym licznik publicznych zapytań. Formularz nie został przesłany.

Zwykłe kliknięcie tego samego przycisku zwróciło dziesięć wariantów ANNA,
P5ANNA niedostępny, pozostałe wolne; fokus `availability-result`.
Zmieniła się wyłącznie tabela licznika zapytań, bieżąca liczba wyniosła 1.
Pozostałe 26 tabel kopii i wszystkie 27 głównej bazy zachowały stan.
Screenshoty 140 i 141 obejrzano; raport podaje hash źródeł i zakres.

Próba odpowiada anulowaniu przed puszczeniem wskaźnika opisanemu w
[wyjaśnieniu W3C do kryterium 2.5.2](https://www.w3.org/WAI/WCAG21/Understanding/pointer-cancellation.html).
Dotyczy bazowego formularza, nie fizycznego ekranu dotykowego ani widgetu
CAPTCHA. Nie włączono VoiceOver: przełącznik macOS odczytano jako wyłączony;
tymczasowe włączenie czytnika wymaga odpowiedzi na pytanie o ustawienie systemu.

## Macierz kryteriów

„Dowód” oznacza lokalnie sprawdzony zakres opisany w ostatniej kolumnie,
nie formalny wynik całego kryterium dla wszystkich ekranów produktu.
„Brak zastosowania” dotyczy wyłącznie zbadanych stanów tego serwisu.
„Częściowo” pozostawia jawne kroki odbioru. Wszystkie 50 kryteriów A/AA są
uwzględnione; 4.1.1 zachowano także jako historyczną kontrolę HTML.

| Kryterium | Stan | Dowód lub brak |
|---|---|---|
| 1.1.1 | Dowód | Tekstowe statusy i cel CAPTCHA; rzeczywista weryfikacja nie wymaga obrazów ani audio, alternatywa informacji w urzędzie. |
| 1.2.1 | Brak zastosowania | Brak audio/wideo w badanych stronach. |
| 1.2.2 | Brak zastosowania | Brak nagrania z dźwiękiem. |
| 1.2.3 | Brak zastosowania | Brak filmu. |
| 1.2.4 | Brak zastosowania | Brak transmisji. |
| 1.2.5 | Brak zastosowania | Brak filmu do audiodeskrypcji. |
| 1.3.1 | Dowód | Nazwane regiony, nagłówki, etykiety, opis instrukcji i błędów; axe i AX. |
| 1.3.2 | Dowód | Czytelna kolejność treści w AX i DOM; CSS nie przestawia etapów. |
| 1.3.3 | Dowód | Instrukcje podają nazwy czynności/pól; status nie wymaga rozpoznania kształtu/położenia. |
| 1.3.4 | Dowód | Układy 320×900 i 900×600, bez blokady orientacji. Brak próby fizycznego telefonu. |
| 1.3.5 | Brak zastosowania | Pole wyróżnika nie zbiera danych o użytkowniku. E-mail logowania poza tym przebiegiem. |
| 1.4.1 | Dowód | Dostępny/niedostępny jest tekstem; kolor nie jest jedynym sygnałem. |
| 1.4.2 | Brak zastosowania | Brak automatycznego dźwięku. |
| 1.4.3 | Dowód | Wcześniejsze obliczenia strony; rzeczywisty widget: tekst/atrybucja 17,7552:1, biały tekst błędu 6,3153:1. ODBIOR-CAPTCHA.md. |
| 1.4.4 | Dowód | Natywne 200% Chrome, sprawdzenie numeru i zachowany wynik. |
| 1.4.5 | Dowód | Rzeczywiste oznaczenia są tekstem HTML, nie rasterem. |
| 1.4.10 | Dowód | Dokument 320 px, bez poziomego przewijania; wynik i błędy. Uzupełnienie CAPTCHA: rzeczywisty błąd 429 przy DOM 320×900, popover 240 px w granicach ekranu, scrollWidth=320; mobile-captcha-error-proof.json. |
| 1.4.11 | Dowód | Widoczny fokus; widget: niezaznaczone obramowanie 3,0554:1, biały znak na zielonym 4,3653:1. Zakres standardowych stanów Chrome. |
| 1.4.12 | Dowód | Zastosowane i zmierzone cztery odstępy; wynik/błędy/instrukcja bez utraty treści. |
| 1.4.13 | Brak zastosowania | Brak własnych nakładek uruchamianych hover/focus w badanych ekranach. |
| 2.1.1 | Dowód | Space weryfikuje, Tab prowadzi do dostępnej atrybucji i submit, Return daje wynik. Odnośnik poprawiony w 772378a. |
| 2.1.2 | Dowód | Tab opuszcza także pracującą weryfikację; bez pułapki w wykonanym procesie. |
| 2.1.4 | Brak zastosowania | Brak skrótów aplikacji aktywowanych jednym znakiem. |
| 2.2.1 | Dowód | Naturalne pięć minut do wygaśnięcia dowodu, komunikat i możliwość ponowienia; ANNA zachowana, brak utraty pracy. |
| 2.2.2 | Dowód | Brak ruchomej treści bazowej; obracający się wskaźnik sygnalizuje niezbędny postęp weryfikacji. |
| 2.3.1 | Dowód | Przebieg pracy widgetu bez migania, wskaźnik obraca się; brak błysków w zbadanym Chrome. |
| 2.4.1 | Dowód | Tab i Enter na linku pomijania prowadzą do main. |
| 2.4.2 | Dowód | Opisowy tytuł sprawdzania w każdej badanej odpowiedzi. |
| 2.4.3 | Dowód | Checkbox → ALTCHA → submit; po POST fokus wyniku. Błąd/wygaśnięcie zachowują kontrolę klawiaturą. |
| 2.4.4 | Dowód | Nazwane linki nawigacji/błędów i opisowa nazwa atrybucji ALTCHA; redundantne logo ukryte. |
| 2.4.5 | Brak zastosowania | Jedna publiczna funkcja, strony odpowiedzi w procesie sprawdzania; login poza zakresem. |
| 2.4.6 | Dowód | Tytuły sekcji i jawne etykiety pól w AX. |
| 2.4.7 | Dowód | Fokus checkboxa, odnośnika i submit widoczny na rzeczywistych zrzutach. |
| 2.5.1 | Dowód | Standardowe pola/przycisk nie wymagają wielopunktowego gestu. |
| 2.5.2 | Dowód | Natywne anulowanie poza przyciskiem i checkboxem; dodatnie kliknięcie w tym samym punkcie. Fizycznego dotyku nie badano. |
| 2.5.3 | Dowód | Nazwy AX zawierają widoczne etykiety pól i przycisków. |
| 2.5.4 | Brak zastosowania | Brak sterowania przez ruch urządzenia. |
| 3.1.1 | Dowód | lang=pl, polskie komunikaty i widget w odczytanym stanie. |
| 3.1.2 | Dowód | Treść polska; nazwy produktu, prefiksy i symbole techniczne. |
| 3.2.1 | Dowód | Przejście fokusem do pól nie przesyła zapytania. |
| 3.2.2 | Dowód | Weryfikacja nie przesyła formularza samoczynnie; potrzebne jawne Enter/kliknięcie submit. |
| 3.2.3 | Dowód | Stałe menu dla początkowego formularza, błędów, wyniku i ograniczeń. |
| 3.2.4 | Dowód | Stałe nazwy pól i czynności we wszystkich badanych odpowiedziach. |
| 3.3.1 | Dowód | Tekst błędu, podsumowanie i aria-invalid; wartości zachowane. |
| 3.3.2 | Dowód | Instrukcja widoczna i połączona z polem; reguły znaków opisane. |
| 3.3.3 | Dowód | Błąd formatu opisuje dozwolone znaki, link pozwala poprawić pole. |
| 3.3.4 | Brak zastosowania | Anonimowe sprawdzenie nie zmienia ewidencji ani nie zawiera czynności prawnej. |
| 4.1.1 | Dowód | HTML testowany pod kątem unikalności identyfikatorów i relacji; automat. |
| 4.1.2 | Dowód | Nazwy/stany niezweryfikowany, pracuje, zweryfikowany i błąd widoczne w natywnym AX. |
| 4.1.3 | Częściowo | Fokus wyniku/błędów, aria-live wyniku i role=alert widgetu potwierdzone. Rzeczywiste ogłoszenie przez VoiceOver niepotwierdzone. |

## Dowody i dalszy odbiór

### Aktualny odbiór i historyczne przygotowanie

`final-public-acceptance-ready.json` opisuje wyłącznie stan przed próbami.
Aktualne wyniki po zgodzie: `final-public-acceptance-proof.json` i
`ODBIOR-CAPTCHA.md`. Trzy rzeczywiście zużyte dowody, upływ pięciu minut,
błąd pobrania 429, ponowienie, klawiatura, fokus i anulowanie zweryfikowane.
Kontrast obliczono z rzeczywistych stylów. Zweryfikowany widget mieści się
w faktycznym DOM 272 px; nie jest to dowód mobilnego popovera błędu 320 px.
Siedemnaście testów PASS i jeden SKIP PG; składnia JS PASS.

VoiceOver tymczasowo włączony, lecz narzędzie nie dostarczyło obserwowalnego
wyniku mowy. Ustawienie przywrócono. Wszystkie 27 głównych tabel zachowane;
kopia CAPTCHA zmieniła wyłącznie stan ochrony, kopia czytnika tylko licznik.
Nie wykonano urzędowej operacji ani nowego testu operatorów.

`evidence/public-wcag-axe.json` zapisuje konkretne przebiegi, wersję silnika,
naruszenia, reguły wymagające ręcznej oceny, hashe źródeł i konfigurację.
`evidence/public-wcag-regression.txt`: 33 testy, 32 PASS/1 SKIP wymagający
PostgreSQL. Zakres: HTML dostępności, ochrona publiczna i walidacja operacji API.

Prywatne zrzuty: 120 (rzeczywiste odstępy, wynik 320), 121 (błąd 320),
122 (wynik 200%), 124 (instrukcja po poprawce). Zrzut 123 po przełączeniu
zoom/override był nieproporcjonalny; nie jest dowodem wizualnym 320.
Dowód szerokości po poprawce pochodzi z DOM, a standardowy wygląd ze 124.

Pozostaje niepotwierdzony rzeczywisty odczyt komunikatów przez czytnik.
Ograniczenie obserwacji mowy utrzymuje się; pozostały scenariusz odbioru
zapisano w ODBIOR-CAPTCHA.md. Mobilny błąd 429 dodatkowo sprawdzono
przy rzeczywistym DOM 320×900 na kodzie 855358b (zrzut 163); bez zmiany CSS.
Wymuszone kolory, inne przeglądarki, fizyczny dotyk i docelowy HTTPS nie były
przedmiotem końcowej próby; jej wynik nie jest formalnym odbiorem urzędowym.
Login/sesja i PDF mają osobne raporty, poza zakresem tej publicznej macierzy.
Żaden wynik nie potwierdza pełnego AA ani osiągnięcia całego celu.
