import { Link, useNavigate, useParams } from 'react-router-dom'
import { useState } from 'react'
import {
  useDeleteService,
  useRescanService,
  useServices,
  useSetServiceManaged,
  useUpdateService,
} from '../api/services'
import type { Service, ServiceFingerprint } from '../api/types'
import { useDeleteDevice, useDevice, useDeviceMetricHistory, useRescanDevice } from '../api/devices'
import { Badge } from '../components/Badge'
import { Card } from '../components/Card'
import { MetricChart } from '../components/MetricChart'
import { StatusBadge } from '../components/StatusBadge'

const METRIC_LABELS: Record<string, { label: string; unit: string }> = {
  load1: { label: 'Load (1m)', unit: '' },
  load5: { label: 'Load (5m)', unit: '' },
  load15: { label: 'Load (15m)', unit: '' },
  mem_used_percent: { label: 'Memory used', unit: '%' },
  disk_used_percent: { label: 'Disk used (/)', unit: '%' },
  latency_ms: { label: 'Latency', unit: 'ms' },
  cpu_percent: { label: 'CPU', unit: '%' },
  uptime_seconds: { label: 'Uptime', unit: 's' },
}

function Fingerprint({ fp }: { fp: ServiceFingerprint | null }) {
  if (!fp) return <>—</>
  const product = [fp.product, fp.version].filter(Boolean).join(' ') || fp.name
  const lines = [product, fp.extrainfo, fp.banner, fp.notes].filter(Boolean)
  if (lines.length === 0) return <>—</>
  return (
    <div className="max-w-md space-y-0.5">
      {lines.map((line) => (
        <div key={line} className="break-words">
          {line}
        </div>
      ))}
    </div>
  )
}

const linkButtonClasses = 'text-xs font-medium text-accent-strong hover:underline disabled:opacity-50'
const ghostButtonClasses =
  'rounded-control border border-line bg-surface px-3 py-1.5 text-sm font-medium text-fg hover:bg-fg-subtle/10 disabled:opacity-50'

function ServiceActions({ service, onEdit }: { service: Service; onEdit: () => void }) {
  const rescan = useRescanService()
  const setManaged = useSetServiceManaged()
  const remove = useDeleteService()
  const [scanNote, setScanNote] = useState<string | null>(null)
  return (
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
      {service.port !== null && (
        <button
          type="button"
          className={linkButtonClasses}
          disabled={rescan.isPending}
          title={scanNote ?? 'Re-fingerprint this service with nmap'}
          onClick={() =>
            rescan.mutate(service.id, {
              onSuccess: (r) => setScanNote(r.updated ? 'Fingerprint updated' : 'No fingerprint returned'),
              onError: (e) => setScanNote(e.message),
            })
          }
        >
          {rescan.isPending ? 'Scanning…' : 'Rescan'}
        </button>
      )}
      <button type="button" className={linkButtonClasses} onClick={onEdit}>
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
  )
}

function ServiceRow({ service }: { service: Service }) {
  const update = useUpdateService()
  const [editing, setEditing] = useState(false)
  const [name, setName] = useState(service.name)
  return (
    <tr className="border-b border-line align-top last:border-b-0">
      <td className="px-4 py-2 font-medium">
        {editing ? (
          <input
            aria-label="Edit name"
            className="rounded-control border border-line bg-surface px-2 py-1 text-sm font-normal text-fg"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        ) : (
          <>
            {service.name}
            {!service.managed && <span className="ml-2 text-xs font-normal text-fg-subtle">discovered</span>}
          </>
        )}
      </td>
      <td className="px-4 py-2 font-mono text-xs text-fg-muted">{service.service_type}</td>
      <td className="px-4 py-2 font-mono tabular-nums text-fg-muted">{service.port ?? '—'}</td>
      <td className="px-4 py-2 text-fg-muted">
        <Fingerprint fp={service.fingerprint} />
      </td>
      <td className="px-4 py-2">
        <StatusBadge status={service.status} />
      </td>
      <td className="px-4 py-2 font-mono tabular-nums text-fg-muted">
        {service.last_latency_ms != null ? `${service.last_latency_ms.toFixed(1)} ms` : '—'}
      </td>
      <td className="whitespace-nowrap px-4 py-2 text-fg-muted">
        {service.last_checked_at ? new Date(service.last_checked_at).toLocaleTimeString() : '—'}
      </td>
      <td className="px-4 py-2 text-fg-muted">{service.source}</td>
      <td className="whitespace-nowrap px-4 py-2 text-right">
        {editing ? (
          <span className="flex justify-end gap-3">
            <button
              type="button"
              className={linkButtonClasses}
              disabled={update.isPending || !name}
              onClick={() => update.mutate({ id: service.id, name }, { onSuccess: () => setEditing(false) })}
            >
              Save
            </button>
            <button type="button" className={linkButtonClasses} onClick={() => setEditing(false)}>
              Cancel
            </button>
          </span>
        ) : (
          <ServiceActions service={service} onEdit={() => setEditing(true)} />
        )}
      </td>
    </tr>
  )
}

export function DeviceDetailPage() {
  const params = useParams<{ id: string }>()
  const deviceId = Number(params.id)
  const navigate = useNavigate()
  const { data: device, isLoading, isError } = useDevice(deviceId)
  const deleteDevice = useDeleteDevice()
  const rescanDevice = useRescanDevice()
  const [scanMessage, setScanMessage] = useState<string | null>(null)
  const { data: allServices } = useServices()
  const services = (allServices ?? []).filter((service) => service.device_id === deviceId)
  const hasLoadMetric = Boolean(device?.metrics && 'load1' in device.metrics)
  const { data: loadHistory } = useDeviceMetricHistory(deviceId, 'load1', hasLoadMetric)

  if (isLoading) return <p className="text-fg-muted">Loading…</p>
  if (isError || !device) return <p className="text-red-600">Device not found.</p>

  function handleDelete() {
    if (!confirm(`Delete ${device!.display_name}?`)) return
    deleteDevice.mutate(device!.id, { onSuccess: () => navigate('/devices') })
  }

  function handleScanAll() {
    setScanMessage('Scanning: every TCP port, then nmap on what is open, then each known service checked again...')
    rescanDevice.mutate(deviceId, {
      onSuccess: (r) => setScanMessage(`Scan finished: ${r.updated} service(s) fingerprinted.`),
      onError: (e) => setScanMessage(e.message),
    })
  }

  return (
    <div>
      <Link to="/devices" className="text-sm text-fg-muted hover:underline">
        ← Devices
      </Link>

      <div className="mt-2 flex items-center justify-between">
        <h1 className="text-2xl font-semibold tracking-tight text-fg">{device.display_name}</h1>
        <button
          type="button"
          onClick={handleDelete}
          className="rounded-control border border-red-300 px-3 py-1.5 text-sm text-red-600 hover:bg-red-50 dark:border-red-800 dark:hover:bg-red-950"
        >
          Delete
        </button>
      </div>

      <dl className="mt-4 grid grid-cols-2 gap-x-6 gap-y-2 text-sm sm:grid-cols-4">
        <div>
          <dt className="text-fg-muted">Type</dt>
          <dd>{device.device_type}</dd>
        </div>
        <div>
          <dt className="text-fg-muted">Status</dt>
          <dd>
            <StatusBadge status={device.status} />
          </dd>
        </div>
        <div>
          <dt className="text-fg-muted">Primary IP</dt>
          <dd className="font-mono">{device.primary_ip ?? '—'}</dd>
        </div>
        <div>
          <dt className="text-fg-muted">Hostname</dt>
          <dd>{device.hostname ?? '—'}</dd>
        </div>
        <div>
          <dt className="text-fg-muted">Activity</dt>
          <dd>
            {device.inactive ? (
              <span title="Down and unseen for several days; AI Mode skips it automatically.">
                <Badge tone="neutral">Inactive</Badge>
              </span>
            ) : (
              '—'
            )}
          </dd>
        </div>
      </dl>

      <section className="mt-8">
        <h2 className="text-lg font-semibold text-fg">Metrics</h2>
        {Object.keys(device.metrics).length === 0 ? (
          <p className="mt-1 text-sm text-fg-muted">No metrics reported yet.</p>
        ) : (
          <>
            <div className="mt-2 flex flex-wrap gap-3">
              {Object.entries(device.metrics).map(([name, value]) => {
                const meta = METRIC_LABELS[name] ?? { label: name, unit: '' }
                return (
                  <Card key={name} className="px-4 py-2">
                    <div className="text-xs text-fg-muted">{meta.label}</div>
                    <div className="font-mono text-lg font-semibold tabular-nums text-fg">
                      {value.toFixed(meta.unit === '' ? 2 : 1)}
                      {meta.unit}
                    </div>
                  </Card>
                )
              })}
            </div>
            {hasLoadMetric && (
              <div className="mt-4">
                <MetricChart points={loadHistory ?? []} />
              </div>
            )}
          </>
        )}
      </section>

      <section className="mt-8">
        <h2 className="text-lg font-semibold text-fg">Addresses</h2>
        {device.addresses.length === 0 ? (
          <p className="mt-1 text-sm text-fg-muted">None recorded.</p>
        ) : (
          <ul className="mt-2 text-sm">
            {device.addresses.map((address) => (
              <li key={address.id} className="font-mono">
                {address.ip_address} {address.mac_address ? `(${address.mac_address})` : ''}
                {address.is_primary ? ' — primary' : ''}
                {address.vendor && <span className="ml-2 font-sans text-fg-muted">— {address.vendor}</span>}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="mt-8">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold text-fg">Services</h2>
          <button
            type="button"
            className={ghostButtonClasses}
            disabled={rescanDevice.isPending}
            onClick={handleScanAll}
          >
            {rescanDevice.isPending ? 'Scanning…' : 'Scan all services'}
          </button>
        </div>
        <p className="mt-1 text-xs text-fg-muted">
          Scans every port on this host with nmap, then re-checks each known service with the tool that matches
          its type: an HTTP request for a web service, a plain TCP connection attempt otherwise, or a DNS/DHCP
          probe for those service types.
        </p>
        {scanMessage && <p className="mt-1 text-sm text-fg-muted">{scanMessage}</p>}
        {services.length === 0 ? (
          <p className="mt-1 text-sm text-fg-muted">No services on this device yet.</p>
        ) : (
          <Card className="mt-2 overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-line text-fg-muted">
                  <th className="px-4 py-2 font-medium">Name</th>
                  <th className="px-4 py-2 font-medium">Type</th>
                  <th className="px-4 py-2 font-medium">Port</th>
                  <th className="px-4 py-2 font-medium">Fingerprint</th>
                  <th className="px-4 py-2 font-medium">Status</th>
                  <th className="px-4 py-2 font-medium">Latency</th>
                  <th className="px-4 py-2 font-medium">Last checked</th>
                  <th className="px-4 py-2 font-medium">Source</th>
                  <th className="px-4 py-2 font-medium" />
                </tr>
              </thead>
              <tbody>
                {services.map((service) => (
                  <ServiceRow key={service.id} service={service} />
                ))}
              </tbody>
            </table>
          </Card>
        )}
      </section>
    </div>
  )
}
