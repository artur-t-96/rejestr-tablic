document.querySelectorAll('.sidebar nav a').forEach(link => {
  if (window.location.pathname === link.getAttribute('href')) link.setAttribute('aria-current', 'page');
});
const kind = document.querySelector('#id_kind');
if (kind && document.querySelector('#id_number')) {
  // Uwagi UMP z 15.11.2026: rodzaj wniosku decyduje o polach — numer albo liczba tablic w puli.
  const toggle = () => {
    const individual = kind.value === 'I';
    [['number', individual], ['number_to', individual], ['count', !individual]].forEach(([name, shown]) => {
      const field = document.querySelector('#id_' + name);
      if (field) {
        field.closest('div').hidden = !shown;
        field.disabled = !shown;
      }
    });
  };
  kind.addEventListener('change', toggle);
  toggle();
}

const numberField = document.querySelector('#id_number');
const numberCheck = document.querySelector('[data-number-check]');
if (numberField && numberCheck) {
  // Podpowiedź przy wpisywaniu: czy numer (seria) jest wolny. Serwer i tak sprawdza przy zapisie.
  const seriesEnd = document.querySelector('#id_number_to');
  const message = document.createElement('p');
  message.className = 'number-check';
  message.setAttribute('aria-live', 'polite');
  numberField.closest('div').appendChild(message);
  let timer;
  const check = () => {
    clearTimeout(timer);
    const value = numberField.value.trim();
    if (value.length < 5) { message.textContent = ''; message.className = 'number-check'; return; }
    timer = setTimeout(async () => {
      const params = new URLSearchParams({ number: value, number_to: seriesEnd ? seriesEnd.value.trim() : '' });
      try {
        const response = await fetch(numberCheck.dataset.numberCheck + '?' + params, { credentials: 'same-origin' });
        const result = await response.json();
        message.textContent = result.message;
        message.className = 'number-check ' + (result.ok ? 'ok' : 'taken');
      } catch (error) {
        message.textContent = '';
      }
    }, 350);
  };
  numberField.addEventListener('input', check);
  if (seriesEnd) seriesEnd.addEventListener('input', check);
  if (numberField.value) check();
}

const autoFilter = document.querySelector('[data-auto-filter]');
if (autoFilter) {
  // Uwagi UMP z 15.11.2026: wybór filtra od razu odświeża listę, bez „Filtruj”.
  const submit = () => {
    autoFilter.querySelectorAll('input, select').forEach(field => { field.disabled = !field.value; });
    autoFilter.submit();
  };
  autoFilter.querySelectorAll('select, input[type="date"]').forEach(field => field.addEventListener('change', submit));
  const search = autoFilter.querySelector('input[name="q"]');
  if (search) {
    let timer;
    search.addEventListener('input', () => {
      clearTimeout(timer);
      timer = setTimeout(() => {
        try { sessionStorage.setItem('filter-focus', 'q'); } catch (error) {}
        submit();
      }, 600);
    });
    try {
      if (sessionStorage.getItem('filter-focus') === 'q') {
        sessionStorage.removeItem('filter-focus');
        search.focus();
        search.setSelectionRange(search.value.length, search.value.length);
      }
    } catch (error) {}
  }
  const button = autoFilter.querySelector('.filter-submit');
  if (button) button.hidden = true;
}

const poolPreview = document.querySelector('#pool-preview');
if (kind && poolPreview) {
  // Formularz przydziału pokazuje tylko zakres wybranego rodzaju puli.
  const showPreview = () => poolPreview.querySelectorAll('[data-pool-kind]').forEach(line => {
    line.hidden = line.dataset.poolKind !== kind.value;
  });
  kind.addEventListener('change', showPreview);
  showPreview();
}

const errorSummary = document.querySelector('[data-focus-errors]');
const feedback = errorSummary || document.querySelector('[data-focus-result]');
if (feedback) {
  // Fragment po linku „Przejdź do treści” może przywrócić fokus po załadowaniu.
  const focusErrors = () => requestAnimationFrame(() => feedback.focus());
  if (document.readyState === 'complete') focusErrors();
  else window.addEventListener('load', focusErrors, { once: true });
}
if (errorSummary) {
  errorSummary.querySelectorAll('a[href^="#"]').forEach(link => {
    link.addEventListener('click', event => {
      const field = document.getElementById(link.getAttribute('href').slice(1));
      if (field && field.getClientRects().length) {
        event.preventDefault();
        field.focus();
        field.scrollIntoView({ block: 'center' });
      }
    });
  });
}

document.querySelectorAll('.table-wrap').forEach(region => {
  const caption = region.querySelector('caption');
  region.setAttribute('role', 'region');
  region.setAttribute('aria-label', caption?.textContent.trim() || 'Tabela danych');
  const resize = () => {
    region.tabIndex = region.scrollWidth > region.clientWidth ? 0 : -1;
  };
  resize();
  if (window.ResizeObserver) new ResizeObserver(resize).observe(region);
});
