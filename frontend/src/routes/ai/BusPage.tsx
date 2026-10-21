import { useSearchParams } from 'react-router-dom'
import { useAgents } from '../../api/aiMode'
import { PageHeader } from '../../components/PageHeader'
import { Segmented } from '../../components/Segmented'
import { useSelectedRun } from '../../lib/useSelectedRun'
import { BusConversations } from './BusConversations'
import { BusFlow } from './BusFlow'
import { BusHealth } from './BusHealth'
import { BusRouting } from './BusRouting'
import { BusTopics } from './BusTopics'
import { RunPicker } from './RunPicker'

const TABS = [
  { value: 'routing', label: 'Routing table' },
  { value: 'topics', label: 'Topics' },
  { value: 'health', label: 'Queues and health' },
  { value: 'flow', label: 'Live flow' },
  { value: 'conversations', label: 'Conversations' },
] as const
type Tab = (typeof TABS)[number]['value']

export function BusPage() {
  const [params, setParams] = useSearchParams()
  const tab: Tab = TABS.find((t) => t.value === params.get('tab'))?.value ?? 'routing'
  const { runs, run, setChosen } = useSelectedRun()
  const agents = useAgents().list.data ?? []

  return (
    <div>
      <PageHeader
        title="Bus"
        description="How messages find their way between agents. Publishers name a topic, never a recipient; the bus delivers to every agent whose subscription pattern matches. The routing table shows the rules; the other views show what actually flowed in a run, how close it is to its limits, and who talked to whom."
      />
      <div className="mt-4 flex flex-wrap items-center gap-4">
        <Segmented options={[...TABS]} value={tab} onChange={(value) => setParams({ tab: value })} label="Bus view" />
        {tab !== 'routing' && <RunPicker runs={runs} run={run} onChange={setChosen} />}
      </div>
      <div className="mt-4">
        {tab === 'routing' && <BusRouting agents={agents} />}
        {tab === 'topics' && <BusTopics runId={run?.id ?? null} />}
        {tab === 'health' && <BusHealth runId={run?.id} />}
        {tab === 'flow' && <BusFlow runId={run?.id} />}
        {tab === 'conversations' && <BusConversations runId={run?.id} />}
      </div>
    </div>
  )
}
