import { Card } from '../../components/Card'
import { PageHeader } from '../../components/PageHeader'

const CONCEPTS = [
  {
    title: 'Embedding',
    body: 'A piece of text, turned into a list of numbers (a vector) by a model trained so that similar meanings land near each other. Two sentences that say the same thing in different words get nearly the same vector; unrelated sentences get very different ones.',
  },
  {
    title: 'Collection',
    body: 'A named group of entries, e.g. "LAN notes" or "Security knowledge". It keeps unrelated topics from being searched together, and lets you (or an agent) clear one topic without touching the others.',
  },
  {
    title: 'Cosine similarity',
    body: 'The standard way to compare two embeddings: it measures the angle between them, not their length. Identical direction scores 1, completely unrelated (perpendicular) scores 0. This is the actual arithmetic behind "search by meaning" - Qdrant computes it internally for every search here, the same formula a hand-written version would use.',
  },
  {
    title: 'Top-k',
    body: 'A search returns the k entries with the highest similarity score to your query, most similar first - not every entry, and not an exact-word match.',
  },
  {
    title: 'Chunking',
    body: 'A long document embedded as a single vector blurs together everything in it. So anything over about 500 characters is split on paragraph breaks into several smaller entries first, each embedded on its own - each one a sharper, more specific match.',
  },
  {
    title: 'Dimensionality reduction (PCA)',
    body: 'An embedding usually has hundreds of numbers - far too many to draw. PCA finds the two directions that capture the most spread in a set of vectors and projects every point onto just those two, for the Map page\'s scatter plot. It is a real, if lossy, shadow of the actual space: points close together were judged similar; exact distances matter less than rough clustering.',
  },
  {
    title: 'Which embedding model, and is it "the" standard?',
    body: 'nomic-embed-text (this app\'s default) is a real, widely used open-weight embedding model - it is not an industry-mandated standard, just a common, free default for a self-hosted Ollama setup, good at general text and small enough to run without a GPU. There is no single required embedding model; what actually is standard is the shape of the request this app sends to get one - an OpenAI-compatible POST /embeddings call (model + input in, a vector back) - which is why pointing this at a different host or model (OpenAI\'s text-embedding-3-small, BAAI/bge-base, or anything else that speaks that same shape) is a one-line settings change, not a code change. People compare embedding models on public benchmarks like MTEB (Massive Text Embedding Benchmark); a bigger model usually scores higher but costs more to run per call.',
  },
]

const GLOSSARY: [string, string][] = [
  ['Vector', 'An embedding\'s own name: a fixed-length list of numbers.'],
  ['Dimension', 'One number in that list. A typical embedding model uses several hundred.'],
  ['Model drift', 'What happens if the embedding model changes: old and new vectors are no longer comparable. Each entry remembers which model made its vector so a mismatch is visible, not silent.'],
  ['Qdrant', 'The embedded vector database this app stores vectors in - a Python library running in-process, not a separate server, unless you point it at one yourself.'],
  ['MTEB', 'Massive Text Embedding Benchmark: the public leaderboard most people actually use to compare embedding models against each other, across many languages and task types.'],
]

export function KnowledgeLearnPage() {
  return (
    <div>
      <PageHeader
        title="How the knowledge base works"
        description="The standards behind search_knowledge/add_knowledge_entry and the Map page: embeddings, similarity search, and the projection that turns a high-dimensional space into something you can look at."
      />

      <div className="mt-6 grid gap-4 md:grid-cols-3">
        {CONCEPTS.map((c) => (
          <Card key={c.title} className="p-4">
            <div className="text-sm font-semibold text-fg">{c.title}</div>
            <p className="mt-2 text-sm text-fg-muted">{c.body}</p>
          </Card>
        ))}
      </div>

      <h2 className="mt-8 text-lg font-semibold">A worked example: tajonaso</h2>
      <Card className="mt-3 p-4 text-sm text-fg-muted">
        <p>
          tajonaso, this app's offensive-security agent, finishes testing a host and wants to remember what
          it found for next time. If the knowledge base is on and tajonaso's own Tools list has it enabled,
          it can call <code className="text-fg">add_knowledge_entry</code> with the "Security knowledge"
          collection, a title, and the finding as content - the same text it would otherwise only put in a
          one-off report. That text gets embedded and stored as a vector, exactly like one you add by hand
          on the Browse page.
        </p>
        <p className="mt-2">
          Weeks later, tajonaso (or any agent with the tool enabled) investigates a different host and wants
          to check whether something similar has come up before. It calls{' '}
          <code className="text-fg">search_knowledge</code> with that same collection and a plain-language
          query describing what it is looking at - not keywords, the actual sentence - and gets back the
          most similar entries by meaning, ranked by score, even if the old note used completely different
          wording.
        </p>
      </Card>

      <h2 className="mt-8 text-lg font-semibold">Glossary</h2>
      <Card className="mt-3 overflow-hidden">
        <dl className="divide-y divide-line">
          {GLOSSARY.map(([term, body]) => (
            <div key={term} className="grid gap-1 p-3 sm:grid-cols-[10rem_1fr]">
              <dt className="text-sm font-medium text-fg">{term}</dt>
              <dd className="text-sm text-fg-muted">{body}</dd>
            </div>
          ))}
        </dl>
      </Card>
    </div>
  )
}
