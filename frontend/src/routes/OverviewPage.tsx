import { Link } from 'react-router-dom'
import { useDevices } from '../api/devices'
import { type HealthBucket, type StatusCounts, useHealthTrend, useOverview } from '../api/overview'
import { useServices } from '../api/services'
import { AlertStateBadge } from '../components/AlertStateBadge'
import { Card } from '../components/Card'
import { HealthGauge, HealthRadar } from '../components/HealthGauge'
import { AlertsIcon, DevicesIcon, IntegrationsIcon, ServicesIcon } from '../components/icons'
import { PageHeader } from '../components/PageHeader'
import { StatusBadge } from '../components/StatusBadge'
import { SummaryTile } from '../components/SummaryTile'

type Overview = NonNullable<ReturnType<typeof useOverview>['data']>

/** Percentage of checked things that are healthy; a degraded one counts for half. Unknown ones are not counted. */
function healthPercent(counts: StatusCounts): number | null {
  const checked = counts.up + counts.down + counts.degraded
  return checked === 0 ? null : Math.round(((counts.up + counts.degraded / 2) / checked) * 100)
}

function healthScore(data: Overview): number {
  const parts = [healthPercent(data.devices), healthPercent(data.services)].filter((p): p is number => p !== null)
  return parts.length === 0 ? 100 : Math.round(parts.reduce((a, b) => a + b, 0) / parts.length)
}

function Panel({ title, to, children }: { title: string; to?: string; children: React.ReactNode }) {
  return (
    <Card className="p-4">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-base font-medium text-fg">{title}</h2>
        {to && (
          <Link to={to} className="text-xs text-fg-muted hover:text-accent-strong">
            More ›
          </Link>
        )}
      </div>
      {children}
    </Card>
  )
}

function Strip({ label, buckets, pick }: { label: string; buckets: HealthBucket[]; pick: (b: HealthBucket) => number | null }) {
  return (
    <div className="flex items-center gap-3">
      <span className="w-16 shrink-0 text-xs text-fg-muted">{label}</span>
      <div className="flex flex-1 gap-0.5">
        {buckets.map((bucket) => {
          const value = pick(bucket)
          const color =
            value === null ? 'bg-fg-subtle/25' : value >= 0.99 ? 'bg-emerald-500' : value >= 0.9 ? 'bg-amber-500' : 'bg-red-500'
          const title = `${new Date(bucket.hour).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}: ${
            value === null ? 'no data' : `${Math.round(value * 100)}% ok`
          }`
          return <span key={bucket.hour} title={title} className={`h-4 flex-1 rounded-[2px] ${color}`} />
        })}
      </div>
    </div>
  )
}

export function OverviewPage() {
  const { data, isLoading } = useOverview()
  return (
    <div>
      <PageHeader title="Overview" description="What's broken right now, and why." />
      {isLoading || !data ? <p className="mt-6 text-fg-muted">Loading…</p> : <Dashboard data={data} />}
    </div>
  )
}

function Dashboard({ data }: { data: Overview }) {
  const { data: trend } = useHealthTrend()
  const { data: devices } = useDevices()
  const { data: services } = useServices({ sort: 'latency', order: 'desc' })

  const firing = data.firing_alerts
  const integrationTotal = data.integrations_ok + data.integrations_error
  const axes = [
    { label: 'Devices', value: healthPercent(data.devices) ?? 100 },
    { label: 'Services', value: healthPercent(data.services) ?? 100 },
    { label: 'Integrations', value: integrationTotal === 0 ? 100 : Math.round((data.integrations_ok / integrationTotal) * 100) },
  ]
  const broken = [
    ...(devices ?? []).filter((d) => d.status === 'down' || d.status === 'degraded').map((d) => ({
      key: `d${d.id}`,
      to: `/devices/${d.id}`,
      name: d.display_name,
      kind: 'Device',
      status: d.status,
    })),
    ...(services ?? []).filter((s) => s.status === 'down').map((s) => ({
      key: `s${s.id}`,
      to: '/services',
      name: s.name,
      kind: 'Service',
      status: s.status,
    })),
  ].slice(0, 5)
  const slowest = (services ?? []).filter((s) => s.status === 'up' && s.last_latency_ms != null).slice(0, 5)

  return (
    <div className="mt-6 grid gap-4 lg:grid-cols-[20rem_1fr]">
      <Card className="flex flex-col items-center gap-2 p-4">
        <HealthGauge score={healthScore(data)} />
        <p className="px-2 text-center text-xs text-fg-muted">
          Average of device health and service health. Each is the share of checked items that are up, with a degraded one
          counting as half and unknown ones left out. Green is 75 or more, amber 50 to 74, red below 50. Integrations appear on
          the radar but do not affect the score.
        </p>
        <HealthRadar axes={axes} />
        <div className="mt-2 w-full border-t border-line pt-3">
          <div className="flex items-center justify-between">
            <span className="text-base font-medium">Pending alerts</span>
            <Link to="/alerts" className="font-mono text-xl tabular-nums text-fg hover:text-accent-strong">
              {firing.length}
            </Link>
          </div>
          {firing.length === 0 ? (
            <p className="py-6 text-center text-sm text-fg-muted">No pending alerts.</p>
          ) : (
            <ul className="mt-2 divide-y divide-line text-sm">
              {firing.slice(0, 5).map((state) => (
                <li key={state.id} className="flex items-center justify-between py-2">
                  <span>
                    {state.entity_type} #{state.entity_id}
                  </span>
                  <AlertStateBadge state={state.state} />
                </li>
              ))}
            </ul>
          )}
        </div>
      </Card>

      <div className="flex min-w-0 flex-col gap-4">
        <Panel title="24h health trend">
          <div className="flex flex-col gap-2">
            <Strip label="Devices" buckets={trend?.buckets ?? []} pick={(b) => b.devices} />
            <Strip label="Services" buckets={trend?.buckets ?? []} pick={(b) => b.services} />
          </div>
          <p className="mt-2 text-xs text-fg-subtle">Share of checks that succeeded in each hour; grey means nothing was checked.</p>
        </Panel>

        <Card className="grid gap-6 p-4 md:grid-cols-3">
          <div>
            <h2 className="mb-3 text-base font-medium">Network overview</h2>
            <div className="grid grid-cols-2 gap-4">
              <SummaryTile icon={<DevicesIcon className="h-5 w-5" />} label="Devices" value={data.devices.up + data.devices.down + data.devices.degraded + data.devices.unknown} />
              <SummaryTile icon={<ServicesIcon className="h-5 w-5" />} label="Services" value={data.services.up + data.services.down + data.services.degraded + data.services.unknown} />
              <SummaryTile icon={<IntegrationsIcon className="h-5 w-5" />} label="Integrations" value={integrationTotal} tone={data.integrations_error > 0 ? 'bad' : 'neutral'} />
              <SummaryTile icon={<AlertsIcon className="h-5 w-5" />} label="Firing" value={firing.length} tone={firing.length > 0 ? 'bad' : 'ok'} />
            </div>
          </div>
          <div>
            <h2 className="mb-3 flex items-center justify-between text-base font-medium">
              Needs attention
              <Link to="/devices" className="text-xs font-normal text-fg-muted hover:text-accent-strong">
                More ›
              </Link>
            </h2>
            {broken.length === 0 ? (
              <p className="py-4 text-sm text-fg-muted">Nothing is down or degraded.</p>
            ) : (
              <ul className="divide-y divide-line text-sm">
                {broken.map((item) => (
                  <li key={item.key} className="flex items-center justify-between gap-2 py-2">
                    <Link to={item.to} className="min-w-0 truncate hover:underline">
                      {item.name}
                      <span className="ml-1 text-xs text-fg-subtle">{item.kind}</span>
                    </Link>
                    <StatusBadge status={item.status} />
                  </li>
                ))}
              </ul>
            )}
          </div>
          <div>
            <h2 className="mb-3 flex items-center justify-between text-base font-medium">
              Slowest services
              <Link to="/services" className="text-xs font-normal text-fg-muted hover:text-accent-strong">
                More ›
              </Link>
            </h2>
            {slowest.length === 0 ? (
              <p className="py-4 text-sm text-fg-muted">No latency data yet.</p>
            ) : (
              <ul className="divide-y divide-line text-sm">
                {slowest.map((service) => (
                  <li key={service.id} className="flex items-center justify-between gap-2 py-2">
                    <span className="min-w-0 truncate">{service.name}</span>
                    <span className="font-mono text-xs tabular-nums text-fg-muted">{service.last_latency_ms?.toFixed(0)} ms</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </Card>

        <Panel title="Recent events" to="/events">
          {data.recent_events.length === 0 ? (
            <p className="text-sm text-fg-muted">No events yet.</p>
          ) : (
            <ul className="divide-y divide-line text-sm">
              {data.recent_events.map((event) => (
                <li key={event.id} className="py-2">
                  <span className="font-mono text-xs text-fg-muted">{new Date(event.ts).toLocaleTimeString()}</span> {event.message}
                </li>
              ))}
            </ul>
          )}
        </Panel>
      </div>
    </div>
  )
}
