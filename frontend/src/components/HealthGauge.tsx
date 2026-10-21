/** A semicircle gauge for a 0-100 score, with the number in the middle. */
export function HealthGauge({ score, label = 'Health score' }: { score: number; label?: string }) {
  const clamped = Math.max(0, Math.min(100, score))
  const radius = 80
  const length = Math.PI * radius
  const color = clamped >= 75 ? '#10b981' : clamped >= 50 ? '#f59e0b' : '#ef4444'
  return (
    <div className="flex flex-col items-center">
      <svg viewBox="0 0 200 120" className="w-56" role="img" aria-label={`${label}: ${clamped}`}>
        <path d="M20 100a80 80 0 0 1 160 0" fill="none" stroke="var(--line)" strokeWidth="12" strokeLinecap="round" />
        <path
          d="M20 100a80 80 0 0 1 160 0"
          fill="none"
          stroke={color}
          strokeWidth="12"
          strokeLinecap="round"
          strokeDasharray={`${(clamped / 100) * length} ${length}`}
        />
        <text x="100" y="92" textAnchor="middle" className="fill-current" fontSize="40" fontWeight="500">
          {clamped}
        </text>
        <text x="100" y="112" textAnchor="middle" className="fill-[var(--fg-muted)]" fontSize="11">
          {label}
        </text>
      </svg>
    </div>
  )
}

/** A three-axis radar: each axis is the percentage (0-100) of something that is healthy. */
export function HealthRadar({ axes }: { axes: { label: string; value: number }[] }) {
  const center = 90
  const radius = 62
  const point = (index: number, value: number) => {
    const angle = -Math.PI / 2 + (index * 2 * Math.PI) / axes.length
    const r = (radius * Math.max(0, Math.min(100, value))) / 100
    return `${(center + r * Math.cos(angle)).toFixed(1)},${(center + r * Math.sin(angle)).toFixed(1)}`
  }
  const ring = (value: number) => axes.map((_, i) => point(i, value)).join(' ')
  return (
    <svg viewBox="0 0 180 180" className="w-44" role="img" aria-label="Health by area">
      {[25, 50, 75, 100].map((value) => (
        <polygon key={value} points={ring(value)} fill="none" stroke="var(--line)" strokeWidth="1" />
      ))}
      {axes.map((axis, i) => {
        const [x, y] = point(i, 100).split(',').map(Number)
        const [lx, ly] = point(i, 118).split(',').map(Number)
        return (
          <g key={axis.label}>
            <line x1={center} y1={center} x2={x} y2={y} stroke="var(--line)" strokeWidth="1" />
            <text x={lx} y={ly} textAnchor="middle" dominantBaseline="middle" fontSize="10" className="fill-[var(--fg-muted)]">
              {axis.label}
            </text>
          </g>
        )
      })}
      <polygon points={axes.map((a, i) => point(i, a.value)).join(' ')} fill="var(--accent-soft-strong)" stroke="var(--accent)" strokeWidth="1.5" />
    </svg>
  )
}
