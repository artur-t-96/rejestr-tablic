# Weryfikacja podpisów — 03.10.2026

## Dowody lokalne

- Rzeczywiste RSA/PAdES i syntetyczna CA, bez atrap funkcji podpisu: podpis kluczem, import bez klucza, jawny łańcuch CA, CRL, odrzucenie unieważnionego certyfikatu i brakujących danych odwołania.
- Odrzucenie zmienionych bajtów, nieobjętego podpisem ogona, pliku bez podpisu oraz poprawnie podpisanej rewizji, która zmienia katalog lub treść strony.
- HTTP: import, raport, pobranie oryginału/podpisu, izolacja nadawcy i odmowa administratorowi; wykrycie uszkodzonego podpisanego PDF.
- Kolejka odczytuje aktualny podpis mimo wcześniejszego obiektu pisma. Zachowuje własny PDF po zmianie archiwum. Nowa wersja zachowuje poprzednik i kolejkę.
- Generator DEMO: rzeczywisty certyfikat, 0600/0700, odmowa nadpisania profilu i odmowa DEMO poza LOCAL. Kontrola backupu wykrywa zmianę podpisanego PDF.
- 79/79 testów całej aplikacji oraz 33/33 testy podpisów i EZD po ostatnich zmianach. Wyniki: `evidence/signatures-and-core-tests.txt`, `evidence/signatures-and-ezd-focused-tests.txt`.
- Wyścig podpis–kolejka sprawdzono następnie na rzeczywistym PostgreSQL: oba porządki dla SMTP/EZD/e-Doręczeń, dwa podpisy, rollback i wolna kryptografia. Końcowy przebieg 26/26 PASS, w tym 10 nowych testów współbieżności. Rzeczywisty plik lokalnej wiadomości zawiera dokładnie podpisany PDF, bez drugiej wiadomości po ponowieniu pracownika. Szczegóły i granice: `WSPOLBIEZNOSC-PODPISU.md`.

## Chrome i działająca baza

W sesji UMP utworzono nową wersję pisma `DRT/2026/APPROVAL/719052ACDF99`, następnie podpisano ją certyfikatem DEMO i zapisano raport. Nowe pismo: `99425517-6508-47d6-845e-b7f0c86a8ec2`. UI pokazuje podpis testowy niekwalifikowany i zamknięcie wersji do ponownego podpisania.

- Screenshot: `evidence/07-pades-podpis-testowy.jpg`, przejrzany wizualnie.
- Plik: `evidence/pades-testowy.pdf`, jedna strona, render Poppler i kontrola wizualna całej strony (`evidence/pades-render-1.png`). Brak nadpisania treści, polskie znaki czytelne, neutralna adnotacja o weryfikacji podpisu.
- Ponowna niezależna walidacja pliku z bazy: `evidence/pades-verification.json`.
- Spójny snapshot po podpisaniu i odtworzenie do osobnego katalogu; `evidence/pades-backup-proof.json` dokumentuje kontrolę sum, relacji, sesji i wstrzymania kolejki. Klucze nie są częścią backupu.

## Niewykonane

Nie wykonano podpisu kwalifikowanego, testu HSM/PKCS#11, kwalifikowanego znacznika czasu ani walidacji podpisów dowodów e-Doręczeń. Nie ma testu na infrastrukturze urzędu. Brak konfiguracji certyfikatów urzędu i dostępu do rzeczywistych API pozostaje jawny. Kolejne prace obejmują m.in. potwierdzenie numeracji kancelaryjnej, odbiór rzeczywistych integracji, dostępność, infrastrukturę urzędu i audyt wszystkich procesów.

Cel całego systemu pozostaje aktywny; powyższe dowody dotyczą konkretnego etapu lokalnego.
