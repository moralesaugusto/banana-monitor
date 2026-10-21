// Small hand-rolled inline SVG icons - no icon library dependency.
// All icons share a 20x20 viewBox, currentColor stroke, and no fill so they
// pick up text color/size utilities like any other inline element.

import type { SVGProps } from 'react'

type IconProps = SVGProps<SVGSVGElement>

function base(props: IconProps) {
  return {
    width: 16,
    height: 16,
    viewBox: '0 0 20 20',
    fill: 'none',
    stroke: 'currentColor',
    strokeWidth: 1.6,
    strokeLinecap: 'round' as const,
    strokeLinejoin: 'round' as const,
    ...props,
  }
}

export function OverviewIcon(props: IconProps) {
  return (
    <svg {...base(props)}>
      <rect x="2.5" y="2.5" width="6" height="6" rx="1.2" />
      <rect x="11.5" y="2.5" width="6" height="6" rx="1.2" />
      <rect x="2.5" y="11.5" width="6" height="6" rx="1.2" />
      <rect x="11.5" y="11.5" width="6" height="6" rx="1.2" />
    </svg>
  )
}

export function DevicesIcon(props: IconProps) {
  return (
    <svg {...base(props)}>
      <rect x="2.5" y="3" width="15" height="9" rx="1.4" />
      <path d="M6.5 16.5h7M10 12v4.5" />
    </svg>
  )
}

export function ServicesIcon(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M7 3v3M13 3v3M4.5 6h11l-.7 6.2a3 3 0 0 1-3 2.66h-3.6a3 3 0 0 1-3-2.66Z" />
      <path d="M10 14.9V17" />
    </svg>
  )
}

export function AlertsIcon(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M10 2.8c-3.4 4-3.9 6.1-3.9 8.7 0 1.7.6 2.7 1.2 3.4H12.7c.6-.7 1.2-1.7 1.2-3.4 0-2.6-.5-4.7-3.9-8.7Z" />
      <path d="M8.4 16.9a1.7 1.7 0 0 0 3.2 0" />
    </svg>
  )
}

export function EventsIcon(props: IconProps) {
  return (
    <svg {...base(props)}>
      <circle cx="10" cy="10" r="7.2" />
      <path d="M10 6v4.2l3 1.8" />
    </svg>
  )
}

export function DiscoveryIcon(props: IconProps) {
  return (
    <svg {...base(props)}>
      <circle cx="9.2" cy="9.2" r="5.2" />
      <path d="m15.8 15.8 2.2 2.2" />
    </svg>
  )
}

export function IntegrationsIcon(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M8 4.5H5A1.5 1.5 0 0 0 3.5 6v3" />
      <path d="M12 4.5h3A1.5 1.5 0 0 1 16.5 6v3" />
      <path d="M8 15.5H5A1.5 1.5 0 0 1 3.5 14v-3" />
      <path d="M12 15.5h3a1.5 1.5 0 0 0 1.5-1.5v-3" />
      <circle cx="10" cy="10" r="2.4" />
    </svg>
  )
}

export function NetworksIcon(props: IconProps) {
  return (
    <svg {...base(props)}>
      <circle cx="10" cy="4" r="1.8" />
      <circle cx="4.5" cy="16" r="1.8" />
      <circle cx="15.5" cy="16" r="1.8" />
      <path d="M10 5.8v4.7M10 10.5 4.9 14.4M10 10.5l5.1 3.9" />
    </svg>
  )
}

export function ChevronRightIcon(props: IconProps) {
  return (
    <svg {...base(props)} width={12} height={12}>
      <path d="m7.5 4 4 6-4 6" />
    </svg>
  )
}

export function ChatIcon(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M3 4.5h14a1 1 0 0 1 1 1v8a1 1 0 0 1-1 1H8l-4 3v-3H3a1 1 0 0 1-1-1v-8a1 1 0 0 1 1-1Z" />
    </svg>
  )
}

export function SettingsIcon(props: IconProps) {
  return (
    <svg {...base(props)}>
      <circle cx="10" cy="10" r="2.6" />
      <path d="M10 3.3v2M10 14.7v2M16.7 10h-2M5.3 10h-2M14.7 5.3l-1.4 1.4M6.7 13.3l-1.4 1.4M14.7 14.7l-1.4-1.4M6.7 6.7 5.3 5.3" />
    </svg>
  )
}

export function InfoIcon(props: IconProps) {
  return (
    <svg {...base(props)}>
      <circle cx="10" cy="10" r="7.2" />
      <path d="M10 9v5" />
      <circle cx="10" cy="6.3" r="0.15" fill="currentColor" stroke="none" />
    </svg>
  )
}

export function CloseIcon(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M5 5l10 10M15 5 5 15" />
    </svg>
  )
}

export function PulseDot({ ok }: { ok: boolean }) {
  return (
    <span className="relative inline-flex h-2 w-2">
      {ok && (
        <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-500 opacity-60" />
      )}
      <span
        className={`relative inline-flex h-2 w-2 rounded-full ${ok ? 'bg-emerald-500' : 'bg-red-500'}`}
      />
    </span>
  )
}

// ---- Shell icons: the same outline style (1.6 stroke, round caps) at the sizes the shell needs. ----

export function DashboardIcon(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M3 13.5a7 7 0 1 1 14 0" />
      <path d="M10 13.5 13.2 8.8" />
      <circle cx="10" cy="13.5" r="1" />
    </svg>
  )
}

export function MapIcon(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M2.5 5.2 7 3.5l6 2 4.5-1.7v11l-4.5 1.7-6-2-4.5 1.7Z" />
      <path d="M7 3.5v11M13 5.5v11" />
    </svg>
  )
}

export function InsightsIcon(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M10 3.2a6.8 6.8 0 1 0 6.8 6.8H10Z" />
      <path d="M12.6 2.4a6.8 6.8 0 0 1 5 5H12.6Z" />
    </svg>
  )
}

export function LogsIcon(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M5 2.8h6.5L15 6.3v10.9H5Z" />
      <path d="M11.5 2.8v3.5H15M7.6 10h4.8M7.6 13h4.8" />
    </svg>
  )
}

export function SparkIcon(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M10 2.8 11.6 8l5.2 1.6-5.2 1.6L10 16.4l-1.6-5.2L3.2 9.6 8.4 8Z" />
    </svg>
  )
}

export function ToolsIcon(props: IconProps) {
  return (
    <svg {...base(props)}>
      <rect x="3" y="6" width="14" height="10" rx="1.6" />
      <path d="M7.5 6V4.3A1.3 1.3 0 0 1 8.8 3h2.4a1.3 1.3 0 0 1 1.3 1.3V6M3 10.5h14" />
    </svg>
  )
}

export function SearchIcon(props: IconProps) {
  return (
    <svg {...base(props)}>
      <circle cx="9" cy="9" r="5.5" />
      <path d="m13.2 13.2 3.6 3.6" />
    </svg>
  )
}

export function RefreshIcon(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M16.5 10a6.5 6.5 0 1 1-2-4.7" />
      <path d="M16.8 3.5v3.3h-3.3" />
    </svg>
  )
}

export function SunIcon(props: IconProps) {
  return (
    <svg {...base(props)}>
      <circle cx="10" cy="10" r="3.2" />
      <path d="M10 2.5v1.8M10 15.7v1.8M2.5 10h1.8M15.7 10h1.8M4.7 4.7 6 6M14 14l1.3 1.3M15.3 4.7 14 6M6 14l-1.3 1.3" />
    </svg>
  )
}

export function MoonIcon(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M16.5 11.6A6.8 6.8 0 0 1 8.4 3.5a6.8 6.8 0 1 0 8.1 8.1Z" />
    </svg>
  )
}

export function UserIcon(props: IconProps) {
  return (
    <svg {...base(props)}>
      <circle cx="10" cy="7" r="3.2" />
      <path d="M3.8 17c.6-3 3-4.6 6.2-4.6s5.6 1.6 6.2 4.6" />
    </svg>
  )
}

export function SidebarIcon(props: IconProps) {
  return (
    <svg {...base(props)}>
      <rect x="2.8" y="3.5" width="14.4" height="13" rx="2" />
      <path d="M7.5 3.5v13" />
    </svg>
  )
}

export function ChevronDownIcon(props: IconProps) {
  return (
    <svg {...base(props)} width={12} height={12}>
      <path d="m4 7.5 6 4 6-4" />
    </svg>
  )
}

export function GlobeIcon(props: IconProps) {
  return (
    <svg {...base(props)}>
      <circle cx="10" cy="10" r="7.2" />
      <path d="M2.8 10h14.4M10 2.8c2 2 3 4.4 3 7.2s-1 5.2-3 7.2c-2-2-3-4.4-3-7.2s1-5.2 3-7.2Z" />
    </svg>
  )
}

export function LockIcon(props: IconProps) {
  return (
    <svg {...base(props)}>
      <rect x="4.2" y="9" width="11.6" height="8" rx="1.6" />
      <path d="M6.8 9V6.6a3.2 3.2 0 0 1 6.4 0V9" />
    </svg>
  )
}

export function ReportsIcon(props: IconProps) {
  return (
    <svg {...base(props)}>
      <rect x="4" y="3.2" width="12" height="14" rx="1.6" />
      <path d="M7.2 13.5v-2.2M10 13.5V8.8M12.8 13.5v-3.4" />
    </svg>
  )
}

export function KebabIcon(props: IconProps) {
  return (
    <svg {...base(props)}>
      <circle cx="10" cy="4.5" r="0.9" fill="currentColor" />
      <circle cx="10" cy="10" r="0.9" fill="currentColor" />
      <circle cx="10" cy="15.5" r="0.9" fill="currentColor" />
    </svg>
  )
}

export function DeleteIcon(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M4.5 6h11M8 6V4.3c0-.6.4-1 1-1h2c.6 0 1 .4 1 1V6M7 6l.7 9.4c0 .6.5 1 1 1h2.6c.5 0 1-.4 1-1L13 6" />
      <path d="M8.5 9v4M11.5 9v4" />
    </svg>
  )
}

export function ToggleIcon(props: IconProps) {
  return (
    <svg {...base(props)}>
      <rect x="2.5" y="6.5" width="15" height="7" rx="3.5" />
      <circle cx="13.5" cy="10" r="2.1" fill="currentColor" stroke="none" />
    </svg>
  )
}

export function KeyIcon(props: IconProps) {
  return (
    <svg {...base(props)}>
      <circle cx="6.3" cy="10" r="3.3" />
      <path d="M9.4 10h8.1M14.5 10v3M16.6 10v2" />
    </svg>
  )
}

export function LoopIcon(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M4 9.5V8a3 3 0 0 1 3-3h8" />
      <path d="M12.5 2.5 15.5 5l-3 2.5" />
      <path d="M16 10.5V12a3 3 0 0 1-3 3H5" />
      <path d="M7.5 17.5 4.5 15l3-2.5" />
    </svg>
  )
}
