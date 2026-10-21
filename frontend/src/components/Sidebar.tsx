import { useState, type ReactNode } from 'react'
import { NavLink, useLocation } from 'react-router-dom'
import { useHealth } from '../api/health'
import {
  AlertsIcon,
  ChevronDownIcon,
  ChevronRightIcon,
  DashboardIcon,
  DevicesIcon,
  DiscoveryIcon,
  EventsIcon,
  InfoIcon,
  InsightsIcon,
  IntegrationsIcon,
  LockIcon,
  LogsIcon,
  MapIcon,
  NetworksIcon,
  PulseDot,
  ReportsIcon,
  ServicesIcon,
  SettingsIcon,
  SidebarIcon,
  SparkIcon,
  ToolsIcon,
} from './icons'

type IconType = (props: { className?: string }) => ReactNode

interface NavLeaf {
  to: string
  label: string
  icon: IconType
  end?: boolean
  beta?: boolean
}

interface NavParent {
  label: string
  icon: IconType
  children: NavLeaf[]
}

type NavEntry = NavLeaf | NavParent

interface NavGroup {
  label: string
  entries: NavEntry[]
}

const isParent = (entry: NavEntry): entry is NavParent => 'children' in entry

const NAV_GROUPS: NavGroup[] = [
  {
    label: 'Management',
    entries: [
      { to: '/', label: 'Dashboard', icon: DashboardIcon, end: true },
      { to: '/devices', label: 'Devices', icon: DevicesIcon },
      { to: '/services', label: 'Services', icon: ServicesIcon },
    ],
  },
  {
    label: 'Monitoring',
    entries: [
      { to: '/network-map', label: 'Network Map', icon: MapIcon },
      { to: '/alerts', label: 'Alerts', icon: AlertsIcon },
      { to: '/events', label: 'Events', icon: EventsIcon },
      { to: '/reports', label: 'Reports', icon: ReportsIcon },
    ],
  },
  {
    label: 'Intelligent Ops',
    entries: [
      { to: '/ai', label: 'AI Mode Single', icon: SparkIcon, end: true },
      { to: '/ai/workflow', label: 'AI Workflow', icon: MapIcon },
      { to: '/ai/agents', label: 'Agents', icon: InsightsIcon },
      { to: '/ai/messages', label: 'Messages', icon: LogsIcon },
      {
        label: 'AI Settings',
        icon: ToolsIcon,
        children: [
          { to: '/ai/runs', label: 'History', icon: EventsIcon },
          { to: '/ai/bus', label: 'Bus', icon: LogsIcon },
          { to: '/ai/map', label: 'Map', icon: MapIcon },
          { to: '/ai/config', label: 'Settings', icon: SettingsIcon },
          { to: '/ai/tools', label: 'Tools and guardrails', icon: ToolsIcon },
          { to: '/ai/learn', label: 'How it works', icon: InfoIcon },
        ],
      },
    ],
  },
  {
    label: 'Configuration',
    entries: [
      { to: '/discovery', label: 'Discovery', icon: DiscoveryIcon },
      {
        label: 'Integrations',
        icon: IntegrationsIcon,
        children: [
          { to: '/integrations', label: 'Configured', icon: IntegrationsIcon, end: true },
          { to: '/integrations/credentials', label: 'Credentials', icon: LockIcon },
          { to: '/integrations/learn', label: 'How it works', icon: InfoIcon },
        ],
      },
      { to: '/networks', label: 'Networks', icon: NetworksIcon },
      { to: '/system', label: 'Settings', icon: SettingsIcon },
    ],
  },
  {
    label: 'Maintenance',
    entries: [
      { to: '/about', label: 'About', icon: InfoIcon, end: true },
      { to: '/about/audit', label: 'Audit Log', icon: LogsIcon },
    ],
  },
]

function linkClasses(isActive: boolean, collapsed: boolean): string {
  return `group relative flex items-center gap-3 rounded-control px-3 py-2 text-sm transition-colors ${
    collapsed ? 'justify-center px-0' : ''
  } ${
    isActive
      ? 'bg-surface font-medium text-accent-strong shadow-sm'
      : 'text-fg hover:bg-fg-subtle/10'
  }`
}

function Leaf({ item, collapsed, nested = false }: { item: NavLeaf; collapsed: boolean; nested?: boolean }) {
  return (
    <NavLink
      to={item.to}
      end={item.end}
      title={collapsed ? item.label : undefined}
      className={({ isActive }) => `${linkClasses(isActive, collapsed)} ${nested ? 'ml-4 py-1.5' : ''}`}
    >
      {({ isActive }) => (
        <>
          {isActive && (
            <span
              aria-hidden
              className="absolute left-0 top-1.5 bottom-1.5 w-[3px] rounded-full"
              style={{ backgroundImage: 'var(--accent-gradient)' }}
            />
          )}
          <item.icon className={`h-5 w-5 shrink-0 ${isActive ? 'text-accent' : 'text-fg-muted group-hover:text-fg'}`} />
          {!collapsed && <span className="truncate">{item.label}</span>}
          {!collapsed && item.beta && (
            <span className="ml-auto rounded-sm bg-accent-soft-strong px-1.5 py-0.5 text-[10px] font-medium text-accent-strong">BETA</span>
          )}
        </>
      )}
    </NavLink>
  )
}

function Parent({ entry, collapsed }: { entry: NavParent; collapsed: boolean }) {
  const { pathname } = useLocation()
  const childActive = entry.children.some((child) => pathname === child.to || pathname.startsWith(`${child.to}/`))
  const [openByHand, setOpenByHand] = useState<boolean | null>(null)
  const open = openByHand ?? childActive

  if (collapsed) {
    // Icon-only rail: the parent is a single link to its first page.
    return <Leaf item={{ ...entry.children[0], icon: entry.icon, label: entry.label }} collapsed />
  }
  return (
    <div>
      <button
        type="button"
        aria-expanded={open}
        className="flex w-full items-center gap-3 rounded-control px-3 py-2 text-sm text-fg hover:bg-fg-subtle/10"
        onClick={() => setOpenByHand(!open)}
      >
        <entry.icon className="h-5 w-5 shrink-0 text-fg-muted" />
        <span className="truncate">{entry.label}</span>
        <span className="ml-auto text-fg-subtle">{open ? <ChevronDownIcon /> : <ChevronRightIcon />}</span>
      </button>
      {open && (
        <div className="mt-0.5 flex flex-col gap-0.5">
          {entry.children.map((child) => (
            <Leaf key={child.to} item={child} collapsed={false} nested />
          ))}
        </div>
      )}
    </div>
  )
}

function ScopeBox({ collapsed }: { collapsed: boolean }) {
  const { data, isError, isLoading } = useHealth()
  const ok = !isError && !isLoading && data?.status === 'ok'
  const text = isLoading ? 'Checking platform…' : ok ? 'Platform healthy' : 'Platform unreachable'
  return (
    <div
      className={`flex items-center gap-2 rounded-control bg-fg-subtle/10 px-3 py-2.5 text-sm ${collapsed ? 'justify-center px-0' : ''}`}
      title={text}
    >
      <PulseDot ok={ok} />
      {!collapsed && <span className="truncate">{text}</span>}
    </div>
  )
}

/** The left rail: a collapse toggle, the platform status, then labelled groups of icon links. */
export function Sidebar({
  collapsed,
  onToggleCollapsed,
  mobileOpen,
  onNavigate,
}: {
  collapsed: boolean
  onToggleCollapsed: () => void
  mobileOpen: boolean
  onNavigate: () => void
}) {
  return (
    <aside
      aria-label="Main navigation"
      className={`fixed inset-y-0 left-0 top-14 z-40 flex shrink-0 flex-col overflow-y-auto border-r border-line bg-canvas transition-[width,transform] md:sticky md:top-14 md:h-[calc(100vh-3.5rem)] md:translate-x-0 ${
        collapsed ? 'md:w-16' : 'md:w-56'
      } w-60 ${mobileOpen ? 'translate-x-0' : '-translate-x-full'}`}
    >
      <div className="px-3 pt-3">
        <button
          type="button"
          onClick={onToggleCollapsed}
          aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          className="hidden h-9 w-9 items-center justify-center rounded-control text-fg-muted hover:bg-fg-subtle/10 hover:text-fg md:flex"
        >
          <SidebarIcon className="h-5 w-5" />
        </button>
        <div className="mt-2">
          <ScopeBox collapsed={collapsed} />
        </div>
      </div>

      <nav onClick={onNavigate} className="mt-3 flex flex-1 flex-col gap-4 px-3 pb-4">
        {NAV_GROUPS.map((group) => (
          <div key={group.label}>
            {collapsed ? (
              <div className="mx-2 mb-1.5 border-t border-line" />
            ) : (
              <div className="px-2 pb-1.5 text-xs font-medium text-fg-subtle">{group.label}</div>
            )}
            <div className="flex flex-col gap-0.5">
              {group.entries.map((entry) =>
                isParent(entry) ? (
                  <Parent key={entry.label} entry={entry} collapsed={collapsed} />
                ) : (
                  <Leaf key={entry.to} item={entry} collapsed={collapsed} />
                ),
              )}
            </div>
          </div>
        ))}
      </nav>
    </aside>
  )
}
