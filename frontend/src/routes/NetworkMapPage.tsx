import { Link, useParams } from 'react-router-dom'
import { useNetworkMap, useNetworks } from '../api/networks'
import { Card } from '../components/Card'
import { PageHeader } from '../components/PageHeader'

/** Cell colors mirror Badge's status tones (Badge.tsx) - up=ok/emerald,
 * down=bad/red, degraded=warn/amber, unknown=neutral - plus two map-only
 * states: a free address (nothing recorded there) and an unmanaged device
 * (auto-populated by discovery but not yet promoted - see
 * docs/decisions.md "Auto-populate discovered devices"). */
const CELL_COLOR: Record<string, string> = {
  free: 'fill-fg-subtle/15',
  unmanaged: 'fill-sky-400/70 dark:fill-sky-500/60',
  up: 'fill-emerald-500',
  down: 'fill-red-500',
  degraded: 'fill-amber-500',
  unknown: 'fill-fg-subtle/40',
}

const CELL_SIZE = 14
const CELL_GAP = 3
const COLUMNS = 32

function cellKey(address: { status: string | null; managed: boolean | null }): string {
  if (address.status === null) return 'free'
  if (address.managed === false) return 'unmanaged'
  return address.status
}

function AddressGrid({ addresses }: { addresses: { ip: string; status: string | null; managed: boolean | null; display_name: string | null }[] }) {
  const rows = Math.ceil(addresses.length / COLUMNS)
  const step = CELL_SIZE + CELL_GAP
  const width = COLUMNS * step
  const height = rows * step

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      width={width}
      height={height}
      className="max-w-full"
      role="img"
      aria-label="Network address map"
    >
      {addresses.map((address, i) => {
        const x = (i % COLUMNS) * step
        const y = Math.floor(i / COLUMNS) * step
        return (
          <rect
            key={address.ip}
            x={x}
            y={y}
            width={CELL_SIZE}
            height={CELL_SIZE}
            rx={2}
            className={CELL_COLOR[cellKey(address)]}
          >
            <title>
              {address.ip}
              {address.display_name ? ` — ${address.display_name}` : ''} ({cellKey(address)})
            </title>
          </rect>
        )
      })}
    </svg>
  )
}

function Legend() {
  const entries: [string, string][] = [
    ['free', 'Free'],
    ['unmanaged', 'Discovered (unmanaged)'],
    ['up', 'Up'],
    ['down', 'Down'],
    ['degraded', 'Degraded'],
    ['unknown', 'Unknown'],
  ]
  return (
    <div className="flex flex-wrap gap-4 text-xs text-fg-muted">
      {entries.map(([key, label]) => (
        <div key={key} className="flex items-center gap-1.5">
          <span className={`inline-block h-3 w-3 rounded-sm ${CELL_COLOR[key]}`} />
          {label}
        </div>
      ))}
    </div>
  )
}

function TopologyView({ networkName, addresses }: { networkName: string; addresses: { ip: string; status: string | null; managed: boolean | null; display_name: string | null }[] }) {
  const devices = addresses.filter((a) => a.display_name !== null)
  return (
    <div className="rounded-control border border-line bg-canvas p-4">
      <div className="text-sm font-medium text-fg">{networkName}</div>
      <div className="mt-3 flex flex-wrap gap-2">
        {devices.length === 0 && <div className="text-xs text-fg-muted">No devices on this network yet.</div>}
        {devices.map((device) => (
          <div
            key={device.ip}
            className="flex flex-col rounded-control border border-line bg-surface px-3 py-2 text-xs"
          >
            <span className="font-medium text-fg">{device.display_name}</span>
            <span className="font-mono text-fg-subtle">{device.ip}</span>
            <span className={`mt-1 inline-block h-1.5 w-full rounded-full ${CELL_COLOR[cellKey(device)]}`} />
          </div>
        ))}
      </div>
    </div>
  )
}

export function NetworkMapPage() {
  const { id } = useParams<{ id: string }>()
  const networkId = id ? Number(id) : null
  const { data: networks } = useNetworks()
  const { data: map, isLoading } = useNetworkMap(networkId)
  const network = networks?.find((n) => n.id === networkId)

  return (
    <div>
      <PageHeader
        title={network ? `${network.name} map` : 'Network map'}
        description={
          <>
            One cell per address in this network's CIDR, colored by status. Above {' '}
            <span className="font-mono">1024</span> addresses this falls back to counts only - see{' '}
            <code className="font-mono">docs/decisions.md</code>.{' '}
            <Link to="/networks" className="text-accent-strong hover:underline">
              Back to Networks
            </Link>
          </>
        }
      />

      <div className="mt-6 flex flex-col gap-6">
        <Card className="p-4">
          {isLoading && <div className="text-sm text-fg-muted">Loading…</div>}
          {map?.truncated && (
            <div className="flex flex-col gap-2">
              <div className="text-sm text-fg-muted">
                {map.total_addresses.toLocaleString()} addresses is too many to render one cell per address -
                showing counts instead.
              </div>
              <div className="flex flex-wrap gap-3 text-sm">
                {map.summary &&
                  Object.entries(map.summary).map(([status, count]) => (
                    <div key={status} className="flex items-center gap-1.5">
                      <span className={`inline-block h-3 w-3 rounded-sm ${CELL_COLOR[status] ?? 'fill-fg-subtle/40'}`} />
                      {status}: {count}
                    </div>
                  ))}
              </div>
            </div>
          )}
          {map && !map.truncated && (
            <div className="flex flex-col gap-3">
              <AddressGrid addresses={map.addresses} />
              <Legend />
            </div>
          )}
        </Card>

        {map && !map.truncated && network && (
          <TopologyView networkName={network.name} addresses={map.addresses} />
        )}
      </div>
    </div>
  )
}
