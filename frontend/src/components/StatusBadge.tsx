import type { HealthStatus } from '../api/types'
import { Badge, type BadgeTone } from './Badge'

const TONES: Record<HealthStatus, BadgeTone> = {
  up: 'ok',
  down: 'bad',
  degraded: 'warn',
  unknown: 'neutral',
}

export function StatusBadge({ status }: { status: HealthStatus }) {
  return <Badge tone={TONES[status]}>{status}</Badge>
}
