import { useMemo, useState } from 'react'
import { type CatalogModel, type Cost, useCost, useOpenRouterCatalog, useResetCost } from '../../api/aiCost'
import { Card, StatTile } from '../../components/Card'

const n = (value: number) => value.toLocaleString()
const usd = (value: number) => (value < 0.01 && value > 0 ? '<$0.01' : `$${value.toFixed(2)}`)
const agentName = (source: string, agent: string) => (source === 'assistant' ? 'Chat assistant' : agent)
const cell = 'px-3 py-2 text-right font-mono tabular-nums'
const head = 'px-3 py-2 text-right text-xs font-medium text-fg-muted'

/** What `inTokens`/`outTokens` would cost at a model's list price. */
export function estimate(model: CatalogModel, inTokens: number, outTokens: number): number {
  return (inTokens / 1_000_000) * model.usd_per_million_in + (outTokens / 1_000_000) * model.usd_per_million_out
}

/** Whole days between the first counted day and today (at least 1), to turn totals into a per-day rate. */
function daysCounted(cost: Cost): number {
  if (!cost.first_day) return 1
  const first = new Date(`${cost.first_day}T00:00:00Z`).getTime()
  return Math.max(1, Math.floor((Date.now() - first) / 86_400_000) + 1)
}

function Table({ children }: { children: React.ReactNode }) {
  return (
    <Card className="overflow-x-auto">
      <table className="w-full text-sm">{children}</table>
    </Card>
  )
}

function Chooser({ cost }: { cost: Cost }) {
  const [load, setLoad] = useState(false)
  const [toolsOnly, setToolsOnly] = useState(true)
  const [fitsOnly, setFitsOnly] = useState(true)
  const [search, setSearch] = useState('')
  const catalog = useOpenRouterCatalog(load)
  const { prompt_tokens, completion_tokens, max_context_tokens } = cost.totals
  const perMonth = 30 / daysCounted(cost)

  const rows = useMemo(() => {
    const term = search.trim().toLowerCase()
    return (catalog.data ?? [])
      .filter((m) => (!toolsOnly || m.tools) && (!fitsOnly || m.context_length >= max_context_tokens))
      .filter((m) => !term || m.id.toLowerCase().includes(term) || m.name.toLowerCase().includes(term))
      .map((m) => ({ m, cost: estimate(m, prompt_tokens, completion_tokens) }))
      .sort((a, b) => a.cost - b.cost)
      .slice(0, 40)
  }, [catalog.data, toolsOnly, fitsOnly, search, prompt_tokens, completion_tokens, max_context_tokens])

  return (
    <section className="flex flex-col gap-3">
      <h2 className="text-sm font-semibold">Choosing a model</h2>
      <p className="text-xs text-fg-muted">
        Prices below are what the tokens counted above would cost on each OpenRouter model (list price, no
        discounts), and the same figure scaled to 30 days at the rate seen so far. A model must be able to call tools
        (agents work only through tool calls) and its context window must be larger than the biggest single call
        ({n(max_context_tokens)} tokens). For Ollama there is no per-token price: pick a model that does tool
        calls well, and set its context size (<span className="font-mono">num_ctx</span>) above that same number, or
        Ollama silently cuts the start of the conversation off.
      </p>
      {!load ? (
        <div>
          <button
            type="button"
            className="rounded-control border border-line bg-surface px-3 py-1.5 text-sm font-medium hover:bg-fg-subtle/10"
            onClick={() => setLoad(true)}
          >
            Compare with OpenRouter models
          </button>
          <span className="ml-3 text-xs text-fg-muted">Fetches OpenRouter's public model list.</span>
        </div>
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-4 text-sm">
            <input
              className="rounded-control border border-line bg-surface px-2 py-1 text-sm"
              placeholder="Filter models"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
            <label className="flex items-center gap-2">
              <input type="checkbox" checked={toolsOnly} onChange={(e) => setToolsOnly(e.target.checked)} />
              Tool calling only
            </label>
            <label className="flex items-center gap-2">
              <input type="checkbox" checked={fitsOnly} onChange={(e) => setFitsOnly(e.target.checked)} />
              Context fits the largest call
            </label>
          </div>
          {catalog.isPending && <p className="text-sm text-fg-muted">Loading the model list...</p>}
          {catalog.isError && <p className="text-sm text-red-600">{catalog.error.message}</p>}
          {catalog.data && (
            <Table>
              <thead>
                <tr className="border-b border-line">
                  <th className={`${head} text-left`}>Model</th>
                  <th className={head}>Context</th>
                  <th className={head}>$/M in</th>
                  <th className={head}>$/M out</th>
                  <th className={head}>Cost of the counted tokens</th>
                  <th className={head}>Per 30 days</th>
                </tr>
              </thead>
              <tbody>
                {rows.map(({ m, cost: c }) => (
                  <tr key={m.id} className="border-b border-line last:border-0">
                    <td className="px-3 py-2 font-mono text-xs">{m.id}</td>
                    <td className={cell}>{n(m.context_length)}</td>
                    <td className={cell}>{m.usd_per_million_in.toFixed(2)}</td>
                    <td className={cell}>{m.usd_per_million_out.toFixed(2)}</td>
                    <td className={cell}>{c === 0 ? 'free' : usd(c)}</td>
                    <td className={cell}>{c === 0 ? 'free' : usd(c * perMonth)}</td>
                  </tr>
                ))}
                {rows.length === 0 && (
                  <tr>
                    <td className="px-3 py-3 text-sm text-fg-muted" colSpan={6}>
                      No model matches these filters.
                    </td>
                  </tr>
                )}
              </tbody>
            </Table>
          )}
        </>
      )}
    </section>
  )
}

export function CostPanel() {
  const { data: cost, isPending, error } = useCost()
  const reset = useResetCost()
  const catalog = useOpenRouterCatalog(false)
  if (isPending) return <p className="mt-6 text-sm text-fg-muted">Loading...</p>
  if (error) return <p className="mt-6 text-sm text-red-600">{error.message}</p>

  const { totals } = cost
  const prices = new Map((catalog.data ?? []).map((m) => [m.id, m]))
  const perDay = totals.total_tokens / daysCounted(cost)

  return (
    <div className="mt-6 flex flex-col gap-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-fg-muted">
          Every model call is counted: all agents and the chat assistant, on Ollama or OpenRouter.{' '}
          {cost.since
            ? `Counting since the reset on ${new Date(cost.since).toLocaleString()}.`
            : cost.first_day
              ? `Counting since ${cost.first_day}.`
              : 'Nothing has been counted yet.'}
        </p>
        <button
          type="button"
          disabled={reset.isPending}
          className="rounded-control border border-line bg-surface px-3 py-1.5 text-sm font-medium hover:bg-fg-subtle/10 disabled:opacity-50"
          onClick={() => {
            if (window.confirm('Reset all token counters to zero? Run history keeps its own token counts.')) reset.mutate()
          }}
        >
          Reset counters
        </button>
      </div>

      <div className="grid grid-cols-2 gap-4 md:grid-cols-5">
        <StatTile label="Total tokens" value={n(totals.total_tokens)} />
        <StatTile label="Tokens in" value={n(totals.prompt_tokens)} />
        <StatTile label="Tokens out" value={n(totals.completion_tokens)} />
        <StatTile label="Model calls" value={n(totals.calls)} />
        <StatTile label="Largest context" value={n(totals.max_context_tokens)} />
      </div>
      <p className="-mt-3 text-xs text-fg-muted">
        Largest context is the biggest single call (prompt plus reply). About {n(Math.round(perDay))} tokens per day at
        the rate so far.
        {totals.calls_without_usage > 0 &&
          ` ${n(totals.calls_without_usage)} call(s) came back without token counts and add nothing to the sums.`}
      </p>

      <section className="flex flex-col gap-2">
        <h2 className="text-sm font-semibold">By agent</h2>
        <Table>
          <thead>
            <tr className="border-b border-line">
              <th className={`${head} text-left`}>Agent</th>
              <th className={`${head} text-left`}>Model</th>
              <th className={head}>Calls</th>
              <th className={head}>In</th>
              <th className={head}>Out</th>
              <th className={head}>Total</th>
              <th className={head}>Share</th>
              <th className={head}>Avg in / call</th>
              <th className={head}>Largest context</th>
            </tr>
          </thead>
          <tbody>
            {cost.by_agent.map((a) => (
              <tr key={`${a.source}:${a.agent}`} className="border-b border-line last:border-0">
                <td className="px-3 py-2">{agentName(a.source, a.agent)}</td>
                <td className="px-3 py-2 font-mono text-xs">{a.models.join(', ')}</td>
                <td className={cell}>{n(a.calls)}</td>
                <td className={cell}>{n(a.prompt_tokens)}</td>
                <td className={cell}>{n(a.completion_tokens)}</td>
                <td className={cell}>{n(a.total_tokens)}</td>
                <td className={cell}>
                  {totals.total_tokens ? `${Math.round((a.total_tokens / totals.total_tokens) * 100)}%` : '-'}
                </td>
                <td className={cell}>{a.calls ? n(Math.round(a.prompt_tokens / a.calls)) : '-'}</td>
                <td className={cell}>{n(a.max_context_tokens)}</td>
              </tr>
            ))}
            {cost.by_agent.length === 0 && (
              <tr>
                <td className="px-3 py-3 text-sm text-fg-muted" colSpan={9}>
                  No model calls counted yet. Start a run or send a chat message.
                </td>
              </tr>
            )}
          </tbody>
        </Table>
      </section>

      <section className="flex flex-col gap-2">
        <h2 className="text-sm font-semibold">By model</h2>
        <Table>
          <thead>
            <tr className="border-b border-line">
              <th className={`${head} text-left`}>Provider</th>
              <th className={`${head} text-left`}>Model</th>
              <th className={head}>Calls</th>
              <th className={head}>In</th>
              <th className={head}>Out</th>
              <th className={head}>Largest context</th>
              <th className={head}>Cost</th>
            </tr>
          </thead>
          <tbody>
            {cost.by_model.map((m) => {
              const price = prices.get(m.model)
              return (
                <tr key={`${m.provider}:${m.model}`} className="border-b border-line last:border-0">
                  <td className="px-3 py-2">{m.provider}</td>
                  <td className="px-3 py-2 font-mono text-xs">{m.model}</td>
                  <td className={cell}>{n(m.calls)}</td>
                  <td className={cell}>{n(m.prompt_tokens)}</td>
                  <td className={cell}>{n(m.completion_tokens)}</td>
                  <td className={cell}>{n(m.max_context_tokens)}</td>
                  <td className={cell}>
                    {m.provider === 'ollama'
                      ? 'local'
                      : price
                        ? usd(estimate(price, m.prompt_tokens, m.completion_tokens))
                        : 'compare below'}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </Table>
      </section>

      {cost.by_day.length > 0 && (
        <section className="flex flex-col gap-2">
          <h2 className="text-sm font-semibold">By day</h2>
          <Table>
            <thead>
              <tr className="border-b border-line">
                <th className={`${head} text-left`}>Day (UTC)</th>
                <th className={head}>Calls</th>
                <th className={head}>In</th>
                <th className={head}>Out</th>
              </tr>
            </thead>
            <tbody>
              {[...cost.by_day].reverse().slice(0, 14).map((d) => (
                <tr key={d.day} className="border-b border-line last:border-0">
                  <td className="px-3 py-2 font-mono text-xs">{d.day}</td>
                  <td className={cell}>{n(d.calls)}</td>
                  <td className={cell}>{n(d.prompt_tokens)}</td>
                  <td className={cell}>{n(d.completion_tokens)}</td>
                </tr>
              ))}
            </tbody>
          </Table>
        </section>
      )}

      <Chooser cost={cost} />
    </div>
  )
}
