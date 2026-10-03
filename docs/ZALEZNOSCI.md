# Zależności i odtwarzalna instalacja

Stan: 03.10.2026. Serwer ma lock wersji i SHA-256 w `requirements.txt`,
wygenerowany przez uv 0.12.22. `requirements.in` zawiera zakresy do planowania
aktualizacji. Osobny `requirements-qa.txt` zawiera ten sam rdzeń i narzędzia
kontroli PDF/QR, opisane w `requirements-qa.in`; nie jest potrzebny na serwerze.

Profil sprawdzony przez wykonanie: CPython 3.12.14, macOS ARM64. Pobrano też
komplet paczek CPython 3.12 dla Linux glibc na x86-64 i ARM64, z wyborem tagów
manylinux 2.28/2.17/2014. Nie wykonano ich na Linuxie. Nie deklarujemy wsparcia
innych wersji Pythona, Windows, PyPy ani musl na podstawie uniwersalnego locka.

## Instalacja wydania

Przygotuj nowe środowisko, zamiast zmieniać środowisko działającego wydania:

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip --isolated install --index-url https://pypi.org/simple --require-hashes --only-binary=:all: -r requirements.txt
.venv/bin/python -m pip check
.venv/bin/python manage.py check
```

Każda zależność, również przechodnia, ma dokładną wersję i hashe. Instalacja
wymaga wheel i nie buduje pobranych źródeł. Flaga `--isolated` ignoruje ustawienia
pip użytkownika i zmienne pip; nie zmienia konfiguracji aplikacji. Nie dodawaj
przypadkowych dodatkowych indeksów ani `--no-require-hashes` do instalacji wydania.
Zatwierdzony wewnętrzny mirror może zastąpić PyPI, zachowując te same bajty i
kontrolę hashy. Hash dowodzi zgodności z lockiem, nie braku podatności biblioteki.

Podstawa mechanizmu: [pip — secure installs](https://pip.pypa.io/en/stable/topics/secure-installs/).
Lock i pliki instalacyjne są częścią tego samego wydania o pełnym SHA.
Spis licencji: `../THIRD-PARTY-NOTICES.md`; konfiguracja serwera i procedura
aktualizacji: `WDROZENIE-URZEDOWE.md`.

## Pakiet offline

Na przygotowującym komputerze z takim samym CPython/platformą jak serwer:

```sh
python3.12 -m pip --isolated download --index-url https://pypi.org/simple --require-hashes --only-binary=:all: --dest wheelhouse -r requirements.txt
```

Przenieś zatwierdzone wydanie, lock, `wheelhouse` i pliki notices do infrastruktury
urzędu uzgodnionym kanałem. Następnie w nowym środowisku serwera:

```sh
.venv/bin/python -m pip --isolated install --no-index --find-links wheelhouse --require-hashes --only-binary=:all: -r requirements.txt
.venv/bin/python -m pip check
```

Nie mieszaj architektur. Gdy potrzebna paczka jest niedostępna dla docelowej
platformy, instalacja ma zakończyć się błędem; nie wyłączaj kontroli ani nie
przechodź automatycznie do budowania źródeł. Python, PostgreSQL, Nginx, systemd,
certyfikaty CA, Node i Poppler nie są zależnościami zarządzanymi przez ten lock.
Ich dostarczenie i wersje mają osobny odbiór na infrastrukturze urzędu.

## Aktualizacja locka

Generator jest narzędziem przygotowania wydania; nie musi być zainstalowany w
środowisku aplikacji. Użyta wersja: uv 0.12.22 z oficjalnej dystrybucji PyPI.
Bez lokalnego Dockera. Zachowaj stary lock w Git i przeczytaj dokładny diff.

```sh
uv pip compile requirements.in --universal --python-version 3.12 --no-python-downloads --default-index https://pypi.org/simple --only-binary :all: --generate-hashes --output-file requirements.txt
uv pip compile requirements.in requirements-qa.in --constraint requirements.txt --universal --python-version 3.12 --no-python-downloads --default-index https://pypi.org/simple --only-binary :all: --generate-hashes --output-file requirements-qa.txt
```

Istniejący lock zachowuje wybrane wersje przy zwykłym compile. Planowaną
aktualizację wykonuj z `--upgrade-package NAZWA`, po ocenie zmian; nie aktualizuj
wszystkich paczek przy instalacji wydania. Podstawa:
[uv — locking environments](https://docs.astral.sh/uv/pip/compile/).

Sprawdź pobranie wszystkich wheel, `pip check` i potrzebne testy w nowym
środowisku. Odbiór aktualizacji biblioteki musi obejmować funkcje, które jej
używają, oraz wymagane CI. Nie traktuj historycznych testów starych wersji jako
wyniku dla nowego locka. Odśwież spis licencji i archiwum notices po każdej zmianie.

## Spis paczek i teksty licencji

`scripts/dependency-inventory.py` odczytuje pobrane wheel bez importowania ich
kodu. Sprawdza nazwę, wersję i SHA-256 w locku, zachowuje dostarczone pliki
LICENSE/LICENCE/COPYING/NOTICE oraz ich hashe. Przykład, z nowym plikiem wyniku:

```sh
python3.12 scripts/dependency-inventory.py --lock requirements.txt --target linux-x86_64-cpython312 --wheels wheelhouse --notices third_party/notices --output third_party/python-new-release.json
```

To spis paczek Python i dostarczonych notices, nie pełny SBOM całego serwera.
Zawiera również notices składników dołączonych do wheel, które nie są używane
przez nasze przepływy, np. dodatkowych fontów ReportLab. Nie usuwaj ich na
podstawie samego braku użycia. Komponenty natywne wewnątrz wheel i systemowe
wymagają osobnego spisu oraz oceny pakietu przed redystrybucją. Nie wykonano
pełnego audytu podatności ani zatwierdzenia warunków komercyjnej dystrybucji.

## Wykonane kontrole poprzedniego locka (33 paczki)

Poniższe wyniki dotyczą locka sprzed rozszerzenia XLSX. Bieżący lock
i dodatkowe sprawdzenia opisano poniżej.

- 33 zależności serwera, te same wersje co dotychczas używane przez aplikację;
  zakresy i wersje bezpośrednio importowanych asn1crypto/certvalidator opisane
  również w pliku wejściowym. Windows-only tzdata występuje w uniwersalnym
  locku, ale nie jest instalowane na sprawdzanych platformach.
- Pobranie z `--require-hashes --only-binary=:all:`: macOS ARM64 oraz Linux
  x86-64/ARM64, po 33 paczki. To sprawdzenie dostępności i integralności.
- Nowe środowisko macOS: rzeczywista instalacja bez internetu z pobranych
  wheel, `pip check` i Django check PASS. Główna `.venv` pozostała bez zmian.
- 34/34 testy dokumentów, podpisów i sesji PASS w czystym środowisku.
  `evidence/dependency-clean-regression.txt`. Brak operatora HTTP w tym teście.
- pip oraz narzędzie spisu odrzuciły celowo zmieniony wheel ALTCHA; nie
  zainstalowano go. `evidence/dependency-tamper-rejection.txt`.
- Wszystkie 52 zachowane notices mają sumy zgodne ze spisami trzech platform.
- Powtórne wygenerowanie obu locków przez tę samą wersję uv dało identyczne
  bajty. Raport: `evidence/dependency-lock-report.json`.

Nie jest to wykonanie na Linuxie, test PostgreSQL tej instalacji, systemd/TLS,
test operatorów ani odbiór całego celu. Instalacja narzędzi QA też przeszła
offline i `pip check`; nie powtarzano pełnego renderowania wszystkich PDF-ów.

## Rozszerzenie XLSX — wcześniejszy lock (36 paczek)

Dodano openpyxl 3.1.5, defusedxml 0.7.1 i et-xmlfile 2.0.0; pozostałe wersje
nie zostały zmienione. Runtime i QA mają dokładne wersje/hashe nowych paczek.
Instalacja wheel z PyPI z `--require-hashes --only-binary=:all:` oraz `pip check`
przeszły w istniejącym czystym środowisku CPython 3.12.14/macOS ARM64.
Nowe uniwersalne wheel dodano też do wcześniejszych zestawów Linux x86-64
oraz ARM64; spisy sprawdzają wszystkie 36 paczek względem bieżącego locka.
To odświeżenie spisów, nie wykonanie na Linuxie ani nowy pełny test instalacji
offline. Bieżące spisy: `third_party/python-*-excel-20261003.json`; 56 notices.

45 testów importów wykonano na SQLite (42 PASS, 3 SKIP PostgreSQL) i lokalnym
PostgreSQL (45 PASS). Osobna kopia bazy przeszła import przez Chrome oraz
backup/restore. Zakres i ograniczenia: [Import XLSX](IMPORT-XLSX.md).
Wcześniejszych wyników dokumentów/podpisów nie powtarzano po tym dodatku.

## Profil Render — dodatek WhiteNoise

Dodano WhiteNoise 6.12.0 (uniwersalny wheel, bez dodatkowych zależności).
Runtime/QA ponownie wygenerowano tym samym uv z ograniczeniami wcześniejszych
locków: wszystkie wcześniejsze wersje zachowane. Oficjalny wheel pobrano
z PyPI, zweryfikowano SHA-256 i zainstalowano w środowisku testowym.
`third_party/whitenoise-render-20261003.json` dotyczy wyłącznie tego dodatku,
nie zastępuje historycznych spisów całego runtime. Zachowano notices.
17 testów profilu/proxy i konfiguracji urzędowej PASS, collectstatic i składnia
PASS; nie wykonano nowego pełnego testu zależności/offline/Linuxa.
Profil i ograniczenia opisuje `RENDER.md`.
