import { useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { useKnowledgeProjection, type ProjectionPoint } from '../../api/knowledge'
import { Card } from '../../components/Card'
import { PageHeader } from '../../components/PageHeader'

const WIDTH = 640
const HEIGHT = 420
const PADDING = 24
const PALETTE = ['#2563eb', '#16a34a', '#d97706', '#dc2626', '#7c3aed', '#0891b2', '#db2777', '#65a30d']

function colorFor(collectionName: string, names: string[]): string {
  const index = names.indexOf(collectionName)
  return PALETTE[index % PALETTE.length]
}

/** Scales raw PCA coordinates (unbounded, centered near 0) into the SVG's pixel box, flipping Y
 * since SVG's origin is top-left while a reader expects "up" to mean a larger value. */
function layout(points: ProjectionPoint[]): { cx: number; cy: number; point: ProjectionPoint }[] {
  if (points.length === 0) return []
  const xs = points.map((p) => p.x)
  const ys = points.map((p) => p.y)
  const minX = Math.min(...xs)
  const maxX = Math.max(...xs)
  const minY = Math.min(...ys)
  const maxY = Math.max(...ys)
  const spanX = maxX - minX || 1
  const spanY = maxY - minY || 1
  return points.map((point) => ({
    cx: PADDING + ((point.x - minX) / spanX) * (WIDTH - 2 * PADDING),
    cy: HEIGHT - PADDING - ((point.y - minY) / spanY) * (HEIGHT - 2 * PADDING),
    point,
  }))
}

/** A 2D PCA scatter of every entry's embedding, colored by collection - the visual view into the
 * knowledge base. Each point is one piece of text; points close together were judged similar by
 * the embedding model. This is a lossy 2D shadow of a much higher-dimensional space, so rough
 * clustering is what matters, not exact distances - see Knowledge > How it works. Clicking a
 * point opens its full detail (content, embedding model, dimensions) on the Browse page. */
export function KnowledgeMapPage() {
  const { data: points, isLoading } = useKnowledgeProjection()
  const navigate = useNavigate()

  const collectionNames = useMemo(
    () => Array.from(new Set((points ?? []).map((p) => p.collection_name))).sort(),
    [points],
  )
  const placed = useMemo(() => layout(points ?? []), [points])

  return (
    <div>
      <PageHeader
        title="Knowledge map"
        description="Every entry's embedding, projected down to two dimensions (PCA). Points near each other were judged similar in meaning; the axes themselves have no label worth reading. Click a point to open it."
      />

      <div className="mt-6 grid gap-6 lg:grid-cols-[1fr_16rem]">
        <Card className="p-4">
          {isLoading && <p className="text-sm text-fg-muted">Loading…</p>}
          {!isLoading && placed.length === 0 && (
            <p className="text-sm text-fg-muted">No entries yet - add some under Knowledge &gt; Browse.</p>
          )}
          {placed.length > 0 && (
            <svg
              role="img"
              aria-label="Knowledge embedding map"
              viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
              className="h-auto w-full"
            >
              {placed.map(({ cx, cy, point }) => (
                <circle
                  key={point.entry_id}
                  cx={cx}
                  cy={cy}
                  r={5}
                  fill={colorFor(point.collection_name, collectionNames)}
                  stroke="var(--color-surface, white)"
                  strokeWidth={1.5}
                  style={{ cursor: 'pointer' }}
                  role="button"
                  tabIndex={0}
                  aria-label={`${point.title} (${point.collection_name})`}
                  onClick={() => navigate(`/ai/knowledge?entry=${point.entry_id}`)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') navigate(`/ai/knowledge?entry=${point.entry_id}`)
                  }}
                >
                  <title>
                    {point.title} ({point.collection_name})
                  </title>
                </circle>
              ))}
            </svg>
          )}
        </Card>

        <Card className="self-start p-4">
          <h2 className="text-xs font-semibold uppercase tracking-wide text-fg-muted">Collections</h2>
          <ul className="mt-3 space-y-1.5">
            {collectionNames.map((name) => (
              <li key={name} className="flex items-center gap-2 text-sm">
                <span
                  className="h-2.5 w-2.5 rounded-full"
                  style={{ backgroundColor: colorFor(name, collectionNames) }}
                />
                {name}
              </li>
            ))}
          </ul>
        </Card>
      </div>
    </div>
  )
}
