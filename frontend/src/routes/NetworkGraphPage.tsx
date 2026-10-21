import {
  forceCenter,
  forceCollide,
  forceLink,
  forceManyBody,
  forceSimulation,
  type Simulation,
  type SimulationLinkDatum,
  type SimulationNodeDatum,
} from 'd3-force'
import { select } from 'd3-selection'
import { zoom, zoomIdentity, type ZoomTransform } from 'd3-zoom'
import { useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { useRescanService, useService } from '../api/services'
import { useNetworks } from '../api/networks'
import { type NodeKind, type TopologyNode, useTopology } from '../api/topology'
import { Card } from '../components/Card'
import { PageHeader } from '../components/PageHeader'

type SimNode = TopologyNode & SimulationNodeDatum
type SimLink = SimulationLinkDatum<SimNode> & { relation: string }

const KINDS: { kind: NodeKind; label: string; fill: string; radius: number }[] = [
  { kind: 'network', label: 'Network', fill: 'fill-violet-500', radius: 16 },
  { kind: 'device', label: 'Device', fill: 'fill-sky-500', radius: 11 },
  { kind: 'service', label: 'Service', fill: 'fill-emerald-500', radius: 6 },
  { kind: 'integration', label: 'Integration', fill: 'fill-amber-500', radius: 11 },
]
const KIND_STYLE = Object.fromEntries(KINDS.map((k) => [k.kind, k]))

const STATUS_STROKE: Record<string, string> = {
  up: 'stroke-emerald-500',
  down: 'stroke-red-500',
  degraded: 'stroke-amber-500',
  unknown: 'stroke-fg-subtle',
}

const selectClasses =
  'mt-1 rounded-control border border-line bg-surface px-2 py-1 text-sm text-fg focus:border-accent focus:outline-none'

function ServiceDetail({ serviceId }: { serviceId: number }) {
  const { data: service } = useService(serviceId)
  const rescan = useRescanService()
  if (!service) return null
  const fp = service.fingerprint
  const rows: [string, string | number | null | undefined][] = [
    ['port', service.port],
    ['type', service.service_type],
    ['product', fp?.product],
    ['version', fp?.version],
    ['detected as', fp?.name],
    ['extra', fp?.extrainfo],
    ['banner', fp?.banner],
    ['identified by', fp?.source],
    ['fingerprinted', fp?.fingerprinted_at ? new Date(fp.fingerprinted_at).toLocaleString() : null],
    ['latency', service.last_latency_ms != null ? `${service.last_latency_ms.toFixed(1)} ms` : null],
  ]
  const canRescan = service.device_id !== null && service.port !== null
  return (
    <div className="flex flex-col gap-2 border-t border-line pt-3">
      {rows
        .filter(([, v]) => v !== null && v !== undefined && v !== '')
        .map(([k, v]) => (
          <div key={k} className="flex justify-between gap-2">
            <span className="shrink-0 text-fg-muted">{k}</span>
            <span className="break-all text-right font-mono text-xs">{String(v)}</span>
          </div>
        ))}
      {!fp && <p className="text-xs text-fg-muted">Not fingerprinted yet.</p>}
      {canRescan && (
        <button
          type="button"
          className="rounded-control border border-line bg-surface px-3 py-1.5 text-sm hover:bg-fg-subtle/10 disabled:opacity-50"
          disabled={rescan.isPending}
          onClick={() => rescan.mutate(serviceId)}
        >
          {rescan.isPending ? 'Fingerprinting…' : 'Re-fingerprint with nmap'}
        </button>
      )}
      {rescan.isError && <p className="text-xs text-red-600 dark:text-red-400">{rescan.error.message}</p>}
      {rescan.isSuccess && (
        <p className="text-xs text-fg-muted">{rescan.data.updated ? 'Fingerprint updated.' : 'nmap returned nothing for this port.'}</p>
      )}
    </div>
  )
}

export function NetworkGraphPage() {
  const { data: networks } = useNetworks()
  const [networkId, setNetworkId] = useState<number | null>(null)
  const { data: topology, isLoading } = useTopology(networkId)

  const [hiddenKinds, setHiddenKinds] = useState<Set<NodeKind>>(new Set())
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set())
  const [statusFilter, setStatusFilter] = useState('')
  const [query, setQuery] = useState('')
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [, setFrame] = useState(0)
  const [transform, setTransform] = useState<ZoomTransform>(zoomIdentity)

  const svgRef = useRef<SVGSVGElement>(null)
  const simRef = useRef<Simulation<SimNode, SimLink> | null>(null)
  // Positions survive refetches so the graph does not jump every 15 seconds.
  const positions = useRef(new Map<string, { x: number; y: number; fx?: number | null; fy?: number | null }>())
  const dragging = useRef<SimNode | null>(null)

  const visible = useMemo(() => {
    if (!topology) return { nodes: [] as SimNode[], links: [] as SimLink[] }
    const hiddenByCollapse = new Set<string>()
    for (const edge of topology.edges) {
      if (edge.relation === 'runs' && collapsed.has(edge.source)) hiddenByCollapse.add(edge.target)
    }
    const nodes: SimNode[] = topology.nodes
      .filter((n) => !hiddenKinds.has(n.kind) && !hiddenByCollapse.has(n.id))
      .filter((n) => !statusFilter || n.status === statusFilter || n.kind === 'network')
      .map((n) => ({ ...n, ...positions.current.get(n.id) }))
    const ids = new Set(nodes.map((n) => n.id))
    const links: SimLink[] = topology.edges
      .filter((e) => ids.has(e.source) && ids.has(e.target))
      .map((e) => ({ source: e.source, target: e.target, relation: e.relation }))
    return { nodes, links }
  }, [topology, hiddenKinds, collapsed, statusFilter])

  useEffect(() => {
    const sim = forceSimulation<SimNode>(visible.nodes)
      .force('link', forceLink<SimNode, SimLink>(visible.links).id((n) => n.id).distance(55).strength(0.7))
      .force('charge', forceManyBody().strength(-160))
      .force('center', forceCenter(450, 300))
      .force('collide', forceCollide<SimNode>().radius((n) => KIND_STYLE[n.kind].radius + 4))
    let pending = false
    sim.on('tick', () => {
      for (const n of visible.nodes) {
        positions.current.set(n.id, { x: n.x ?? 0, y: n.y ?? 0, fx: n.fx, fy: n.fy })
      }
      if (!pending) {
        pending = true
        requestAnimationFrame(() => {
          pending = false
          setFrame((f) => f + 1)
        })
      }
    })
    simRef.current = sim
    return () => {
      sim.stop()
    }
  }, [visible])

  useEffect(() => {
    if (!svgRef.current) return
    const behavior = zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.2, 4])
      .extent(() => {
        const rect = svgRef.current?.getBoundingClientRect()
        return [[0, 0], [rect?.width || 900, rect?.height || 620]]
      })
      .filter((event) => !dragging.current && !event.button)
      .on('zoom', (event) => setTransform(event.transform))
    select(svgRef.current).call(behavior)
  }, [])

  const matches = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return null
    return new Set(
      visible.nodes
        .filter((n) => `${n.label} ${n.subtitle ?? ''} ${n.kind}`.toLowerCase().includes(q))
        .map((n) => n.id),
    )
  }, [query, visible.nodes])

  const selected = topology?.nodes.find((n) => n.id === selectedId) ?? null
  const neighbors = useMemo(() => {
    if (!topology || !selectedId) return []
    return topology.edges
      .filter((e) => e.source === selectedId || e.target === selectedId)
      .map((e) => ({
        relation: e.relation,
        outgoing: e.source === selectedId,
        node: topology.nodes.find((n) => n.id === (e.source === selectedId ? e.target : e.source)),
      }))
      .filter((x) => x.node)
  }, [topology, selectedId])

  function toggleKind(kind: NodeKind) {
    setHiddenKinds((prev) => {
      const next = new Set(prev)
      if (next.has(kind)) next.delete(kind)
      else next.add(kind)
      return next
    })
  }

  function toggleCollapse(id: string) {
    setCollapsed((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  function pointerToGraph(event: React.PointerEvent): [number, number] {
    const rect = svgRef.current!.getBoundingClientRect()
    return [
      (event.clientX - rect.left - transform.x) / transform.k,
      (event.clientY - rect.top - transform.y) / transform.k,
    ]
  }

  function detailLink(node: TopologyNode): string | null {
    if (node.kind === 'device') return `/devices/${node.entity_id}`
    if (node.kind === 'service') return '/services'
    if (node.kind === 'integration') return '/integrations'
    if (node.kind === 'network') return `/networks/${node.entity_id}/map`
    return null
  }

  return (
    <div>
      <PageHeader
        title="Network Map"
        description="What is connected to what: networks contain devices, devices run services, integrations monitor them. Click a node to inspect it, double-click a device to fold its services, drag to pin, scroll to zoom."
      />

      <div className="mt-4 flex flex-wrap items-end gap-4 text-sm">
        <label className="flex flex-col">
          Network
          <select
            className={selectClasses}
            value={networkId ?? ''}
            onChange={(e) => setNetworkId(e.target.value ? Number(e.target.value) : null)}
          >
            <option value="">All networks</option>
            {networks?.map((n) => (
              <option key={n.id} value={n.id}>
                {n.name}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col">
          Status
          <select className={selectClasses} value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
            <option value="">Any</option>
            {['up', 'down', 'degraded', 'unknown'].map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col">
          Search
          <input
            className={selectClasses}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="name, ip, product"
          />
        </label>
        <div className="flex items-center gap-3">
          {KINDS.map((k) => (
            <label key={k.kind} className="flex items-center gap-1.5">
              <input type="checkbox" checked={!hiddenKinds.has(k.kind)} onChange={() => toggleKind(k.kind)} />
              <svg width="12" height="12" aria-hidden>
                <circle cx="6" cy="6" r="5" className={k.fill} />
              </svg>
              {k.label}
            </label>
          ))}
        </div>
        <button
          type="button"
          className="rounded-control border border-line bg-surface px-3 py-1.5 text-sm hover:bg-fg-subtle/10"
          onClick={() => {
            positions.current.clear()
            setCollapsed(new Set())
            setTransform(zoomIdentity)
            if (svgRef.current) select(svgRef.current).call(zoom<SVGSVGElement, unknown>().transform, zoomIdentity)
            simRef.current?.alpha(1).restart()
          }}
        >
          Reset layout
        </button>
      </div>

      {topology?.truncated && (
        <p className="mt-2 text-xs text-fg-muted">
          Very large network: services are hidden. Pick a single network to see them.
        </p>
      )}

      <div className="mt-4 grid gap-4 lg:grid-cols-[1fr_280px]">
        <Card className="overflow-hidden">
          {isLoading && <div className="p-4 text-sm text-fg-muted">Loading...</div>}
          <svg ref={svgRef} className="h-[620px] w-full touch-none select-none" role="img" aria-label="Network graph">
            <g transform={`translate(${transform.x},${transform.y}) scale(${transform.k})`}>
              {visible.links.map((link, i) => {
                const s = link.source as SimNode
                const t = link.target as SimNode
                if (s.x == null || t.x == null) return null
                const active = selectedId && (s.id === selectedId || t.id === selectedId)
                return (
                  <line
                    key={i}
                    x1={s.x}
                    y1={s.y}
                    x2={t.x}
                    y2={t.y}
                    className={active ? 'stroke-accent' : 'stroke-fg-subtle/40'}
                    strokeWidth={active ? 2 : 1}
                    strokeDasharray={link.relation === 'monitors' ? '4 3' : undefined}
                  >
                    <title>{link.relation}</title>
                  </line>
                )
              })}
              {visible.nodes.map((node) => {
                if (node.x == null) return null
                const style = KIND_STYLE[node.kind]
                const dim = matches && !matches.has(node.id)
                const folded = node.kind === 'device' && collapsed.has(node.id)
                return (
                  <g
                    key={node.id}
                    transform={`translate(${node.x},${node.y})`}
                    opacity={dim ? 0.15 : 1}
                    className="cursor-pointer"
                    onClick={() => setSelectedId(node.id)}
                    onDoubleClick={() => node.kind === 'device' && toggleCollapse(node.id)}
                    onPointerDown={(e) => {
                      e.stopPropagation()
                      ;e.currentTarget.setPointerCapture?.(e.pointerId)
                      dragging.current = node
                      simRef.current?.alphaTarget(0.3).restart()
                    }}
                    onPointerMove={(e) => {
                      if (dragging.current !== node) return
                      const [x, y] = pointerToGraph(e)
                      node.fx = x
                      node.fy = y
                    }}
                    onPointerUp={() => {
                      dragging.current = null
                      simRef.current?.alphaTarget(0)
                    }}
                  >
                    <circle
                      r={style.radius}
                      className={`${style.fill} ${STATUS_STROKE[node.status ?? ''] ?? 'stroke-transparent'}`}
                      strokeWidth={node.status ? 3 : 0}
                    />
                    {node.id === selectedId && (
                      <circle r={style.radius + 5} className="fill-none stroke-accent" strokeWidth={2} />
                    )}
                    {folded && <circle r={style.radius + 3} className="fill-none stroke-fg-muted" strokeDasharray="2 2" />}
                    {node.kind !== 'service' && (
                      <text y={style.radius + 12} textAnchor="middle" className="fill-fg text-[10px]">
                        {node.label}
                      </text>
                    )}
                    <title>{`${node.label}${node.subtitle ? ` - ${node.subtitle}` : ''}`}</title>
                  </g>
                )
              })}
            </g>
          </svg>
        </Card>

        <Card className="p-4 text-sm">
          {!selected && <p className="text-fg-muted">Select a node to see what it is connected to.</p>}
          {selected && (
            <div className="flex flex-col gap-3">
              <div>
                <div className="text-xs uppercase text-fg-muted">{selected.kind}</div>
                <div className="text-base font-semibold text-fg">{selected.label}</div>
                {selected.subtitle && <div className="font-mono text-xs text-fg-muted">{selected.subtitle}</div>}
              </div>
              {selected.status && <div>Status: {selected.status}</div>}
              {Object.entries(selected.meta)
                .filter(([, v]) => v !== null && v !== undefined)
                .map(([k, v]) => (
                  <div key={k} className="flex justify-between gap-2">
                    <span className="text-fg-muted">{k.replace('_', ' ')}</span>
                    <span className="font-mono">{String(v)}</span>
                  </div>
                ))}
              {selected.kind === 'service' && <ServiceDetail serviceId={selected.entity_id} />}
              {detailLink(selected) && (
                <Link to={detailLink(selected)!} className="text-accent-strong hover:underline">
                  Open full page
                </Link>
              )}
              <div>
                <div className="mb-1 text-xs uppercase text-fg-muted">Connected ({neighbors.length})</div>
                <ul className="flex max-h-60 flex-col gap-1 overflow-y-auto">
                  {neighbors.map((nb, i) => (
                    <li key={i}>
                      <button
                        type="button"
                        className="text-left hover:underline"
                        onClick={() => setSelectedId(nb.node!.id)}
                      >
                        <span className="text-fg-muted">
                          {nb.outgoing ? nb.relation : `${nb.relation} by`}{' '}
                        </span>
                        {nb.node!.label}
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          )}
        </Card>
      </div>
    </div>
  )
}
