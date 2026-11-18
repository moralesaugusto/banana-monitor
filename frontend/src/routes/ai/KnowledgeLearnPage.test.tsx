import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { KnowledgeLearnPage } from './KnowledgeLearnPage'

describe('KnowledgeLearnPage', () => {
  it('explains the key concepts and lists a glossary', () => {
    render(<KnowledgeLearnPage />)

    expect(screen.getByText('Embedding')).toBeInTheDocument()
    expect(screen.getByText('Cosine similarity')).toBeInTheDocument()
    expect(screen.getByText('Dimensionality reduction (PCA)')).toBeInTheDocument()
    expect(screen.getByText('Vector')).toBeInTheDocument()
    expect(screen.getByText('Model drift')).toBeInTheDocument()
  })

  it("explains what nomic-embed-text is and that it isn't a mandated standard", () => {
    render(<KnowledgeLearnPage />)

    expect(screen.getByText('Which embedding model, and is it "the" standard?')).toBeInTheDocument()
    expect(screen.getByText(/nomic-embed-text/)).toBeInTheDocument()
    expect(screen.getByText('MTEB')).toBeInTheDocument()
  })

  it('walks through a concrete example using tajonaso', () => {
    render(<KnowledgeLearnPage />)

    expect(screen.getByRole('heading', { name: /tajonaso/ })).toBeInTheDocument()
    expect(screen.getByText('add_knowledge_entry')).toBeInTheDocument()
    expect(screen.getByText('search_knowledge')).toBeInTheDocument()
  })
})
