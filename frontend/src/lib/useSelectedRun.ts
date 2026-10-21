import { useState } from 'react'
import { useAiRuns, useBusEvents } from '../api/aiMode'

/** Picks which run to look at (default: the latest) and subscribes to live bus events. */
export function useSelectedRun() {
  useBusEvents()
  const { data: runs } = useAiRuns()
  const [chosen, setChosen] = useState<number | null>(null)
  const run = runs?.find((r) => r.id === chosen) ?? runs?.[0]
  return { runs: runs ?? [], run, setChosen }
}
