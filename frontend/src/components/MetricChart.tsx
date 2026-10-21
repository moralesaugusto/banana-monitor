import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import type { MetricPoint } from '../api/types'

interface MetricChartProps {
  points: MetricPoint[]
  unit?: string
}

export function MetricChart({ points, unit }: MetricChartProps) {
  if (points.length === 0) {
    return <p className="text-sm text-fg-muted">Not enough data yet.</p>
  }

  const data = points.map((p) => ({
    time: new Date(p.ts).toLocaleTimeString(),
    value: p.value,
  }))

  return (
    <div className="h-40 w-full max-w-lg">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
          <XAxis dataKey="time" tick={{ fontSize: 10 }} minTickGap={30} />
          <YAxis tick={{ fontSize: 10 }} width={40} />
          <Tooltip
            formatter={(value) => {
              const num = typeof value === 'number' ? value : Number(value)
              return [unit ? `${num.toFixed(1)}${unit}` : num, 'value']
            }}
          />
          <Line type="monotone" dataKey="value" stroke="currentColor" dot={false} strokeWidth={2} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}
