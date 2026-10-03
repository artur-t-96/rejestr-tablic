# Końcowy lokalny odbiór CAPTCHA

03.10.2026, kod aplikacji `772378a8b0afc0f15973833fc4a6968e68632a9f`.
Próby wykonano w Chrome użytkownika na osobnej bazie i cookies,
`127.0.0.1:8787`. Próg testowy wynosił 1, domyślny pozostaje 10;
limit 30/min i koszt PBKDF2 5000 zachowano. Zgoda użytkownika na
oczekujące czynności została otrzymana. Nie zmieniono ustawień głównej instancji.

Odtworzono brak dostępu Tab do atrybucji ALTCHA. Własna konfiguracja
tłumaczenia usuwa tabindex=-1 z jedynego widocznego odnośnika, a ukrycie
logo usuwa drugi, dekoracyjny odnośnik. Pliki dostawcy/licencja i wyłączenie
Human Interaction Signature pozostały bez zmian. Zastosowano
[oficjalne API konfiguracji widgetu](https://altcha.org/docs/integration/widget-customization/).
Po twardym odświeżeniu Chrome sprawdzono rzeczywiście nowy DOM.

## Wykonane scenariusze

- Space uruchomił weryfikację, stan zmienił się z „Weryfikacja…” na
  „Zweryfikowano”. Tab podczas pracy nie tworzył pułapki. Kolejność po
  poprawce: checkbox → odnośnik ALTCHA → przycisk sprawdzenia.
  Odnośnik miał widoczny fokus i opisową nazwę; nie otwierano zewnętrznej strony.
- Trzy rzeczywiste POST przyjęły nowy dowód i przeniosły fokus do wyniku.
  Bezpośrednio przed każdym ogrzano licznik GET, aby POST przekraczał próg.
  Pole consumed_at trzech wyzwań potwierdza weryfikację serwerową, a nie
  przypadkowe zapytanie poniżej progu po upływie okna.
- Po rzeczywistych pięciu minutach niewykorzystany dowód wygasł.
  Checkbox został wyzerowany, polski komunikat informował o ponowieniu,
  ANNA pozostała. Próba przesłania zatrzymała się na wymaganym checkboxie.
  Nie jest to próba serwerowego POST z wygasłym dowodem; tę odmowę bada backend.
- Naciśnięcie checkboxa, przeciągnięcie poza niego i puszczenie nie utworzyło
  wyzwania. Dodatnie kliknięcie w tym samym punkcie utworzyło wyzwanie
  i zweryfikowało je. Wcześniejszą próbę z niejednoznacznymi współrzędnymi wykluczono.
- Pobieranie wyzwań do limitu dało rzeczywiste 429. Widget pokazał polski
  błąd w role=alert i zachował ANNA. Po upływie okna ponowienie powiodło się,
  a świeży dowód został zużyty przez serwer. Pierwsza seria pobrań wygasła
  przed kliknięciem: nie zaliczono jej jako próby błędu UI.
- Zweryfikowany widget mieścił się przy rzeczywistym DOM 272 px:
  scrollWidth=272, szerokość widgetu 198. Pasek DeviceToolbar wcześniej
  pokazywał 320×900, lecz pomiar po aktywacji był inny. Nie opisujemy tego
  zrzutu jako dowodu 320 px ani mobilnego komunikatu błędu.

Kontrast z rzeczywistych stylów OKLCH, przeliczonych na luminancję sRGB:
tekst/atrybucja 17,7552:1; niezaznaczone obramowanie 3,0554:1;
biały znak na zielonym zaznaczeniu 4,3653:1; biały tekst błędu 6,3153:1.
Animacja pracy to obrót wskaźnika, bez migania; sygnalizuje niezbędny postęp.
Nie badano tutaj wymuszonych kolorów ani fizycznego urządzenia.

17 testów ochrony/HTML PASS, 1 SKIP wymagający PostgreSQL; kontrola składni
JavaScript PASS. To testy serwera/HTML, osobne od prób Chrome.
Dowód: `../evidence/final-public-acceptance-proof.json` oraz
`../evidence/final-public-acceptance-tests.txt`.
Prywatne zrzuty 153, 155, 156, 158, 160 i 162 obejrzano.
Zrzuty 154 i 159 nie są dowodami odpowiednio anulowania i 320 px.

## Czytnik i zachowanie danych

VoiceOver włączono tymczasowo po zgodzie użytkownika. Na osobnej kopii
8788 sprawdzono błędne Q: wartość zachowana, fokus podsumowania błędów.
Narzędzie nie udostępniło obserwowalnego wyniku mowy/panelu czytnika;
nie potwierdzono ogłoszenia komunikatu przez VoiceOver. Próba nie dowodzi
usterki aplikacji ani czytnika. VoiceOver przywrócono do wyłączonego,
panel podpisów do poprzedniego ustawienia, samouczek zamknięto.
Tymczasowe rozmiary i tryb urządzenia Chrome również przywrócono.

Wszystkie 27 tabel głównej bazy zachowały liczby i hashe.
W kopii CAPTCHA zmieniły się tylko sesja, wyzwania, liczniki i sqlite_sequence;
23 pozostałe tabele zachowane. W kopii czytnika zmienił się wyłącznie licznik,
26 pozostałych tabel zachowano. Nie zapisano żadnej operacji urzędowej.

B04 ma lokalny dowód działania. B05 pozostaje otwarty: rzeczywiste
ogłaszanie przez czytnik i pełny odbiór AA nie są potwierdzone.
Główna aplikacja działa pod `http://127.0.0.1:8765/`, health podaje powyższy
commit kodu. Nie ma remote/CI/produkcyjnego wdrożenia ani nowych testów operatorów.

## Uzupełnienie mobilne (03.10, kod 855358b)

Na tej samej odizolowanej kopii wykonano ponownie rzeczywiste 429:
dziesięć pobrań wyzwania zwróciło 200, jedenaste i kliknięcie Chrome 429.
Zmierzono DOM 320×900, scrollWidth=320, widget x=37..283 (246 px)
i popover x=43..283 (240 px). Polski błąd mieścił się w ekranie,
ANNA pozostała. Zrzut 163 obejrzano; nie zmieniono kodu ani CSS.
To dowód mobilnego błędu, nie nowy test wygaśnięcia lub odczytu mowy.
Przywrócono DeviceToolbar 400/pusta wysokość, wyłączono go, zamknięto
DevTools oraz kartę próby. Serwer kopii 8787 zatrzymano.
Dowód: `../evidence/mobile-captcha-error-proof.json`.

## Pozostały odbiór rzeczywistym czytnikiem

Ograniczenie narzędzia utrzymało się przez kolejne próby: brak dostępnego
wyniku mowy lub panelu napisów. Odczyt AX, poprawny fokus i aria-live
nie zamykają B05. To wymaga odsłuchu przez osobę albo narzędzia,
które rzeczywiście udostępni mowę/napisy. Zgoda na ustawienia została
już udzielona; nie jest to oczekiwanie na ponowne potwierdzenie.

Próba podstawowa na odizolowanym `http://127.0.0.1:8788/`:

1. Włącz czytnik, przejdź klawiaturą do pola wyróżnika. Sprawdź odczyt
   etykiety, instrukcji formatu oraz wyboru województwa/cyfry.
2. Wpisz Q i prześlij. Potwierdź przeniesienie do podsumowania błędów,
   odczyt konkretnego błędu i zachowanie Q; odnośnik musi prowadzić do pola.
3. Wpisz ANNA i prześlij. Potwierdź odczyt wyniku dostępności i sugestii,
   bez potrzeby samodzielnego szukania nowej treści.
4. Osobny test z progiem CAPTCHA 1: odczyt wymogu, etykiety checkboxa,
   pracy, zakończenia, błędu i wygaśnięcia; po ponowieniu wynik formularza.
   Kopia 8787 jest zatrzymana — uruchom ją zgodnie z zapisaną konfiguracją
   próby, zachowując izolowane cookies i dane. Nie obniżaj progu głównej instancji.
5. Zapisz system, czytnik/wersję, przeglądarkę/wersję, rewizję kodu,
   faktycznie wypowiedziane komunikaty i PASS/FAIL każdego punktu.
   Przywróć ustawienia czytnika. Odmowa/błąd ma pozostać jawny do poprawki.

Do zamknięcia B05 nie wystarczy wykonanie tylko punktów 1–3.
GitHub i Render pozostają odroczone zgodnie z warunkiem użytkownika.
