// Wersja external: skrypty, CSS i worker wyłącznie z własnej instancji.
const captchaScript = document.querySelector('script[src$="/public-captcha.js"]');
const captchaWorker = new URL('altcha/pbkdf2.js', captchaScript.src);
window.$altcha.algorithms.set('PBKDF2/SHA-256', () => new Worker(captchaWorker));
// Jeden widoczny odnośnik atrybucji, dostępny również klawiszem Tab.
window.$altcha.i18n.set('pl', {
  ...window.$altcha.i18n.get('pl'),
  footer: 'Chronione przez <a href="https://altcha.org/" target="_blank" rel="noopener" aria-label="Altcha (oficjalna strona internetowa)">ALTCHA</a>',
});
const publicCaptchaConfiguration = { humanInteractionSignature: false, hideLogo: true };
window.$altcha.defaults.set(publicCaptchaConfiguration);
const publicWidget = document.querySelector('altcha-widget');
if (publicWidget) publicWidget.configure(publicCaptchaConfiguration);
