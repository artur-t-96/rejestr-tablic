# Rzeczywisty odbiór VoiceOver — 03.10.2026

## Wynik i zakres

**B05 pozostaje częściowy.** Po zgodzie użytkownika uzyskano rzeczywisty
wynik VoiceOver przez systemowy Script Editor i właściwość `last phrase.content`.
To tekst wygenerowany przez czytnik, a nie drzewo AX ani tekst oczekiwanego
komunikatu przekazany do syntezatora. Nie deklarujemy odsłuchu fizycznego audio.
[Wybrane faktyczne komunikaty i wersje](../evidence/reader-output-20261003.json)
zawierają zakres oraz ograniczenia każdej próby.

Środowisko: macOS 26.5.1 (25F80), VoiceOver 10 (993), Chrome 154.0.8037.95.
Formularz: izolowana kopia SQLite i cookies, port 8789; bazowy kod produkcji
`22b5f759c3402c785475ac57f1d2d641b130e1e2`, następnie poprawka
`c0913358934d41d8a6cb207aa162e588f0bda80d`. Drugi port 8790 służy tylko
próbie CAPTCHA z progiem 1; domyślny próg głównej aplikacji pozostaje 10.
Dane ewidencji, kont i dokumentów głównej instancji zachowały liczby rekordów.

## Wykonane próby

| Punkt | Wynik | Rzeczywisty zakres |
|---|---|---|
| P1 | PASS | Czytnik wypowiedział etykietę i instrukcję wyróżnika, nazwę/wybór województwa i cyfry. |
| P2 | PASS po poprawce | Q zachowane; fokus podsumowania, polski konkretny błąd odnośnika, Enter wraca do pola. Czytnik odczytał Q, instrukcję i błąd wraz ze stanem invalid. |
| P3 | PASS w opisanym zakresie | Po POST fokus regionu ANNA; VoiceOver odczytał nazwę wyniku, numery, dostępność oraz sugestie podczas nawigacji w wyniku. Nie potwierdzono automatycznego odczytu całego regionu ani każdej pary numer/status. |
| P4 | CZĘŚCIOWO | Rzeczywiście odczytano wymóg potwierdzenia i niezaznaczony checkbox „Nie jestem robotem”. Odczyt pracy, zakończenia, błędu, wygaśnięcia i udanego ponowienia pozostaje niewykonany w tej próbie. |
| P5 | Przywrócone ustawienia | VoiceOver wyłączony, sterowanie AppleScript wyłączone, oryginalne okno powitalne włączone, widok Commands; Quick Nav i inne ustawienia zachowane. Pełny test nie jest zakończony z powodu P4. |

W pierwszym przebiegu Q natywna walidacja Chrome zatrzymywała POST angielskim
komunikatem długości. Formularz ma teraz `novalidate` i korzysta z istniejącej
walidacji serwera, która pokazuje polskie podsumowanie i powiązany błąd pola.
Nie usunięto walidacji danych. Nieudane próby nawigacji pozostają w prywatnym
zapisie jako nieudane; nie są dowodem odczytu odnośnika.

## Dostarczenie poprawki

[PR #5](https://github.com/artur-t-96/rejestr-tablic/pull/5) scalono jako
`f88a82403438dd5cf6bfb44ab7f94c1dedfebf7f`.
[CI PR](https://github.com/artur-t-96/rejestr-tablic/actions/runs/37136666937)
i [CI main](https://github.com/artur-t-96/rejestr-tablic/actions/runs/37136905566)
przeszły wszystkie trzy zadania. Istniejący skupiony test powiązania instrukcji
i błędu także przeszedł lokalnie; lokalnego Dockera nie używano.

Render `dep-db0iqblg1s2s73e9cvfg` uruchomił powyższą rewizję: health 200
z pełnym zgodnym SHA. W Chrome użytkownika wykonano Q → podsumowanie →
odnośnik błędu → zachowane pole → ANNA → dostępność i sugestie. Ekrany
sprawdzono wizualnie. Główna instancja lokalna na 8765 ma tę samą poprawkę
szablonu i również przeszła Q → poprawienie → wynik. Próby mowy na produkcji
zwróciły niezwiązane „New Tab” i **nie zostały zaliczone** jako dowód czytnika;
zapisany rzeczywisty odczyt dotyczy odizolowanej kopii lokalnej.

## Pozostałe kroki

Ukończenie CAPTCHA wymaga potwierdzenia przy wykonaniu według zasad narzędzia
obsługi komputera. Pytanie o tę konkretną próbę na 8790 i jej ponowienia jest
oczekujące; ogólna zgoda na autonomię nie zastępuje tego potwierdzenia.
Po odpowiedzi należy ponownie sprawdzić aktualny checkbox, włączyć uzgodnioną
sesję czytnika i zebrać jego rzeczywiste komunikaty pracy, zakończenia,
wygaśnięcia, błędu i ponowienia z wynikiem formularza. Przywrócić ustawienia.

Wcześniejsze funkcjonalne ukończenia CAPTCHA, naturalne wygaśnięcie i błąd 429
mają własne dowody w [ODBIOR-CAPTCHA.md](ODBIOR-CAPTCHA.md). Nie zastępują
odbioru tych stanów czytnikiem. Macierz [WCAG-PUBLICZNY.md](WCAG-PUBLICZNY.md)
pozostawia 4.1.3 częściowe; pełna zgodność A/AA nie jest jeszcze potwierdzona.
