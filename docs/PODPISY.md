# Podpisy PDF

## Zaimplementowany zakres

Pismo ma niezmienny oryginał i osobną podpisaną rewizję PAdES. Urzędnik nadawcy może podpisać kluczem skonfigurowanym dla urzędu lub wgrać PDF podpisany poza aplikacją. Konfiguracja dodatkowo dopuszcza konkretne konta i odciski certyfikatów. Administrator techniczny nie podpisuje pism ani nie pobiera dokumentów merytorycznych.

Weryfikacja obejmuje: bajty oryginału, analizę zmian wszystkich rewizji, podpis CMS, pokrycie całego dokumentu ostatnim podpisem, dopuszczony certyfikat, łańcuch zaufania i politykę unieważnienia. Niedozwolone zmiany treści, obcy certyfikat lub brak wymaganych danych odwołania blokują zapis. Raport, użytkownik, data i sumy SHA-256 są archiwizowane. Pobranie i utworzenie kolejki kontrolują integralność pliku.

Podpisywanie i kolejka blokują urząd, następnie pismo w tej samej kolejności. Kolejka odczytuje aktualną wersję spod blokady i zachowuje własny niezmienny PDF. Pisma z podpisem lub kolejką nie są ponownie podpisywane. Nowa wersja otrzymuje osobny numer i datę, kopiuje treść, wskazuje poprzednie pismo oraz wymaga uzasadnienia. Poprzedni dokument i zadania pozostają w archiwum. Nowa wersja nie anuluje doręczonego wcześniej pisma.

Rzeczywiste testy dwóch połączeń PostgreSQL, obu kolejności operacji, rollbacku
i załącznika lokalnej poczty: `WSPOLBIEZNOSC-PODPISU.md`. Jeśli ma być wysłana
podpisana wersja, podpisz ją przed utworzeniem kolejki. Późniejsza próba podpisu
tej wersji zostanie odrzucona, także przed rozpoczęciem wysyłki.

Starsze oryginały zawierające stałą adnotację „Status: niepodpisany” wymagają nowej wersji przed podpisaniem. Nie zmieniamy historycznych PDF ani ich sum kontrolnych. Migracja oznacza istniejące podpisane pliki jako wymagające weryfikacji; wyliczenie sumy nie nadaje im statusu poprawnego podpisu.

## Konfiguracja

Ustaw `SIGNING_CONFIG_FILE` na bezwzględną ścieżkę prywatnego JSON. Pliki konfiguracji, certyfikatów, CRL/OCSP i klucza mają mieć uprawnienia 0600, katalog 0700. Nie przechowuj ich w Git. Profile są osobne dla urzędów:

```json
{
  "offices": {
    "ump": {
      "mode": "LOCAL_PEM",
      "authorized_users": ["uprawniony@domena-urzedu.pl"],
      "allowed_certificate_fingerprints": ["64_male_znaki_hex_sha256_cert_der"],
      "trust_root_files": ["/etc/dyna-signing/root-ca.pem"],
      "chain_files": ["/etc/dyna-signing/intermediate-ca.pem"],
      "crl_files": ["/etc/dyna-signing/current-crl.pem"],
      "ocsp_files": [],
      "seal": {
        "key_file": "/etc/dyna-signing/seal-key.pem",
        "certificate_file": "/etc/dyna-signing/seal-certificate.pem",
        "password_file": "/etc/dyna-signing/key-password"
      }
    }
  }
}
```

Zastąp odcisk prawdziwym SHA-256 certyfikatu DER. `seal` jest opcjonalny: bez niego dostępny jest import podpisanego PDF, bez oddawania klucza aplikacji. Import wymaga zachowania oryginału jako pierwszej rewizji, bez drukowania lub ponownego zapisywania całego PDF. Aktualna wersja przyjmuje do pięciu podpisów PAdES i plik do 10 MB. Nie obsługuje kwalifikowanych znaczników czasu jako osobnego procesu LTV.

`LOCAL_PEM` wymaga jawnych korzeni CA i aktualnych CRL lub OCSP; weryfikacja odwołania jest offline i musi się powieść. Dane trzeba aktualizować w kontrolowanym procesie operacyjnym. Weryfikator nie pobiera adresów z nieznanego PDF/certyfikatu i nie korzysta z systemowych korzeni TLS. Certyfikat, ważność, długość klucza i zgodność z kluczem są sprawdzane przed podpisaniem.

## Lokalny certyfikat demonstracyjny

```sh
.venv/bin/python manage.py create_demo_signing --email ump@example.invalid --directory var/signing-demo-ump
SIGNING_CONFIG_FILE="$PWD/var/signing-demo-ump/profile.json" sh scripts/run-local.sh
```

Polecenie działa wyłącznie w trybie lokalnym, nie nadpisuje istniejącego katalogu i tworzy pliki prywatne. Certyfikat ważny jest siedem dni. Klucz CA nie jest zapisywany. `DEMO` stosuje demonstracyjną politykę bez wymaganej kontroli odwołania i jest blokowane poza środowiskiem lokalnym. To rzeczywisty podpis kryptograficzny, ale niekwalifikowany i nieprzeznaczony do oficjalnej korespondencji.

## Granice potwierdzenia

`VERIFIED_SIGNED` oznacza poprawność techniczną względem skonfigurowanej polityki. Nie oznacza podpisu kwalifikowanego. Raport zapisuje `qualification=NOT_ASSESSED` i `qualified_timestamp_verified=false`. Nie wdrożono jeszcze pełnej oceny list zaufania, kwalifikacji usługi, QSCD, walidacji długoterminowej ani konektora PKCS#11/HSM. Proces z rzeczywistym podpisem/pieczęcią urzędu wymaga ich doboru i osobnego testu. Konektor lokalnego PEM nie zastępuje urządzenia do tworzenia podpisu kwalifikowanego.

Podstawa implementacji: [API walidacji pyHanko](https://docs.pyhanko.eu/en/latest/lib-guide/validation/general-api.html), [analiza aktualizacji PDF](https://docs.pyhanko.eu/en/latest/lib-guide/validation/diff-analysis.html) i kod zainstalowanego pyHanko 0.35.0. Biblioteka wskazuje ograniczenia analizy zmian; testy nie dowodzą odporności na każdy możliwy złośliwy PDF.
