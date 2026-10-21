/** Pins light or dark over the OS preference; the choice survives reloads. */
export function applyStoredTheme() {
  try {
    const stored = localStorage.getItem('banana-theme')
    if (stored === 'light' || stored === 'dark') document.documentElement.dataset.theme = stored
  } catch {
    // storage blocked: fall back to the OS preference
  }
}
