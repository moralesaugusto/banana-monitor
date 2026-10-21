import { useState } from 'react'
import { MoonIcon, SunIcon } from './icons'

type Theme = 'light' | 'dark'

function currentTheme(): Theme {
  const pinned = document.documentElement.dataset.theme
  if (pinned === 'light' || pinned === 'dark') return pinned
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

export function ThemeToggle({ className = '' }: { className?: string }) {
  const [theme, setTheme] = useState<Theme>(currentTheme)
  const next = theme === 'dark' ? 'light' : 'dark'

  function toggle() {
    document.documentElement.dataset.theme = next
    try {
      localStorage.setItem('banana-theme', next)
    } catch {
      // not persisted
    }
    setTheme(next)
  }

  return (
    <button type="button" onClick={toggle} aria-label={`Switch to ${next} mode`} title={`Switch to ${next} mode`} className={className}>
      {theme === 'dark' ? <SunIcon className="h-5 w-5" /> : <MoonIcon className="h-5 w-5" />}
    </button>
  )
}
