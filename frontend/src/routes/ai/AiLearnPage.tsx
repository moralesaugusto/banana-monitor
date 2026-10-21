import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useAgents, useAiRun, useAiRuns, useMessages } from '../../api/aiMode'
import { Card } from '../../components/Card'
import { PageHeader } from '../../components/PageHeader'
import { explainMessage, messageText, topicMatches } from '../../lib/bus'
import { explainStep } from './Trace'

const LOOP = [
  { title: '1. Observe', body: 'The model receives the instructions (system prompt), the message it was given, and everything that has happened so far in this turn.' },
  { title: '2. Decide', body: 'It picks the next move: call a tool such as nmap, or stop and write an answer. It is guessing the most useful next step, like an engineer would.' },
  { title: '3. Act', body: 'This application checks the request against the guardrails, runs the real command, and captures the output.' },
  { title: '4. Learn', body: 'The output goes back to the model as a new message. It reads it, and the loop repeats until it is done or hits its loop limit.' },
]

const TIMING_CONCEPTS = [
  { title: 'Independent loops', body: 'Every enabled agent runs as its own task on the same event loop, started the moment a run begins. They are concurrent, not sequential: one agent running a tool or waiting on the model never blocks another agent from doing the same at the same time.' },
  { title: 'Reacting, not calling', body: 'An agent only wakes up when a message matching its subscription lands in its own queue. Publishing never waits for a reply, so a fast agent can publish several messages before a slower one has even read its first.' },
  { title: 'Model-call gate', body: 'Every agent on one Ollama host shares the same GPU, so at most a few model calls run at once across the whole run - 2 by default. OpenRouter is a hosted API that tolerates more, so its default is 4. Both are configurable under AI Settings > Settings ("Max concurrent Ollama/OpenRouter calls"), independently of each other.' },
  { title: 'Tool-call gate', body: 'Separately, up to 4 tool calls run at once across the whole run - whether that is one agent’s turn asking for several tools, or several agents each mid-tool-call at the same moment.' },
  { title: 'Time limits, three levels', body: 'A run has an overall deadline ("Time limit per run"). Each agent has its own "Loop limit": how many model calls it may make answering one message before it is forced to stop and answer anyway. Each individual model call has its own "Model call timeout".' },
  { title: 'Live activity, not just busy/idle', body: 'The Workflow and Map pages show each agent’s actual activity - Waiting on model reply, Running tool call(s), or Held for approval - instead of a single working/waiting flag, so a stuck Ollama call looks different from a long-running nmap scan.' },
]

const BUS_CONCEPTS = [
  { title: 'Agent', body: 'One model with its own prompt, tools, settings and loop limit. An agent has no idea how many other agents exist; it only reads messages and publishes messages.' },
  { title: 'Topic', body: 'A name for a kind of message, written as dot-separated words: task.discoverer, discovery.service.found, result.reviewer. A topic is not a mailbox and has no owner.' },
  { title: 'Publish', body: 'An agent hands the bus a message and a topic. It never says who should receive it. That is what decouples agents: you can add a listener without touching the sender.' },
  { title: 'Subscribe', body: 'An agent declares topic patterns it wants. The bus delivers a copy of every matching message to it. The pattern * matches one word; # matches the rest (result.# matches result.reviewer and result.a.b).' },
  { title: 'Envelope', body: 'Every message carries: an id, topic, publisher, the payload, a conversation (correlation) id shared by every message that grew out of one task, a hop count, and an optional reply_to topic.' },
  { title: 'Log first, then deliver', body: 'The bus writes each message to the database before handing it to anyone, so the Messages page can show exactly what happened even after a restart. Each recipient has a delivery state: delivered, then acked once it finished handling it.' },
  { title: 'Human in the loop', body: 'An agent can be set so its messages or tool calls wait for you. The message is stored as held and nobody receives it until you approve it, edit it, or reject it with a reason that the agent sees.' },
  { title: 'Loop protection', body: 'Agents that answer each other could talk forever. Each message counts a hop from the original task, and a run has a maximum number of hops, messages and minutes. You can also pause or stop a run.' },
]

const GLOSSARY: [string, string][] = [
  ['Model', 'The language model (served by Ollama) that reads text and produces the next action.'],
  ['System prompt', 'Standing instructions placed at the start of every turn. Edit them per agent under Agents.'],
  ['Tool calling', 'The model answers with a structured request such as run_nmap(target=...) instead of prose. It never executes anything itself.'],
  ['Tokens', 'Chunks of text the model reads (in) and writes (out). Each step re-reads the whole conversation, so input tokens grow as a turn goes on.'],
  ['Temperature', 'How adventurous the model is. Low values repeat the most likely choice; higher values explore.'],
  ['Guardrails', 'Rules enforced by the application, outside the model: target limits, flag allowlist, timeouts. The model cannot talk its way past them, and they apply to every agent.'],
  ['Dry run', 'The agents explore for real but record_service calls are only simulated, so nothing is written.'],
  ['Pub/sub', 'Publish/subscribe: senders and receivers know only topics, never each other. The same model MQTT, NATS and Kafka use, here running inside this process.'],
  ['Broker / bus', 'The component that matches published messages to subscriptions. Here it is a small in-process module (backend/app/llm/bus.py); there is no external server.'],
  ['Correlation id', 'An id copied from message to message so everything that came from one task can be grouped into one conversation.'],
  ['Ack', 'Acknowledgement: the recipient tells the bus it finished handling a message. A run is finished when every message is acked and none is waiting for you.'],
  ['Held message', 'A message waiting for a human decision. It is logged but not delivered.'],
  ['Event loop', 'The single thread that runs every agent’s coroutine, switching between them while each one waits on I/O (a model call, SSH, HTTP). This is how many agents run "at once" in one process without separate threads.'],
  ['Concurrency gate', 'A counter that only lets a limited number of a certain kind of call run at once; everything past the limit simply waits its turn. Used here for model calls (per provider) and for tool calls.'],
  ['Activity', 'An agent’s moment-to-moment status while a run is active: waiting on a model reply, running a tool call, or held for your approval - shown live on the Workflow and Map pages.'],
]

function MatchTester() {
  const [pattern, setPattern] = useState('result.#')
  const [topic, setTopic] = useState('result.reviewer')
  const matches = topicMatches(pattern, topic)
  const input = 'rounded-control border border-line bg-surface px-2 py-1 font-mono text-sm'
  return (
    <Card className="p-4">
      <div className="text-sm font-medium">Try the matcher</div>
      <p className="mt-1 text-xs text-fg-muted">This is the exact function the bus uses to decide who receives a message.</p>
      <div className="mt-3 flex flex-wrap items-center gap-3 text-sm">
        <label className="flex items-center gap-2">
          Subscription pattern
          <input className={input} value={pattern} onChange={(e) => setPattern(e.target.value)} />
        </label>
        <label className="flex items-center gap-2">
          Published topic
          <input className={input} value={topic} onChange={(e) => setTopic(e.target.value)} />
        </label>
        <span className={matches ? 'font-medium text-emerald-600' : 'font-medium text-red-600'}>
          {matches ? 'delivered' : 'not delivered'}
        </span>
      </div>
    </Card>
  )
}

export function AiLearnPage() {
  const { data: runs } = useAiRuns()
  const finished = runs?.find((r) => r.status !== 'running')
  const { data: run } = useAiRun(finished?.id)
  const { data: messages } = useMessages(finished?.id)
  const { list: agents } = useAgents()

  return (
    <div>
      <PageHeader
        title="How it works"
        description="An AI agent is a language model in a loop with tools. A team of agents is several of those loops, running concurrently, that coordinate only by publishing and subscribing to messages. This page explains both, how their timing and concurrency limits work, and replays a real run from your network."
      />

      <h2 className="mt-6 text-lg font-semibold">Part 1: one agent</h2>
      <div className="mt-3 grid gap-4 md:grid-cols-4">
        {LOOP.map((s) => (
          <Card key={s.title} className="p-4">
            <div className="text-sm font-semibold text-fg">{s.title}</div>
            <p className="mt-2 text-sm text-fg-muted">{s.body}</p>
          </Card>
        ))}
      </div>

      <h2 className="mt-8 text-lg font-semibold">Part 2: a team that talks through a message bus</h2>
      <p className="mt-2 max-w-3xl text-sm text-fg-muted">
        With several agents the question is how they cooperate. The simplest answer, one agent calling another
        directly, makes every agent depend on every other. Publish/subscribe removes that: a publisher only names a
        topic, and the bus delivers to whoever subscribed. In this app the flow is:
      </p>
      <ol className="mt-3 max-w-3xl list-decimal pl-5 text-sm text-fg-muted">
        <li>You start a run. If you did not give explicit targets, they come from devices on a configured network, skipping any marked <Link className="text-accent-strong hover:underline" to="/devices">Inactive</Link> (down for more than a few days). The app publishes a <span className="font-mono">task.discoverer</span> message with the targets.</li>
        <li>The <span className="font-mono">discoverer</span> is subscribed to that topic, so it receives the message and runs its loop with nmap, nc and record_service.</li>
        <li>Each service it records is announced on <span className="font-mono">discovery.service.found</span> automatically.</li>
        <li>The <span className="font-mono">reviewer</span> subscribes to that topic, so it receives every announcement and double-checks it, then publishes <span className="font-mono">result.reviewer</span>.</li>
        <li>When every message is acknowledged and nothing is waiting for you, the run ends.</li>
      </ol>
      <p className="mt-3 max-w-3xl text-sm text-fg-muted">
        Every subscribed agent's loop is already running, idle, waiting on its own queue - steps 2 and 4 above can
        happen for two different agents at the very same moment. Nothing here is a chain of calls that waits its
        turn; it is several independent loops that happen to react to each other's output. See the timing section
        below for exactly what is, and is not, limited.
      </p>
      <p className="mt-3 text-sm">
        Watch it happen on the <Link className="text-accent-strong hover:underline" to="/ai/map">Map</Link> and read every message on the{' '}
        <Link className="text-accent-strong hover:underline" to="/ai/messages">Messages</Link> page. Change who listens to what on the{' '}
        <Link className="text-accent-strong hover:underline" to="/ai/agents">Agents</Link> page.
      </p>

      <h2 className="mt-8 text-lg font-semibold">Part 3: timing and concurrency</h2>
      <p className="mt-2 max-w-3xl text-sm text-fg-muted">
        "Concurrent" does not mean "unlimited." Agents share real, scarce resources - one GPU, one network - so a
        few limits keep everything moving instead of overloading any one of them.
      </p>
      <div className="mt-3 grid gap-4 md:grid-cols-2 lg:grid-cols-3">
        {TIMING_CONCEPTS.map((s) => (
          <Card key={s.title} className="p-4">
            <div className="text-sm font-semibold text-fg">{s.title}</div>
            <p className="mt-2 text-sm text-fg-muted">{s.body}</p>
          </Card>
        ))}
      </div>

      <div className="mt-4 grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        {BUS_CONCEPTS.map((s) => (
          <Card key={s.title} className="p-4">
            <div className="text-sm font-semibold text-fg">{s.title}</div>
            <p className="mt-2 text-sm text-fg-muted">{s.body}</p>
          </Card>
        ))}
      </div>

      <div className="mt-4"><MatchTester /></div>

      {agents.data && (
        <Card className="mt-4 p-4">
          <div className="text-sm font-medium">Who listens to what right now</div>
          <table className="mt-2 w-full text-left text-sm">
            <thead>
              <tr className="text-fg-muted">
                <th className="py-1 font-medium">Agent</th>
                <th className="py-1 font-medium">Subscribes to</th>
                <th className="py-1 font-medium">May publish to</th>
              </tr>
            </thead>
            <tbody>
              {agents.data.map((a) => (
                <tr key={a.id} className="border-t border-line">
                  <td className="py-1.5 font-mono">{a.name}</td>
                  <td className="py-1.5 font-mono text-xs">{a.subscribes.join(', ') || '-'}</td>
                  <td className="py-1.5 font-mono text-xs">{a.publishes.join(', ') || '-'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}

      <h2 className="mt-8 text-lg font-semibold">A real run: the messages</h2>
      {!run && (
        <p className="mt-2 text-sm text-fg-muted">
          No finished run yet. <Link className="text-accent-strong hover:underline" to="/ai">Start one</Link> and it will be replayed here.
        </p>
      )}
      {run && (
        <>
          <Card className="mt-3 p-4">
            <p className="text-sm text-fg-muted">
              Run #{run.id} on {run.targets.join(', ')}: {messages?.length ?? 0} bus messages.{' '}
              <Link className="text-accent-strong hover:underline" to="/ai/messages">Open the message log</Link>
            </p>
            <ol className="mt-3 flex flex-col gap-2 text-sm">
              {messages?.map((m, i) => (
                <li key={m.id} className="flex gap-3">
                  <span className="w-6 shrink-0 text-right font-mono text-fg-muted">{i + 1}</span>
                  <span>
                    {explainMessage(m)} <span className="text-fg-muted">&ldquo;{messageText(m).slice(0, 120)}&rdquo;</span>
                  </span>
                </li>
              ))}
              {messages?.length === 0 && <li className="text-fg-muted">This run predates the message bus.</li>}
            </ol>
          </Card>

          <h2 className="mt-8 text-lg font-semibold">A real run: inside each agent&apos;s loop</h2>
          <Card className="mt-3 p-4">
            <p className="text-sm text-fg-muted">
              Used <span className="font-mono">{run.model}</span> and took {run.steps.length} steps.{' '}
              <Link className="text-accent-strong hover:underline" to={`/ai/runs/${run.id}`}>Open the full trace</Link>
            </p>
            <ol className="mt-3 flex flex-col gap-2 text-sm">
              {run.steps.map((step) => (
                <li key={step.idx} className="flex gap-3">
                  <span className="w-6 shrink-0 text-right font-mono text-fg-muted">{step.idx + 1}</span>
                  <span>{explainStep(step)}</span>
                </li>
              ))}
            </ol>
            {run.summary && <p className="mt-3 border-t border-line pt-3 text-sm">{run.summary}</p>}
          </Card>
        </>
      )}

      <h2 className="mt-8 text-lg font-semibold">Glossary</h2>
      <Card className="mt-3 divide-y divide-line">
        {GLOSSARY.map(([term, text]) => (
          <div key={term} className="flex flex-wrap gap-x-4 px-4 py-2.5 text-sm">
            <span className="w-32 shrink-0 font-medium">{term}</span>
            <span className="flex-1 text-fg-muted">{text}</span>
          </div>
        ))}
      </Card>
    </div>
  )
}
