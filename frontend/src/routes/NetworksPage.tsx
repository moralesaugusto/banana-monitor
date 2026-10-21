import { Fragment, useState } from 'react'
import { Link } from 'react-router-dom'
import { useCredentials } from '../api/credentials'
import {
  useAddNetworkCredential,
  useCreateNetwork,
  useDeleteNetwork,
  useNetworkCredentials,
  useNetworks,
  useRemoveNetworkCredential,
  useScanNetwork,
  useScanStatus,
} from '../api/networks'
import { Card } from '../components/Card'
import { PageHeader } from '../components/PageHeader'

/** The scan trigger plus a live "Scanning... N/M hosts" indicator, backed by
 * the in-memory GET /networks/{id}/scan-status endpoint - the trigger itself
 * just returns 202 immediately (it's a detached background task), so status
 * polling is the only way to see whether a scan is actually still running or
 * how far along it is. One instance per network row, not shared state, so
 * each row's hook order stays stable regardless of list length. */
function NetworkScanControl({ networkId }: { networkId: number }) {
  const { data: scanStatus } = useScanStatus(networkId)
  const scanNetwork = useScanNetwork()
  const scanning = scanStatus?.status === 'scanning'

  return (
    <div className="flex items-center gap-3">
      {scanning && (
        <div className="flex items-center gap-2">
          <span className="text-xs font-medium text-accent">
            Scanning… {scanStatus.scanned_hosts}/{scanStatus.total_hosts}
          </span>
          <div className="h-1.5 w-20 overflow-hidden rounded-full bg-accent-soft">
            <div
              className="h-full rounded-full bg-accent-strong transition-[width]"
              style={{
                width: `${scanStatus.total_hosts > 0 ? Math.round((scanStatus.scanned_hosts / scanStatus.total_hosts) * 100) : 0}%`,
              }}
            />
          </div>
        </div>
      )}
      {!scanning && scanStatus?.finished_at && (
        <span className="text-xs text-fg-subtle">
          Last scan {new Date(scanStatus.finished_at).toLocaleTimeString()}
        </span>
      )}
      {!scanning && scanStatus?.error && (
        <span className="text-xs text-red-600 dark:text-red-400" title={scanStatus.error}>
          Scan failed
        </span>
      )}
      {!scanning && !scanStatus?.error && (scanStatus?.failed_hosts ?? 0) > 0 && (
        <span className="text-xs text-amber-600" title="These hosts raised an error and were skipped; see the log.">
          {scanStatus?.failed_hosts} host(s) skipped
        </span>
      )}
      <button
        type="button"
        onClick={() => scanNetwork.mutate(networkId)}
        disabled={scanning || scanNetwork.isPending}
        className="text-xs font-medium text-accent-strong hover:underline disabled:opacity-50"
      >
        {scanning ? 'Scanning…' : 'Scan now'}
      </button>
    </div>
  )
}

const inputClasses =
  'mt-1 rounded-control border border-line bg-surface px-2 py-1 text-sm text-fg focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent'
const primaryButtonClasses =
  'rounded-control bg-accent px-3 py-1.5 text-sm font-medium text-on-accent transition-colors hover:brightness-95 disabled:opacity-50'

/** Ordered auto-login credentials for one network - tried in priority order
 * against any host its scan finds with SSH open. See docs/decisions.md
 * "Auto-login on discovery" for why this tries every bound credential
 * rather than scoping one to a specific host. */
function NetworkCredentialsPanel({ networkId }: { networkId: number }) {
  const { data: bindings, isLoading } = useNetworkCredentials(networkId)
  const { data: credentials } = useCredentials()
  const addCredential = useAddNetworkCredential(networkId)
  const removeCredential = useRemoveNetworkCredential(networkId)
  const [credentialId, setCredentialId] = useState('')

  const boundIds = new Set(bindings?.map((b) => b.credential_id))
  const available = credentials?.filter((c) => !boundIds.has(c.id))

  function handleAdd() {
    if (!credentialId) return
    addCredential.mutate(
      { credential_id: Number(credentialId), priority: bindings?.length ?? 0 },
      { onSuccess: () => setCredentialId('') },
    )
  }

  return (
    <div className="flex flex-col gap-2 rounded-control bg-canvas p-3 text-xs">
      <div className="font-medium text-fg">Auto-login credentials (tried in order on SSH hosts)</div>
      {isLoading && <div className="text-fg-muted">Loading…</div>}
      {bindings?.length === 0 && <div className="text-fg-muted">None bound - discovered SSH hosts won't auto-login.</div>}
      <ul className="flex flex-col gap-1">
        {bindings?.map((binding, i) => {
          const credential = credentials?.find((c) => c.id === binding.credential_id)
          return (
            <li key={binding.id} className="flex items-center gap-2">
              <span className="font-mono text-fg-subtle">#{i + 1}</span>
              <span>{credential?.label ?? `credential ${binding.credential_id}`}</span>
              <button
                type="button"
                className="text-fg-muted hover:text-red-600 hover:underline dark:hover:text-red-400"
                onClick={() => removeCredential.mutate(binding.id)}
              >
                remove
              </button>
            </li>
          )
        })}
      </ul>
      <div className="flex items-center gap-2">
        <select className={inputClasses} value={credentialId} onChange={(e) => setCredentialId(e.target.value)}>
          <option value="">Add credential…</option>
          {available?.map((c) => (
            <option key={c.id} value={c.id}>
              {c.label} ({c.credential_type})
            </option>
          ))}
        </select>
        <button
          type="button"
          className="rounded-control border border-line bg-surface px-2 py-1 font-medium text-fg hover:bg-fg-subtle/10 disabled:opacity-50"
          disabled={!credentialId || addCredential.isPending}
          onClick={handleAdd}
        >
          Add
        </button>
      </div>
      <p className="text-fg-subtle">
        Manage credentials themselves on the{' '}
        <Link to="/integrations" className="text-accent-strong hover:underline">
          Integrations
        </Link>{' '}
        page.
      </p>
    </div>
  )
}

export function NetworksPage() {
  const { data: networks, isLoading } = useNetworks()
  const createNetwork = useCreateNetwork()
  const deleteNetwork = useDeleteNetwork()

  const [name, setName] = useState('')
  const [cidr, setCidr] = useState('')
  const [expandedId, setExpandedId] = useState<number | null>(null)

  function handleSubmit(event: React.FormEvent) {
    event.preventDefault()
    if (!name || !cidr) return
    createNetwork.mutate(
      { name, cidr },
      {
        onSuccess: () => {
          setName('')
          setCidr('')
        },
      },
    )
  }

  return (
    <div>
      <PageHeader
        title="Networks"
        description={
          <>
            Networks define the discovery scope for a CIDR range. Devices can be assigned to one.
            Discovered devices and services show up for review on the{' '}
            <Link to="/discovery" className="text-accent-strong hover:underline">
              Discovery
            </Link>{' '}
            page.
          </>
        }
      />

      <form onSubmit={handleSubmit} className="mt-6 flex flex-wrap items-end gap-3 rounded-card border border-line bg-surface p-4">
        <label className="flex flex-col text-sm">
          Name
          <input
            className={inputClasses}
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="LAN"
          />
        </label>
        <label className="flex flex-col text-sm">
          CIDR
          <input
            className={inputClasses}
            value={cidr}
            onChange={(e) => setCidr(e.target.value)}
            placeholder="192.168.1.0/24"
          />
        </label>
        <button type="submit" disabled={createNetwork.isPending} className={primaryButtonClasses}>
          Add network
        </button>
        {createNetwork.error && <p className="w-full text-sm text-red-600">{createNetwork.error.message}</p>}
      </form>
      {deleteNetwork.error && <p className="mt-2 text-sm text-red-600">{deleteNetwork.error.message}</p>}

      <div className="mt-6 overflow-x-auto">
        <Card className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-line text-fg-muted">
                <th className="px-4 py-2.5 font-medium">Name</th>
                <th className="px-4 py-2.5 font-medium">CIDR</th>
                <th className="px-4 py-2.5 font-medium">VLAN</th>
                <th className="px-4 py-2.5 font-medium">Description</th>
                <th className="px-4 py-2.5" />
              </tr>
            </thead>
            <tbody>
              {isLoading && (
                <tr>
                  <td className="px-4 py-3 text-fg-muted" colSpan={5}>
                    Loading…
                  </td>
                </tr>
              )}
              {networks?.length === 0 && (
                <tr>
                  <td className="px-4 py-3 text-fg-muted" colSpan={5}>
                    No networks yet.
                  </td>
                </tr>
              )}
              {networks?.map((network) => (
                <Fragment key={network.id}>
                  <tr className="border-b border-line last:border-b-0">
                    <td className="px-4 py-2.5 font-medium">{network.name}</td>
                    <td className="px-4 py-2.5 font-mono text-fg-muted">{network.cidr}</td>
                    <td className="px-4 py-2.5 text-fg-muted">{network.vlan_id ?? '—'}</td>
                    <td className="px-4 py-2.5 text-fg-muted">{network.description ?? '—'}</td>
                    <td className="px-4 py-2.5 text-right">
                      <div className="flex items-center justify-end gap-3">
                        <Link
                          to={`/networks/${network.id}/map`}
                          className="text-xs font-medium text-accent-strong hover:underline"
                        >
                          Map
                        </Link>
                        <button
                          type="button"
                          onClick={() => setExpandedId((id) => (id === network.id ? null : network.id))}
                          className="text-xs font-medium text-accent-strong hover:underline"
                        >
                          {expandedId === network.id ? 'Hide credentials' : 'Credentials'}
                        </button>
                        <NetworkScanControl networkId={network.id} />
                        <button
                          type="button"
                          onClick={() => {
                            if (
                              confirm(
                                `Delete network ${network.name}? Its devices and discovered candidates are kept but become unassigned.`,
                              )
                            )
                              deleteNetwork.mutate(network.id)
                          }}
                          disabled={deleteNetwork.isPending}
                          className="text-xs font-medium text-fg-muted hover:text-red-600 hover:underline disabled:opacity-50 dark:hover:text-red-400"
                        >
                          Delete
                        </button>
                      </div>
                    </td>
                  </tr>
                  {expandedId === network.id && (
                    <tr className="border-b border-line last:border-b-0">
                      <td colSpan={5} className="bg-canvas/50 px-4 py-3">
                        <NetworkCredentialsPanel networkId={network.id} />
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        </Card>
      </div>
    </div>
  )
}
