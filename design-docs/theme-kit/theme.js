const KEY = 'ds-theme';
const media = matchMedia('(prefers-color-scheme: light)');

export function getPreference() {
  try { const v = localStorage.getItem(KEY); if (v === 'light' || v === 'dark') return v; } catch {}
  return 'system';
}

function apply(pref) {
  const theme = pref === 'system' ? (media.matches ? 'light' : 'dark') : pref;
  const root = document.documentElement;
  if (root.getAttribute('data-theme') === theme) return;
  root.classList.add('ds-theme-switching');            // swap every component at once
  root.setAttribute('data-theme', theme);
  requestAnimationFrame(() => requestAnimationFrame(() => root.classList.remove('ds-theme-switching')));
}

export function setPreference(pref) {                  // 'light' | 'dark' | 'system'
  try { pref === 'system' ? localStorage.removeItem(KEY) : localStorage.setItem(KEY, pref); } catch {}
  apply(pref);
}

export function initTheme() {
  apply(getPreference());
  media.addEventListener('change', () => { if (getPreference() === 'system') apply('system'); });
  addEventListener('storage', (e) => { if (e.key === KEY) apply(getPreference()); });   // other tabs
}
