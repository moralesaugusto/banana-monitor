import { Link, useParams } from 'react-router-dom'
import { useAiRun } from '../../api/aiMode'
import { PageHeader } from '../../components/PageHeader'
import { RunTrace } from './Trace'

export function AiTracePage() {
  const { id } = useParams()
  const { data: run, isLoading, isError } = useAiRun(id ? Number(id) : undefined)
  return (
    <div>
      <PageHeader
        title={`Run #${id}`}
        description="The complete trace: what the model was told, what it decided, which tools it ran and what came back."
        actions={<Link className="text-sm text-accent-strong hover:underline" to="/ai/runs">All runs</Link>}
      />
      <div className="mt-6">
        {isLoading && <p className="text-sm text-fg-muted">Loading...</p>}
        {isError && <p className="text-sm text-fg-muted">Run not found.</p>}
        {run && <RunTrace run={run} />}
      </div>
    </div>
  )
}
