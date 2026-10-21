import { useState } from 'react'
import { useDevices } from '../api/devices'
import {
  type ServiceFilters,
  type ServiceSortKey,
  useBulkServices,
  useCreateService,
  useDeleteService,
  useRescanService,
  useServices,
  useSetServiceManaged,
  useUpdateService,
} from '../api/services'
import { type Device, type HealthStatus, SERVICE_TYPES, type Service, type ServiceType } from '../api/types'
import { Card } from '../components/Card'
import { PageHeader } from '../components/PageHeader'
import { StatusBadge } from '../components/StatusBadge'

const CHECKABLE_TYPES: ServiceType[] = ['http', 'https', 'tcp']

const inputClasses =
  'mt-1 rounded-control border border-line bg-surface px-2 py-1 text-sm text-fg focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent'
const primaryButtonClasses =
  'rounded-control bg-accent px-3 py-1.5 text-sm font-medium text-on-accent transition-colors hover:brightness-95 disabled:opacity-50'

const STATUSES: HealthStatus[] = ['up', 'down', 'degraded', 'unknown']

function fingerprintText(service: Service): string {
  const fp = service.fingerprint
  if (!fp) return '—'
  const product = [fp.product, fp.version].filter(Boolean).join(' ')
  return product || fp.name || fp.banner || '—'
}

function SortHeader({
  label,
  sortKey,
  filters,
  onSort,
}: {
  label: string
  sortKey: ServiceSortKey
  filters: ServiceFilters
  onSort: (key: ServiceSortKey) => void
}) {
  const active = filters.sort === sortKey
  return (
    <th className="px-4 py-2.5 font-medium" aria-sort={active ? (filters.order === 'desc' ? 'descending' : 'ascending') : 'none'}>
      <button type="button" className="font-medium hover:text-fg" onClick={() => onSort(sortKey)}>
        {label}
        {active ? (filters.order === 'desc' ? ' \u25BC' : ' \u25B2') : ''}
      </button>
    </th>
  )
}

const linkButtonClasses = 'text-xs font-medium text-accent-strong hover:underline disabled:opacity-50'
const COLUMN_COUNT = 11

function ServiceRow({
  service,
  devices,
  selected,
  onToggle,
  showDevice,
}: {
  service: Service
  devices: Device[] | undefined
  selected: boolean
  onToggle: () => void
  showDevice: boolean
}) {
  const rescan = useRescanService()
  const [scanNote, setScanNote] = useState<string | null>(null)
  const setManaged = useSetServiceManaged()
  const update = useUpdateService()
  const remove = useDeleteService()
  const [editing, setEditing] = useState(false)
  const [name, setName] = useState(service.name)
  const [deviceId, setDeviceId] = useState(service.device_id?.toString() ?? '')

  function save() {
    update.mutate(
      { id: service.id, name, device_id: deviceId ? Number(deviceId) : null },
      { onSuccess: () => setEditing(false) },
    )
  }

  return (
    <tr className="border-b border-line last:border-b-0">
      <td className="px-4 py-2.5">
        <input type="checkbox" aria-label={`Select ${service.name}`} checked={selected} onChange={onToggle} />
      </td>
      <td className="px-4 py-2.5 font-medium">
        {editing ? (
          <input
            aria-label="Edit name"
            className={inputClasses}
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        ) : (
          <>
            {service.name}
            {!service.managed && (
              <span className="ml-2 rounded-control border border-line px-1.5 py-0.5 text-xs font-normal text-fg-muted">
                discovered
              </span>
            )}
          </>
        )}
      </td>
      <td className="px-4 py-2.5 font-mono text-xs text-fg-muted">{service.service_type}</td>
      <td className="px-4 py-2.5 font-mono tabular-nums text-fg-muted">{service.port ?? '—'}</td>
      <td className="max-w-64 truncate px-4 py-2.5 text-fg-muted" title={fingerprintText(service)}>
        {fingerprintText(service)}
      </td>
      <td className="px-4 py-2.5">
        {editing ? (
          <select
            aria-label="Edit device"
            className={inputClasses}
            value={deviceId}
            onChange={(e) => setDeviceId(e.target.value)}
          >
            <option value="">None</option>
            {devices?.map((d) => (
              <option key={d.id} value={d.id}>
                {d.display_name}
              </option>
            ))}
          </select>
        ) : showDevice ? (
          (devices?.find((d) => d.id === service.device_id)?.display_name ?? '—')
        ) : (
          ''
        )}
      </td>
      <td className="px-4 py-2.5 text-fg-muted">{service.device_vendor ?? '—'}</td>
      <td className="px-4 py-2.5">
        <StatusBadge status={service.status} />
      </td>
      <td className="px-4 py-2.5 font-mono tabular-nums text-fg-muted">
        {service.last_latency_ms != null ? `${service.last_latency_ms.toFixed(1)} ms` : '—'}
      </td>
      <td className="px-4 py-2.5 text-fg-muted">
        {service.last_checked_at ? new Date(service.last_checked_at).toLocaleTimeString() : '—'}
      </td>
      <td className="whitespace-nowrap px-4 py-2.5 text-right">
        {editing ? (
          <span className="flex justify-end gap-3">
            <button type="button" className={linkButtonClasses} onClick={save} disabled={update.isPending || !name}>
              Save
            </button>
            <button type="button" className={linkButtonClasses} onClick={() => setEditing(false)}>
              Cancel
            </button>
          </span>
        ) : (
          <span className="flex justify-end gap-3">
            {!service.managed && (
              <button
                type="button"
                className={linkButtonClasses}
                disabled={setManaged.isPending}
                onClick={() => setManaged.mutate({ id: service.id, managed: true })}
              >
                Monitor
              </button>
            )}
            {service.device_id !== null && service.port !== null && (
              <button
                type="button"
                className={linkButtonClasses}
                disabled={rescan.isPending}
                title={scanNote ?? 'Re-fingerprint this service with nmap'}
                onClick={() =>
                  rescan.mutate(service.id, {
                    onSuccess: (r) =>
                      setScanNote(
                        `${r.updated ? 'Fingerprint updated' : 'No fingerprint returned'}${r.status ? `; now ${r.status}` : ''}`,
                      ),
                    onError: (e) => setScanNote(e.message),
                  })
                }
              >
                {rescan.isPending ? 'Scanning…' : 'Rescan'}
              </button>
            )}
            <button type="button" className={linkButtonClasses} onClick={() => setEditing(true)}>
              Edit
            </button>
            <button
              type="button"
              className="text-xs font-medium text-red-600 hover:underline disabled:opacity-50"
              disabled={remove.isPending}
              onClick={() => {
                if (window.confirm(`Delete ${service.name}?`)) remove.mutate(service.id)
              }}
            >
              Delete
            </button>
          </span>
        )}
      </td>
    </tr>
  )
}

function GroupRows({
  group,
  devices,
  selected,
  onToggle,
  showDevice,
}: {
  showDevice: boolean
  group: { key: string; label: string; items: Service[] }
  devices: Device[] | undefined
  selected: Set<number>
  onToggle: (ids: number[], on: boolean) => void
}) {
  const ids = group.items.map((svc) => svc.id)
  const allOn = ids.every((id) => selected.has(id))
  return (
    <>
      <tr className="border-b border-line bg-fg-subtle/10">
        <td className="px-4 py-2">
          <input
            type="checkbox"
            aria-label={`Select group ${group.label}`}
            checked={allOn}
            onChange={(e) => onToggle(ids, e.target.checked)}
          />
        </td>
        <td className="px-4 py-2 font-medium" colSpan={COLUMN_COUNT - 1}>
          {group.label} <span className="font-normal text-fg-muted">({group.items.length})</span>
        </td>
      </tr>
      {group.items.map((service) => (
        <ServiceRow
          key={service.id}
          service={service}
          devices={devices}
          selected={selected.has(service.id)}
          onToggle={() => onToggle([service.id], !selected.has(service.id))}
          showDevice={showDevice}
        />
      ))}
    </>
  )
}

export function ServicesPage() {
  const [filters, setFilters] = useState<ServiceFilters>({ sort: 'name', order: 'asc' })
  const { data: services, isLoading } = useServices(filters)
  const { data: devices } = useDevices()
  const bulk = useBulkServices()
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [groupBy, setGroupBy] = useState<'host' | 'network' | null>(null)
  const grouped = groupBy !== null

  const allIds = services?.map((svc) => svc.id) ?? []
  const allSelected = allIds.length > 0 && allIds.every((id) => selected.has(id))

  function toggle(ids: number[], on: boolean) {
    setSelected((prev) => {
      const next = new Set(prev)
      for (const id of ids) {
        if (on) next.add(id)
        else next.delete(id)
      }
      return next
    })
  }

  function runBulk(action: 'delete' | 'monitor' | 'unmonitor') {
    const ids = [...selected]
    if (action === 'delete' && !window.confirm(`Delete ${ids.length} service(s)?`)) return
    bulk.mutate({ ids, action }, { onSuccess: () => setSelected(new Set()) })
  }

  const groups: { key: string; label: string; items: Service[] }[] = []
  if (groupBy && services) {
    const keyOf = (svc: Service): string => {
      if (groupBy === 'host') return svc.device_id === null ? '' : String(svc.device_id)
      return devices?.find((d) => d.id === svc.device_id)?.network_name ?? ''
    }
    const labelOf = (key: string): string => {
      if (groupBy === 'network') return key || 'No network'
      if (!key) return 'No device'
      return devices?.find((d) => d.id === Number(key))?.display_name ?? `Device ${key}`
    }
    const byKey = new Map<string, Service[]>()
    for (const svc of services) byKey.set(keyOf(svc), [...(byKey.get(keyOf(svc)) ?? []), svc])
    for (const [key, items] of byKey) groups.push({ key, label: labelOf(key), items })
    groups.sort((a, b) => (a.key === '' ? 1 : b.key === '' ? -1 : a.label.localeCompare(b.label)))
  }

  function handleSort(key: ServiceSortKey) {
    setFilters((f) => ({ ...f, sort: key, order: f.sort === key && f.order === 'asc' ? 'desc' : 'asc' }))
  }
  const createService = useCreateService()

  const [name, setName] = useState('')
  const [serviceType, setServiceType] = useState<ServiceType>('http')
  const [deviceId, setDeviceId] = useState<string>('')
  const [url, setUrl] = useState('')
  const [host, setHost] = useState('')
  const [port, setPort] = useState('')
  const [queryName, setQueryName] = useState('')
  const [recordType, setRecordType] = useState('')
  const [timeoutSeconds, setTimeoutSeconds] = useState('')
  const [error, setError] = useState<string | null>(null)

  const isTcp = serviceType === 'tcp'
  const isDns = serviceType === 'dns'
  const isDhcp = serviceType === 'dhcp'
  const isCheckable = CHECKABLE_TYPES.includes(serviceType)

  function resetFormFields() {
    setName('')
    setUrl('')
    setHost('')
    setPort('')
    setQueryName('')
    setRecordType('')
    setTimeoutSeconds('')
  }

  function handleSubmit(event: React.FormEvent) {
    event.preventDefault()
    setError(null)
    if (!name) return

    let config: Record<string, unknown> = {}
    if (isTcp) {
      if (!host || !port) {
        setError('Host and port are required for a TCP check.')
        return
      }
      config = { host, port: Number(port) }
    } else if (isDns) {
      if (!host) {
        setError('Host (the resolver to query) is required for a DNS check.')
        return
      }
      config = { host }
      if (port) config.port = Number(port)
      if (queryName) config.query_name = queryName
      if (recordType) config.record_type = recordType
    } else if (isDhcp) {
      if (!host) {
        setError('Host (the DHCP server to probe) is required for a DHCP check.')
        return
      }
      config = { host }
      if (timeoutSeconds) config.timeout_seconds = Number(timeoutSeconds)
    } else if (isCheckable) {
      if (!url) {
        setError('URL is required for an HTTP/HTTPS check.')
        return
      }
      config = { url }
    }

    createService.mutate(
      { name, service_type: serviceType, device_id: deviceId ? Number(deviceId) : null, config },
      {
        onSuccess: resetFormFields,
        onError: (err) => setError(err.message || 'Failed to create service.'),
      },
    )
  }

  return (
    <div>
      <PageHeader
        title="Services"
        description="HTTP/HTTPS/TCP/DNS/DHCP checks and provider-native services (e.g. Proxmox VMs) attached to devices."
      />

      <form onSubmit={handleSubmit} className="mt-6 flex flex-wrap items-end gap-3 rounded-card border border-line bg-surface p-4">
        <label className="flex flex-col text-sm">
          Name
          <input
            className={inputClasses}
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="pve-web"
          />
        </label>
        <label className="flex flex-col text-sm">
          Type
          <select
            className={inputClasses}
            value={serviceType}
            onChange={(e) => setServiceType(e.target.value as ServiceType)}
          >
            {SERVICE_TYPES.map((type) => (
              <option key={type} value={type}>
                {type}
              </option>
            ))}
          </select>
        </label>

        {isTcp && (
          <>
            <label className="flex flex-col text-sm">
              Host
              <input
                className={inputClasses}
                value={host}
                onChange={(e) => setHost(e.target.value)}
                placeholder="192.168.1.10"
              />
            </label>
            <label className="flex flex-col text-sm">
              Port
              <input
                className={`${inputClasses} w-20`}
                value={port}
                onChange={(e) => setPort(e.target.value)}
                placeholder="22"
              />
            </label>
          </>
        )}
        {isDns && (
          <>
            <label className="flex flex-col text-sm">
              Host
              <input
                className={inputClasses}
                value={host}
                onChange={(e) => setHost(e.target.value)}
                placeholder="192.168.1.1"
              />
            </label>
            <label className="flex flex-col text-sm">
              Port
              <input
                className={`${inputClasses} w-20`}
                value={port}
                onChange={(e) => setPort(e.target.value)}
                placeholder="53"
              />
            </label>
            <label className="flex flex-col text-sm">
              Query name
              <input
                className={inputClasses}
                value={queryName}
                onChange={(e) => setQueryName(e.target.value)}
                placeholder="example.com"
              />
            </label>
            <label className="flex flex-col text-sm">
              Record type
              <input
                className={`${inputClasses} w-20`}
                value={recordType}
                onChange={(e) => setRecordType(e.target.value)}
                placeholder="A"
              />
            </label>
          </>
        )}
        {isDhcp && (
          <>
            <label className="flex flex-col text-sm">
              Host
              <input
                className={inputClasses}
                value={host}
                onChange={(e) => setHost(e.target.value)}
                placeholder="192.168.1.1"
              />
            </label>
            <label className="flex flex-col text-sm">
              Timeout (seconds)
              <input
                className={`${inputClasses} w-24`}
                value={timeoutSeconds}
                onChange={(e) => setTimeoutSeconds(e.target.value)}
                placeholder="2"
              />
            </label>
          </>
        )}
        {isCheckable && !isTcp && (
          <label className="flex flex-1 flex-col text-sm">
            URL
            <input
              className={inputClasses}
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="https://192.168.1.10:8006"
            />
          </label>
        )}

        <label className="flex flex-col text-sm">
          Device
          <select
            className={inputClasses}
            value={deviceId}
            onChange={(e) => setDeviceId(e.target.value)}
          >
            <option value="">None</option>
            {devices?.map((device) => (
              <option key={device.id} value={device.id}>
                {device.display_name}
              </option>
            ))}
          </select>
        </label>
        <button type="submit" disabled={createService.isPending || !name.trim()} className={primaryButtonClasses}>
          Add service
        </button>
      </form>

      {error && <p className="mt-2 text-sm text-red-600">{error}</p>}

      <div className="mt-6 flex flex-wrap items-end gap-3">
        <label className="flex flex-col text-sm">
          Search
          <input
            className={inputClasses}
            value={filters.q ?? ''}
            onChange={(e) => setFilters((f) => ({ ...f, q: e.target.value }))}
            placeholder="name, product, device"
          />
        </label>
        <label className="flex flex-col text-sm">
          Status
          <select
            className={inputClasses}
            aria-label="Filter status"
            value={filters.status ?? ''}
            onChange={(e) => setFilters((f) => ({ ...f, status: e.target.value as HealthStatus | '' }))}
          >
            <option value="">All</option>
            {STATUSES.map((st) => (
              <option key={st} value={st}>
                {st}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col text-sm">
          Kind
          <select
            className={inputClasses}
            aria-label="Filter type"
            value={filters.service_type ?? ''}
            onChange={(e) => setFilters((f) => ({ ...f, service_type: e.target.value as ServiceType | '' }))}
          >
            <option value="">All</option>
            {SERVICE_TYPES.map((type) => (
              <option key={type} value={type}>
                {type}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col text-sm">
          Monitoring
          <select
            className={inputClasses}
            aria-label="Filter monitoring"
            value={filters.managed ?? ''}
            onChange={(e) => setFilters((f) => ({ ...f, managed: e.target.value as 'true' | 'false' | '' }))}
          >
            <option value="">All</option>
            <option value="true">Monitored</option>
            <option value="false">Discovered only</option>
          </select>
        </label>
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-3 text-sm">
        <label className="flex items-center gap-2">
          <input
            type="checkbox"
            checked={groupBy === 'host'}
            onChange={(e) => setGroupBy(e.target.checked ? 'host' : null)}
          />
          Group by host
        </label>
        <label className="flex items-center gap-2">
          <input
            type="checkbox"
            checked={groupBy === 'network'}
            onChange={(e) => setGroupBy(e.target.checked ? 'network' : null)}
          />
          Group by network
        </label>
        {selected.size > 0 && (
          <>
            <span className="text-fg-muted">{selected.size} selected</span>
            <button type="button" className={linkButtonClasses} disabled={bulk.isPending} onClick={() => runBulk('monitor')}>
              Monitor
            </button>
            <button type="button" className={linkButtonClasses} disabled={bulk.isPending} onClick={() => runBulk('unmonitor')}>
              Stop monitoring
            </button>
            <button
              type="button"
              className="text-xs font-medium text-red-600 hover:underline disabled:opacity-50"
              disabled={bulk.isPending}
              onClick={() => runBulk('delete')}
            >
              Delete selected
            </button>
            <button type="button" className={linkButtonClasses} onClick={() => setSelected(new Set())}>
              Clear
            </button>
          </>
        )}
      </div>

      <div className="mt-2 overflow-x-auto">
        <Card className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="whitespace-nowrap border-b border-line text-fg-muted">
                <th className="px-4 py-2.5">
                  <input
                    type="checkbox"
                    aria-label="Select all"
                    checked={allSelected}
                    onChange={(e) => toggle(allIds, e.target.checked)}
                  />
                </th>
                <SortHeader label="Name" sortKey="name" filters={filters} onSort={handleSort} />
                <SortHeader label="Type" sortKey="type" filters={filters} onSort={handleSort} />
                <SortHeader label="Port" sortKey="port" filters={filters} onSort={handleSort} />
                <th className="px-4 py-2.5 font-medium">Fingerprint</th>
                <SortHeader label="Device" sortKey="device" filters={filters} onSort={handleSort} />
                <SortHeader label="Vendor" sortKey="vendor" filters={filters} onSort={handleSort} />
                <SortHeader label="Status" sortKey="status" filters={filters} onSort={handleSort} />
                <SortHeader label="Latency" sortKey="latency" filters={filters} onSort={handleSort} />
                <SortHeader label="Last checked" sortKey="last_checked" filters={filters} onSort={handleSort} />
                <th className="px-4 py-2.5 font-medium" />
              </tr>
            </thead>
            <tbody>
              {isLoading && (
                <tr>
                  <td className="px-4 py-3 text-fg-muted" colSpan={COLUMN_COUNT}>
                    Loading…
                  </td>
                </tr>
              )}
              {services?.length === 0 && (
                <tr>
                  <td className="px-4 py-3 text-fg-muted" colSpan={COLUMN_COUNT}>
                    No services yet.
                  </td>
                </tr>
              )}
              {grouped
                ? groups.map((group) => (
                    <GroupRows
                      key={group.key}
                      group={group}
                      devices={devices}
                      selected={selected}
                      onToggle={toggle}
                      showDevice={groupBy === 'network'}
                    />
                  ))
                : services?.map((service) => (
                    <ServiceRow
                      key={service.id}
                      service={service}
                      devices={devices}
                      selected={selected.has(service.id)}
                      onToggle={() => toggle([service.id], !selected.has(service.id))}
                      showDevice
                    />
                  ))}
            </tbody>
          </table>
        </Card>
      </div>
    </div>
  )
}
