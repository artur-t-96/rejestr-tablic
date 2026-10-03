# Third-party notices

Stan: 03.10.2026. Spis paczek Python serwera z rzeczywiście pobranych wheel.
Dokładne wersje i dozwolone SHA-256: `requirements.txt`. Metadane poniżej są
deklaracjami dostarczonymi przez autorów paczek; pełne teksty zachowano w
`third_party/notices/`, bez zmian. Nie są jednolitą licencją całego produktu.

| Paczka | Wersja | Deklaracja licencji w metadanych |
| --- | --- | --- |
| [altcha](https://pypi.org/project/altcha/2.1.0/) | 2.1.0 | OSI Approved :: MIT License |
| [anyio](https://pypi.org/project/anyio/4.15.1/) | 4.15.1 | MIT |
| [asgiref](https://pypi.org/project/asgiref/3.12.1/) | 3.12.1 | OSI Approved :: BSD License |
| [asn1crypto](https://pypi.org/project/asn1crypto/1.5.1/) | 1.5.1 | OSI Approved :: MIT License |
| [certifi](https://pypi.org/project/certifi/2026.7.22/) | 2026.7.22 | OSI Approved :: Mozilla Public License 2.0 (MPL 2.0) |
| [cffi](https://pypi.org/project/cffi/2.1.1/) | 2.1.1 | MIT-0 |
| [charset-normalizer](https://pypi.org/project/charset-normalizer/3.5.2/) | 3.5.2 | MIT |
| [cryptography](https://pypi.org/project/cryptography/47.0.0/) | 47.0.0 | Apache-2.0 OR BSD-3-Clause |
| [defusedxml](https://pypi.org/project/defusedxml/0.7.1/) | 0.7.1 | OSI Approved :: Python Software Foundation License |
| [et-xmlfile](https://pypi.org/project/et-xmlfile/2.0.0/) | 2.0.0 | OSI Approved :: MIT License |
| [Django](https://pypi.org/project/Django/5.2.17/) | 5.2.17 | BSD-3-Clause |
| [gunicorn](https://pypi.org/project/gunicorn/23.0.0/) | 23.0.0 | OSI Approved :: MIT License |
| [h11](https://pypi.org/project/h11/0.16.0/) | 0.16.0 | OSI Approved :: MIT License |
| [httpcore](https://pypi.org/project/httpcore/1.0.9/) | 1.0.9 | BSD-3-Clause |
| [httpx](https://pypi.org/project/httpx/0.28.1/) | 0.28.1 | OSI Approved :: BSD License |
| [idna](https://pypi.org/project/idna/3.20/) | 3.20 | BSD-3-Clause |
| [lxml](https://pypi.org/project/lxml/6.1.3/) | 6.1.3 | BSD-3-Clause |
| [openpyxl](https://pypi.org/project/openpyxl/3.1.5/) | 3.1.5 | OSI Approved :: MIT License |
| [oscrypto](https://pypi.org/project/oscrypto/1.3.0/) | 1.3.0 | OSI Approved :: MIT License |
| [packaging](https://pypi.org/project/packaging/26.3/) | 26.3 | Apache-2.0 OR BSD-2-Clause |
| [pillow](https://pypi.org/project/pillow/12.3.0/) | 12.3.0 | MIT-CMU |
| [psycopg](https://pypi.org/project/psycopg/3.3.6/) | 3.3.6 | LGPL-3.0-only |
| [psycopg-binary](https://pypi.org/project/psycopg-binary/3.3.6/) | 3.3.6 | LGPL-3.0-only |
| [pycparser](https://pypi.org/project/pycparser/3.0/) | 3.0 | BSD-3-Clause |
| [pyHanko](https://pypi.org/project/pyHanko/0.35.0/) | 0.35.0 | MIT |
| [pyhanko-certvalidator](https://pypi.org/project/pyhanko-certvalidator/0.31.0/) | 0.31.0 | MIT |
| [PyJWT](https://pypi.org/project/PyJWT/2.15.1/) | 2.15.1 | MIT |
| [pypdf](https://pypi.org/project/pypdf/6.19.0/) | 6.19.0 | BSD-3-Clause |
| [PyYAML](https://pypi.org/project/PyYAML/6.0.3/) | 6.0.3 | OSI Approved :: MIT License |
| [reportlab](https://pypi.org/project/reportlab/4.5.1/) | 4.5.1 | OSI Approved :: BSD License |
| [requests](https://pypi.org/project/requests/2.34.2/) | 2.34.2 | OSI Approved :: Apache Software License |
| [WhiteNoise](https://pypi.org/project/whitenoise/6.12.0/) | 6.12.0 | MIT |
| [sqlparse](https://pypi.org/project/sqlparse/0.6.0/) | 0.6.0 | OSI Approved :: BSD License |
| [typing_extensions](https://pypi.org/project/typing_extensions/4.16.0/) | 4.16.0 | PSF-2.0 |
| [tzlocal](https://pypi.org/project/tzlocal/5.4.4/) | 5.4.4 | MIT |
| [uritools](https://pypi.org/project/uritools/6.1.3/) | 6.1.3 | MIT |
| [urllib3](https://pypi.org/project/urllib3/2.8.0/) | 2.8.0 | MIT |

Spisy z nazwami wheel, hashami i ścieżkami notices:

- `third_party/python-linux-x86_64-excel-20261003.json`
- `third_party/python-linux-arm64-excel-20261003.json`
- `third_party/python-macos-excel-20261003.json`

Każdy bieżący spis obejmuje 36 paczek i 56 notices. Starsze spisy
33 paczek/52 notices pozostają dowodami poprzedniego locka. Nie obejmuje warunkowego tzdata
dla Windows, narzędzi QA/uv/pip ani kompletnej listy natywnych bibliotek
wewnątrz wheel i systemu operacyjnego. Pobranie wheel Linuxa nie oznacza
wykonania aplikacji na Linuxie. Zasady aktualizacji: `docs/ZALEZNOSCI.md`.

W repozytorium są też osobno dostarczane zasoby:

- font DejaVu Sans: `registry/fonts/LICENSE`;
- widget ALTCHA: `registry/static/registry/altcha/LICENSE.txt`, wersje i sumy
  zasobów w `registry/static/registry/altcha/manifest.json`.

Pakiet zawiera różne warunki, w tym LGPL dla psycopg, MPL dla certifi oraz
odrębne notices bibliotek i fontów dołączonych do wheel. Pełna ocena warunków
dystrybucji i kompletności składników natywnych pozostaje do wykonania przed
przekazaniem komercyjnego pakietu. Zachowanie notices nie dowodzi spełnienia
wszystkich obowiązków; nie zastępuje oceny konkretnego sposobu dystrybucji.
