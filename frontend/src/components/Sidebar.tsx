import { useMemo, useState, type ReactNode } from 'react'
import { Link, NavLink, useLocation } from 'react-router-dom'
import { useAiModeSettings } from '../api/aiMode'
import { useHealth } from '../api/health'
import { BananaLogo } from './BananaLogo'
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
  KnowledgeIcon,
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
      { to: '/ai/runs', label: 'History', icon: EventsIcon },
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
        label: 'Knowledge',
        icon: KnowledgeIcon,
        children: [
          { to: '/ai/knowledge', label: 'Browse', icon: KnowledgeIcon, end: true },
          { to: '/ai/knowledge/map', label: 'Map', icon: MapIcon },
          { to: '/ai/knowledge/settings', label: 'Settings', icon: SettingsIcon },
          { to: '/ai/knowledge/learn', label: 'How it works', icon: InfoIcon },
        ],
      },
      {
        label: 'AI Settings',
        icon: ToolsIcon,
        children: [
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
      { to: '/integrations', label: 'Credentials & Keys', icon: IntegrationsIcon },
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

/** With the knowledge base off, only "Settings" stays under the Knowledge parent - the one page
 * that must always be reachable to turn it back on (see docs/decisions.md). Browse/Map/How it
 * works would otherwise show a page with nothing useful to do on it. */
function navGroups(knowledgeBaseOn: boolean): NavGroup[] {
  if (knowledgeBaseOn) return NAV_GROUPS
  return NAV_GROUPS.map((group) => ({
    ...group,
    entries: group.entries.map((entry) =>
      isParent(entry) && entry.label === 'Knowledge'
        ? { ...entry, children: entry.children.filter((c) => c.label === 'Settings') }
        : entry,
    ),
  }))
}

function linkClasses(isActive: boolean, collapsed: boolean): string {
  return `group relative flex items-center gap-3 rounded-control px-3 py-2 text-sm transition-colors ${
    collapsed ? 'justify-center px-0' : ''
  } ${
    isActive
      ? 'bg-accent-soft font-medium text-fg'
      : 'text-fg-muted hover:bg-fg-subtle/10 hover:text-fg'
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
          <item.icon className={`h-[18px] w-[18px] shrink-0 ${isActive ? 'text-fg' : 'text-fg-muted group-hover:text-fg'}`} />
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
        className="flex w-full items-center gap-3 rounded-control px-3 py-2 text-sm text-fg-muted hover:bg-fg-subtle/10 hover:text-fg"
        onClick={() => setOpenByHand(!open)}
      >
        <entry.icon className="h-[18px] w-[18px] shrink-0 text-fg-muted" />
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
      className={`flex items-center gap-2 rounded-control border border-line px-3 py-2.5 text-sm text-fg-muted ${collapsed ? 'justify-center px-0' : ''}`}
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
  const { data: aiSettings } = useAiModeSettings()
  // Defaults to shown while the setting is still loading (or on any page that doesn't otherwise
  // need it) - hiding first and revealing a moment later would flicker, and showing by default
  // never strands anyone (worst case, a page they could already reach stays reachable).
  const groups = useMemo(() => navGroups(aiSettings?.knowledge_base_enabled ?? true), [aiSettings])
  return (
    <aside
      aria-label="Main navigation"
      className={`fixed inset-y-0 left-0 z-40 flex shrink-0 flex-col overflow-y-auto border-r border-line bg-surface transition-[width,transform] md:sticky md:inset-auto md:top-3 md:m-3 md:mr-0 md:h-[calc(100vh-1.5rem)] md:translate-x-0 md:rounded-card md:border ${
        collapsed ? 'md:w-16' : 'md:w-60'
      } w-60 ${mobileOpen ? 'translate-x-0' : '-translate-x-full'}`}
    >
      <div className={`flex items-center px-3 pt-4 ${collapsed ? 'flex-col gap-2' : 'justify-between'}`}>
        <Link to="/" aria-label="Banana home" className="flex items-center gap-2 px-2">
          <BananaLogo size={28} />
          {!collapsed && <span className="text-[15px] font-semibold tracking-tight">Banana</span>}
        </Link>
        <button
          type="button"
          onClick={onToggleCollapsed}
          aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          className="hidden h-8 w-8 items-center justify-center rounded-control text-fg-muted hover:bg-fg-subtle/10 hover:text-fg md:flex"
        >
          <SidebarIcon className="h-[18px] w-[18px]" />
        </button>
      </div>

      <nav onClick={onNavigate} className="mt-4 flex flex-1 flex-col gap-4 px-3 pb-3">
        {groups.map((group) => (
          <div key={group.label}>
            {collapsed ? (
              <div className="mx-2 mb-1.5 border-t border-line" />
            ) : (
              <div className="px-3 pb-1.5 text-xs text-fg-subtle">{group.label}</div>
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
      <div className="px-3 pb-3">
        <ScopeBox collapsed={collapsed} />
      </div>
    </aside>
  )
}
