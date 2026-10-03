(() => {
  const notice = document.querySelector('#session-notice');
  if (!notice) return;
  const form = notice.querySelector('[data-session-extend]');
  const button = form.querySelector('button');
  const extendNow = document.querySelector('[data-session-extend-now]');
  const loginLink = notice.querySelector('[data-session-login]');
  const title = notice.querySelector('h2');
  const message = notice.querySelector('[data-session-message]');
  let deadline = null;
  let warningSeconds = 120;
  let blocked = false;
  let warningShown = false;
  let busy = false;
  let pendingExtension = false;
  let feedbackTimer;
  let lastField;
  const sizeNotice = () => { notice.tabIndex = notice.scrollHeight > notice.clientHeight ? 0 : -1; };
  if (window.ResizeObserver) new ResizeObserver(sizeNotice).observe(notice);

  document.addEventListener('focusin', event => {
    if (!notice.contains(event.target) && event.target.closest('main')) lastField = event.target;
  });

  const restoreFocus = (force = false) => {
    if (force || notice.contains(document.activeElement)) {
      (lastField?.isConnected && lastField.getClientRects().length ? lastField : document.querySelector('#main'))?.focus();
    }
  };
  const show = (heading, text, controls, role = 'alert') => {
    // Kolejne odczyty tego samego stanu nie powtarzają komunikatu czytnika.
    if (!notice.hidden && title.textContent === heading && message.textContent === text &&
        notice.getAttribute('role') === role && form.hidden === (controls !== 'extend') &&
        loginLink.hidden === (controls !== 'login')) return;
    clearTimeout(feedbackTimer);
    notice.setAttribute('role', role);
    title.textContent = heading;
    message.textContent = text;
    form.hidden = controls !== 'extend';
    loginLink.hidden = controls !== 'login';
    notice.hidden = false;
    notice.scrollTop = 0;
    sizeNotice();
  };
  const warn = () => {
    if (warningShown || blocked) return;
    warningShown = true;
    show('Kończy się czas logowania', 'Przedłuż czas, aby kontynuować pracę. Wpisane dane pozostaną w formularzu.', 'extend');
  };
  const stop = (heading, text) => {
    blocked = true;
    deadline = null;
    show(heading, text, 'login');
  };

  const check = async (extend = false) => {
    if (busy) {
      if (extend) pendingExtension = true;
      return;
    }
    busy = true;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 8000);
    try {
      const headers = { Accept: 'application/json', 'X-Dyna-Session-Owner': notice.dataset.sessionOwner };
      if (extend) headers['X-CSRFToken'] = form.querySelector('[name=csrfmiddlewaretoken]').value;
      const response = await fetch(extend ? notice.dataset.extendUrl : notice.dataset.statusUrl, {
        method: extend ? 'POST' : 'GET', credentials: 'same-origin', cache: 'no-store', headers, signal: controller.signal,
      });
      if (response.status === 401) {
        stop('Logowanie wygasło', 'Wpisane pola pozostają na tej stronie. Zaloguj się w nowej karcie; odrzucone operacje nie zostaną ponowione.');
        return;
      }
      if (response.status === 409) {
        stop('Zmieniło się konto lub uprawnienia', 'Nie wysyłaj tego formularza jako inne konto. Zachowaj potrzebne dane i otwórz formularz ponownie.');
        return;
      }
      if (response.status === 403) {
        stop('Formularz wymaga odświeżenia', 'Nie potwierdzono przedłużenia. Zachowaj potrzebne dane i ponownie otwórz formularz po zalogowaniu.');
        return;
      }
      if (!response.ok) throw new Error('session-unavailable');
      const data = await response.json();
      if (!Number.isFinite(data.remaining_seconds) || !Number.isFinite(data.warning_seconds)) throw new Error('session-unavailable');
      if (blocked) {
        show('Otwórz formularz ponownie', 'Nie odświeżyliśmy ani nie wysłaliśmy starych pól po zmianie logowania. Zachowaj potrzebne dane i otwórz świeży formularz.', 'login');
        return;
      }
      deadline = performance.now() + data.remaining_seconds * 1000;
      warningSeconds = data.warning_seconds;
      if (extend) {
        warningShown = false;
        show('Czas logowania przedłużony', 'Możesz kontynuować pracę. Wpisane dane pozostają w formularzu.', '', 'status');
        restoreFocus(true);
        feedbackTimer = setTimeout(() => { if (!warningShown && !blocked) notice.hidden = true; }, 8000);
      } else if (data.remaining_seconds <= warningSeconds) warn();
      else if (warningShown) {
        warningShown = false;
        restoreFocus();
        notice.hidden = true;
      }
    } catch {
      show('Nie można sprawdzić czasu logowania', 'Sprawdź połączenie i spróbuj przedłużyć czas ponownie. Nie potwierdzono przedłużenia ani nie wysłano danych formularza.', blocked ? 'login' : 'extend');
    } finally {
      clearTimeout(timeout);
      busy = false;
      button.disabled = blocked;
      if (extendNow) extendNow.disabled = blocked;
      if (pendingExtension) {
        pendingExtension = false;
        if (!blocked) check(true);
      }
    }
  };

  form.addEventListener('submit', event => {
    event.preventDefault();
    button.disabled = true;
    check(true);
  });
  if (extendNow) {
    extendNow.hidden = false;
    extendNow.addEventListener('click', () => {
      extendNow.disabled = true;
      check(true);
    });
  }
  document.addEventListener('submit', event => {
    if (blocked && event.target !== form) {
      event.preventDefault();
      notice.focus();
    }
  }, true);
  setInterval(() => {
    if (deadline === null || blocked) return;
    if (performance.now() >= deadline) check();
    else if ((deadline - performance.now()) / 1000 <= warningSeconds) warn();
  }, 1000);
  setInterval(() => check(), 20000);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) check(); });
  check();
})();
