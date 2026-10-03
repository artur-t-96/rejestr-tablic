# Weryfikacja e-Doręczeń — etap lokalny, 03.10.2026

## Wynik

63 testy całej aplikacji PASS (4,281 s). Ruff lint i format kodu poza istniejącymi wygenerowanymi migracjami PASS. Django check PASS, brak nowych wymaganych migracji. Wynik testów: `evidence/edor-and-core-tests.txt`.

21 testów e-Doręczeń obejmuje podpis JWT weryfikowany kluczem publicznym, cache tokenu, konfigurację/TLS/ważność certyfikatu, wyszukiwanie aktualnych danych BAE, utrwalenie PDF i ADE, deduplikację zleceń, zadanie asynchroniczne, nadanie i doręczenie, brak dowodu mimo statusu, odrębne uznanie za doręczoną, błędy 429/500/401, przerwane połączenie, budżet błędów obserwacji, wznowienie znanego zadania, zmianę nadawcy/środowiska, obcego adresata i nadawcę, obcy dowód, nieoczekiwany format dowodu, ochronę CSRF, limit zapytań, role, pobieranie i kontrolę integralności oraz dwa pracowniki konkurujące o jedno zadanie.

**To MockTransport i syntetyczny certyfikat testowy. Nie jest to test rzeczywistej usługi ani podpis kwalifikowany.** Symulowane dowody istnieją tylko w bazie testów, a nie jako fałszywe potwierdzenia w działającym rejestrze.

## Rzeczywista aplikacja lokalna

- Chrome, konto UMP: wejście Integracje → Wyszukaj adres urzędu; widoczny brak konfiguracji, wyłączony przycisk. Screenshot `evidence/05-edor-adresy.jpg`, sprawdzony wizualnie.
- Pisma: próba e-Doręczeń dla `DRT/2026/APPROVAL/B1AF05263D43`; czytelny komunikat braku konfiguracji, brak utworzonego zadania EDOR. Screenshot `evidence/06-edor-wysylka-zablokowana.jpg`, sprawdzony wizualnie.
- Nie wywołano mutującego API operatora, nie użyto rzeczywistych ADE ani certyfikatów, nie wysłano zgłoszenia dostępu.
- W bazie działa 35 urzędów; nadal jeden wcześniej zweryfikowany e-mail do lokalnej skrzynki plikowej. Nie potwierdza zewnętrznego doręczenia.

## Kopia i odtworzenie

Prawdziwy snapshot bazy działającej aplikacji: `var/backups/2026-10-03-edor-stage.zip`; SHA-256 bazy w archiwum `1c54e05daab377dc1cc03c4d28534998ed329f8bd37584b8f5124290f6ee53ee`. Odtworzenie do nowego katalogu `var/restores/2026-10-03-edor-stage`, bez nadpisania pracy. Kontrola SQLite/FK i sum dokumentów PASS, sesje i OTP unieważnione, brak zadań automatycznie gotowych do wysyłki. Dowód: `evidence/edor-backup-proof.json`.

Testy odtwarzania osobno sprawdzają zawartość dowodów, wstrzymanie `MONITORING` i odrzucenie uszkodzonego dokumentu kolejki lub dowodu. Działająca baza nie zawiera jeszcze rzeczywistych dowodów operatora.

## Braki i wymagany dalszy odbiór

Brak przydzielonych uprawnień INT, ADE nadawcy/odbiorcy i certyfikatu zarejestrowanego systemu. Materiały do zgłoszenia: `docs/DOSTEP-E-DORECZENIA.md`; konfiguracja i scenariusz prawdziwego testu: `docs/E-DORECZENIA.md`. Zgodność z rzeczywistym API, podpisy dowodów i test na infrastrukturze urzędu nie są potwierdzone. Pełny cel obejmuje również dalsze prace nad podpisami pism, przepływem EZD, wszystkimi rolami i procesami, dostępnością, PostgreSQL oraz instalacją i audytem końcowym.
