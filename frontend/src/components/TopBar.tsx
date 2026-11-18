import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { useLogout, useMe } from '../api/auth'
import { useAiStatus } from '../api/aiMode'
import { useInternetAccess } from '../api/system'
import { GlobeIcon, LoopIcon, RefreshIcon, SidebarIcon } from './icons'
import { ThemeToggle } from './ThemeToggle'

const iconButton =
  'flex h-9 w-9 items-center justify-center rounded-full text-fg-muted transition-colors hover:bg-fg-subtle/15 hover:text-fg focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-current'

function UserMenu() {
  const { data: me } = useMe()
  const logout = useLogout()
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const close = (event: MouseEvent) => {
      if (!ref.current?.contains(event.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [open])

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        aria-label="Account menu"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="flex h-8 w-8 items-center justify-center rounded-full border border-line bg-surface text-sm font-medium text-fg"
      >
        {(me?.username ?? '?').slice(0, 1).toUpperCase()}
      </button>
      {open && (
        <div className="absolute right-0 top-11 z-50 w-56 rounded-card border border-line bg-surface py-1 text-sm text-fg shadow-lg">
          <div className="border-b border-line px-3 py-2 text-xs text-fg-muted">
            Signed in as <span className="font-medium text-fg">{me?.username}</span>
          </div>
          <Link to="/system" className="block px-3 py-2 hover:bg-fg-subtle/10" onClick={() => setOpen(false)}>
            Account and settings
          </Link>
          <Link to="/about" className="block px-3 py-2 hover:bg-fg-subtle/10" onClick={() => setOpen(false)}>
            About Banana
          </Link>
          <button
            type="button"
            className="block w-full px-3 py-2 text-left hover:bg-fg-subtle/10 disabled:opacity-50"
            disabled={logout.isPending}
            onClick={() => logout.mutate()}
          >
            Sign out
          </button>
        </div>
      )}
    </div>
  )
}

/** Shown only while the Master Discoverer runs in its continuous loop; pulses while a run is active. */
function LoopIndicator() {
  const { data: status } = useAiStatus()
  if (!status?.ai_enabled || !status.schedule.schedule_enabled) return null
  const { schedule, run } = status
  const next = schedule.next_run_at ? ` Next run at ${new Date(schedule.next_run_at).toLocaleTimeString()}.` : ''
  const title = `AI discovery loop is on: a run starts ${schedule.schedule_interval_seconds}s after the previous one finishes.${run ? ' A run is active now.' : next}`
  return (
    <Link to="/ai/workflow" aria-label="AI discovery loop is on" title={title} className={iconButton}>
      <LoopIcon className={`h-5 w-5 ${run ? 'animate-spin [animation-duration:3s]' : ''}`} />
    </Link>
  )
}

/** Shown while any enabled agent holds a web tool; links to the kill switch in Settings. */
function InternetIndicator() {
  const { data } = useInternetAccess()
  if (!data || data.agents.length === 0) return null
  const names = data.agents.join(', ')
  const title = data.blocked
    ? `Agent internet access is blocked by the kill switch (configured for: ${names}). Open settings.`
    : `Internet access is on for AI agents: ${names}. Open settings.`
  return (
    <Link
      to="/ai/config#internet"
      aria-label={data.blocked ? 'Agent internet access is blocked' : 'Agent internet access is on'}
      title={title}
      className={`${iconButton} relative`}
    >
      <GlobeIcon className="h-5 w-5" />
      <span
        className={`absolute -bottom-0.5 -right-0.5 rounded px-1 text-[9px] font-bold leading-4 text-white ${data.blocked ? 'bg-red-900' : 'bg-red-600'}`}
      >
        {data.blocked ? 'OFF' : 'ON'}
      </span>
    </Link>
  )
}

/** The slim top strip: mobile menu button on the left, quick actions on the right. */
export function TopBar({ onMenu }: { onMenu: () => void }) {
  const queryClient = useQueryClient()
  return (
    <header className="flex h-14 shrink-0 items-center justify-between gap-2 border-b border-line bg-surface px-3 md:px-4">
      <div className="flex items-center gap-2">
        <button type="button" aria-label="Open menu" className={`${iconButton} md:hidden`} onClick={onMenu}>
          <SidebarIcon className="h-5 w-5" />
        </button>
      </div>

      <div className="flex items-center gap-1">
        <span className="mr-2 hidden text-xs text-fg-muted xl:inline">
          <span className="font-semibold text-fg">Banana</span> - Built-in Alerting for Networks, Appliances, Nodes and Apps
        </span>
        <InternetIndicator />
        <LoopIndicator />
        <button
          type="button"
          aria-label="Refresh data"
          title="Refresh data"
          className={iconButton}
          onClick={() => queryClient.invalidateQueries()}
        >
          <RefreshIcon className="h-5 w-5" />
        </button>
        <ThemeToggle className="flex h-9 w-9 items-center justify-center rounded-control bg-accent text-on-accent transition-opacity hover:opacity-85" />
        <UserMenu />
      </div>
    </header>
  )
}
