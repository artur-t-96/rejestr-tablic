document.querySelectorAll('.sidebar nav a').forEach(link => {
  if (window.location.pathname === link.getAttribute('href')) link.setAttribute('aria-current', 'page');
});
const kind = document.querySelector('#id_kind');
if (kind && document.querySelector('#id_owner')) {
  const toggle = () => {
    ['number', 'owner', 'address', 'vin'].forEach(name => {
      const field = document.querySelector('#id_' + name);
      if (field) {
        field.closest('div').hidden = kind.value !== 'I';
        field.disabled = kind.value !== 'I';
      }
    });
    ['count', 'station', 'justification'].forEach(name => {
      const field = document.querySelector('#id_' + name);
      if (field) {
        field.closest('div').hidden = kind.value === 'I';
        field.disabled = kind.value === 'I';
        if (name === 'count') field.required = kind.value !== 'I';
      }
    });
  };
  kind.addEventListener('change', toggle);
  toggle();
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
