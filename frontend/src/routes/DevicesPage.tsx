import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useCreateDevice, useDeleteDevice, useDevices, useRescanDevice } from '../api/devices'
import { useNetworks } from '../api/networks'
import { DEVICE_TYPES, type DeviceListItem, type DeviceType, type HealthStatus } from '../api/types'
import { Card } from '../components/Card'
import { PageHeader } from '../components/PageHeader'
import { Pagination } from '../components/Pagination'
import { usePaging } from '../lib/usePaging'
import { Segmented } from '../components/Segmented'
import { SummaryTile } from '../components/SummaryTile'
import { DevicesIcon } from '../components/icons'
import { Badge, type BadgeTone } from '../components/Badge'
import { downloadCsv } from '../lib/csv'

const inputClasses =
  'mt-1 rounded-control border border-line bg-surface px-2 py-1 text-sm text-fg focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent'
const primaryButtonClasses =
  'rounded-control bg-accent px-3 py-1.5 text-sm font-medium text-on-accent transition-colors hover:brightness-95 disabled:opacity-50'

const ghostButtonClasses =
  'rounded-control border border-line bg-surface px-3 py-1.5 text-sm font-medium text-fg hover:bg-fg-subtle/10 disabled:opacity-50'

const STATUS_INFO: Record<HealthStatus, { tone: BadgeTone; label: string; help: string }> = {
  up: { tone: 'ok', label: 'up', help: 'Online: answers ping, or its integration poll succeeds.' },
  degraded: {
    tone: 'warn',
    label: 'partial',
    help: 'Partial: does not answer ping, but at least one known service port still accepts connections.',
  },
  down: { tone: 'bad', label: 'down', help: 'Offline: no ping reply and no service port reachable.' },
  unknown: { tone: 'neutral', label: 'unknown', help: 'Not checked yet: the first reachability check runs within a minute of the device appearing.' },
}

type SortKey = 'name' | 'role' | 'ip' | 'network' | 'vendor' | 'services' | 'status' | 'last_seen'

const STATUS_ORDER: Record<HealthStatus, number> = { down: 0, degraded: 1, unknown: 2, up: 3 }

function sortValue(device: DeviceListItem, key: SortKey): string | number {
  switch (key) {
    case 'name':
      return device.display_name.toLowerCase()
    case 'role':
      return (device.role ?? device.device_type).toLowerCase()
    case 'ip':
      return (device.primary_ip ?? '').split('.').map((o) => o.padStart(3, '0')).join('.')
    case 'network':
      return (device.network_name ?? '').toLowerCase()
    case 'vendor':
      return (device.vendor ?? '').toLowerCase()
    case 'services':
      return device.service_count ?? 0
    case 'status':
      return STATUS_ORDER[device.status]
    case 'last_seen':
      return device.last_seen_at ?? ''
  }
}

function SortTh({
  label,
  k,
  sort,
  onSort,
  className = '',
}: {
  label: string
  k: SortKey
  sort: { key: SortKey; desc: boolean }
  onSort: (k: SortKey) => void
  className?: string
}) {
  const active = sort.key === k
  return (
    <th className={`whitespace-nowrap px-4 py-2.5 font-medium ${className}`} aria-sort={active ? (sort.desc ? 'descending' : 'ascending') : 'none'}>
      <button type="button" className="inline-flex items-center gap-1 hover:text-fg" onClick={() => onSort(k)}>
        {label}
        {active && <span aria-hidden>{sort.desc ? '▼' : '▲'}</span>}
      </button>
    </th>
  )
}

export function DevicesPage() {
  const { data: devices, isLoading } = useDevices()
  const { data: networks } = useNetworks()
  const createDevice = useCreateDevice()
  const deleteDevice = useDeleteDevice()
  const rescan = useRescanDevice()
  const [sort, setSort] = useState<{ key: SortKey; desc: boolean }>({ key: 'name', desc: false })
  const [query, setQuery] = useState('')
  const [statusFilter, setStatusFilter] = useState<'all' | HealthStatus>('all')
  const [networkFilter, setNetworkFilter] = useState<'all' | 'unassigned' | string>('all')
  const [showForm, setShowForm] = useState(false)
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [message, setMessage] = useState<string | null>(null)

  const rows = useMemo(() => {
    const needle = query.trim().toLowerCase()
    const filtered = (devices ?? []).filter(
      (d) =>
        (statusFilter === 'all' || d.status === statusFilter) &&
        (networkFilter === 'all' ||
          (networkFilter === 'unassigned' ? d.network_id === null : d.network_id === Number(networkFilter))) &&
        (!needle ||
        [d.display_name, d.primary_ip, d.role, d.vendor, d.network_name, d.hostname]
          .filter(Boolean)
          .some((v) => String(v).toLowerCase().includes(needle))),
    )
    const dir = sort.desc ? -1 : 1
    return [...filtered].sort((a, b) => {
      const va = sortValue(a, sort.key)
      const vb = sortValue(b, sort.key)
      return va < vb ? -dir : va > vb ? dir : 0
    })
  }, [devices, query, sort, statusFilter, networkFilter])
  const paging = usePaging(rows)
  const counts = { all: devices?.length ?? 0, up: 0, degraded: 0, down: 0, unknown: 0 }
  for (const d of devices ?? []) counts[d.status] += 1
  const networkCounts = useMemo(() => {
    const byId = new Map<number, number>()
    let unassigned = 0
    for (const d of devices ?? []) {
      if (d.network_id === null) unassigned += 1
      else byId.set(d.network_id, (byId.get(d.network_id) ?? 0) + 1)
    }
    return { byId, unassigned }
  }, [devices])

  function onSort(key: SortKey) {
    setSort((cur) => (cur.key === key ? { key, desc: !cur.desc } : { key, desc: false }))
  }

  function toggle(id: number) {
    setSelected((cur) => {
      const next = new Set(cur)
      if (!next.delete(id)) next.add(id)
      return next
    })
  }

  const allSelected = rows.length > 0 && rows.every((d) => selected.has(d.id))

  async function removeSelected() {
    if (!confirm(`Remove ${selected.size} device(s)? Their services stay but become unassigned.`)) return
    await Promise.all([...selected].map((id) => deleteDevice.mutateAsync(id)))
    setSelected(new Set())
  }

  async function scanSelected() {
    setMessage(`Scanning ${selected.size} device(s): every TCP port, then nmap on what is open. This can take a few minutes...`)
    const results = await Promise.allSettled([...selected].map((id) => rescan.mutateAsync(id)))
    const failed = results.filter((r) => r.status === 'rejected').length
    const updated = results.reduce((n, r) => n + (r.status === 'fulfilled' ? r.value.updated : 0), 0)
    setMessage(`Scan finished: ${updated} service(s) fingerprinted${failed ? `, ${failed} device(s) could not be scanned` : ''}.`)
  }

  function exportCsv() {
    downloadCsv(
      'devices.csv',
      ['name', 'role', 'type', 'ip', 'network', 'vendor', 'status', 'services', 'services_up', 'last_seen'],
      rows.map((d) => [
        d.display_name, d.role, d.device_type, d.primary_ip, d.network_name, d.vendor,
        d.status, d.service_count, d.services_up, d.last_seen_at,
      ]),
    )
  }

  const [displayName, setDisplayName] = useState('')
  const [deviceType, setDeviceType] = useState<DeviceType>('linux')
  const [primaryIp, setPrimaryIp] = useState('')
  const [networkId, setNetworkId] = useState<string>('')

  function handleSubmit(event: React.FormEvent) {
    event.preventDefault()
    if (!displayName) return
    createDevice.mutate(
      {
        display_name: displayName,
        device_type: deviceType,
        primary_ip: primaryIp || null,
        network_id: networkId ? Number(networkId) : null,
      },
      {
        onSuccess: () => {
          setDisplayName('')
          setPrimaryIp('')
        },
      },
    )
  }

  return (
    <div>
      <PageHeader
        title="Devices"
        description="Hosts, hypervisors, VMs/LXCs, and network equipment being monitored."
      />

      <div className="mt-5 grid grid-cols-2 gap-4 md:grid-cols-4">
        <SummaryTile icon={<DevicesIcon className="h-5 w-5" />} label="Devices" value={counts.all} />
        <SummaryTile icon={<DevicesIcon className="h-5 w-5" />} label="Up" value={counts.up} tone="ok" />
        <SummaryTile icon={<DevicesIcon className="h-5 w-5" />} label="Partial" value={counts.degraded} tone={counts.degraded > 0 ? 'warn' : 'neutral'} />
        <SummaryTile icon={<DevicesIcon className="h-5 w-5" />} label="Down" value={counts.down} tone={counts.down > 0 ? 'bad' : 'neutral'} />
      </div>

      {showForm && (
      <form onSubmit={handleSubmit} className="mt-6 flex flex-wrap items-end gap-3 rounded-card border border-line bg-surface p-4">
        <label className="flex flex-col text-sm">
          Name
          <input
            className={inputClasses}
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
            placeholder="pve1"
          />
        </label>
        <label className="flex flex-col text-sm">
          Type
          <select
            className={inputClasses}
            value={deviceType}
            onChange={(e) => setDeviceType(e.target.value as DeviceType)}
          >
            {DEVICE_TYPES.map((type) => (
              <option key={type} value={type}>
                {type}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col text-sm">
          Primary IP
          <input
            className={inputClasses}
            value={primaryIp}
            onChange={(e) => setPrimaryIp(e.target.value)}
            placeholder="192.168.1.10"
          />
        </label>
        <label className="flex flex-col text-sm">
          Network
          <select
            className={inputClasses}
            value={networkId}
            onChange={(e) => setNetworkId(e.target.value)}
          >
            <option value="">None</option>
            {networks?.map((network) => (
              <option key={network.id} value={network.id}>
                {network.name}
              </option>
            ))}
          </select>
        </label>
        <button type="submit" disabled={createDevice.isPending || !displayName.trim()} className={primaryButtonClasses}>
          Add device
        </button>
        {createDevice.error && <p className="w-full text-sm text-red-600">{createDevice.error.message}</p>}
      </form>
      )}

      <div className="mt-6 flex flex-wrap items-center gap-3">
        <input
          className={`${inputClasses} mt-0 w-64 max-w-full`}
          placeholder="Search name, IP, role, vendor"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <Segmented
          label="Filter by status"
          value={statusFilter}
          onChange={setStatusFilter}
          options={[
            { value: 'all', label: `All (${counts.all})` },
            { value: 'up', label: `Up (${counts.up})` },
            { value: 'degraded', label: `Partial (${counts.degraded})` },
            { value: 'down', label: `Down (${counts.down})` },
            { value: 'unknown', label: `Unknown (${counts.unknown})` },
          ]}
        />
        <select
          aria-label="Filter by network"
          className={`${inputClasses} mt-0`}
          value={networkFilter}
          onChange={(e) => setNetworkFilter(e.target.value)}
        >
          <option value="all">All networks ({counts.all})</option>
          {networks?.map((network) => (
            <option key={network.id} value={network.id}>
              {network.name} ({networkCounts.byId.get(network.id) ?? 0})
            </option>
          ))}
          <option value="unassigned">Unassigned ({networkCounts.unassigned})</option>
        </select>
        <button type="button" className={ghostButtonClasses} onClick={() => setShowForm((v) => !v)} aria-expanded={showForm}>
          {showForm ? 'Close' : 'New device'}
        </button>
        <button type="button" className={ghostButtonClasses} onClick={exportCsv} disabled={rows.length === 0}>
          Export CSV
        </button>
        {selected.size > 0 && (
          <>
            <span className="text-sm text-fg-muted">{selected.size} selected</span>
            <button type="button" className={ghostButtonClasses} onClick={scanSelected} disabled={rescan.isPending}>
              Scan host (all ports)
            </button>
            <button type="button" className={ghostButtonClasses} onClick={removeSelected}>
              Remove
            </button>
          </>
        )}
      </div>
      {message && <p className="mt-2 text-sm text-fg-muted">{message}</p>}

      <div className="mt-3">
        <Card className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-line text-fg-muted">
                <th className="w-8 px-3 py-2.5">
                  <input
                    type="checkbox"
                    aria-label="Select all devices"
                    checked={allSelected}
                    onChange={() => setSelected(allSelected ? new Set() : new Set(rows.map((d) => d.id)))}
                  />
                </th>
                <SortTh label="Name" k="name" sort={sort} onSort={onSort} />
                <SortTh label="Role" k="role" sort={sort} onSort={onSort} />
                <SortTh label="IP" k="ip" sort={sort} onSort={onSort} />
                <SortTh label="Network" k="network" sort={sort} onSort={onSort} className="hidden 2xl:table-cell" />
                <SortTh label="Vendor" k="vendor" sort={sort} onSort={onSort} />
                <SortTh label="Services" k="services" sort={sort} onSort={onSort} />
                <SortTh label="Status" k="status" sort={sort} onSort={onSort} />
                <th className="whitespace-nowrap px-4 py-2.5 font-medium">Activity</th>
                <SortTh label="Last seen" k="last_seen" sort={sort} onSort={onSort} className="hidden 2xl:table-cell" />
              </tr>
            </thead>
            <tbody>
              {isLoading && (
                <tr>
                  <td className="px-4 py-3 text-fg-muted" colSpan={10}>
                    Loading…
                  </td>
                </tr>
              )}
              {devices?.length === 0 && (
                <tr>
                  <td className="px-4 py-3 text-fg-muted" colSpan={10}>
                    No devices yet.
                  </td>
                </tr>
              )}
              {paging.rows.map((device) => (
                <tr key={device.id} className="border-b border-line last:border-b-0">
                  <td className="px-3 py-2.5">
                    <input
                      type="checkbox"
                      aria-label={`Select ${device.display_name}`}
                      checked={selected.has(device.id)}
                      onChange={() => toggle(device.id)}
                    />
                  </td>
                  <td className="whitespace-nowrap px-3 py-2.5 font-medium">
                    <Link to={`/devices/${device.id}`} className="hover:underline">
                      {device.display_name}
                    </Link>
                    {!device.managed && <span className="ml-2 text-xs text-fg-subtle">discovered</span>}
                  </td>
                  <td className="whitespace-nowrap px-3 py-2.5 text-fg-muted">{device.role ?? device.device_type}</td>
                  <td className="whitespace-nowrap px-3 py-2.5 font-mono text-fg-muted">{device.primary_ip ?? '—'}</td>
                  <td className="hidden whitespace-nowrap px-3 py-2.5 text-fg-muted 2xl:table-cell">{device.network_name ?? '—'}</td>
                  <td className="max-w-32 truncate px-3 py-2.5 text-fg-muted" title={device.vendor ?? undefined}>
                    {device.vendor ?? '—'}
                  </td>
                  <td className="whitespace-nowrap px-3 py-2.5 text-fg-muted">
                    {device.service_count ? `${device.services_up}/${device.service_count} up` : '—'}
                  </td>
                  <td className="px-3 py-2.5" title={STATUS_INFO[device.status].help}>
                    <Badge tone={STATUS_INFO[device.status].tone}>{STATUS_INFO[device.status].label}</Badge>
                  </td>
                  <td className="px-3 py-2.5">
                    {device.inactive && (
                      <span title="Down and unseen for several days; AI Mode skips it automatically.">
                        <Badge tone="neutral">Inactive</Badge>
                      </span>
                    )}
                  </td>
                  <td className="hidden whitespace-nowrap px-3 py-2.5 text-fg-muted 2xl:table-cell">
                    {device.last_seen_at ? new Date(device.last_seen_at).toLocaleString() : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <Pagination {...paging.footer} />
        </Card>
      </div>

      <dl className="mt-4 grid gap-2 text-xs text-fg-muted sm:grid-cols-2">
        {(Object.keys(STATUS_INFO) as HealthStatus[]).map((status) => (
          <div key={status} className="flex items-start gap-2">
            <dt>
              <Badge tone={STATUS_INFO[status].tone}>{STATUS_INFO[status].label}</Badge>
            </dt>
            <dd>{STATUS_INFO[status].help}</dd>
          </div>
        ))}
      </dl>
    </div>
  )
}
