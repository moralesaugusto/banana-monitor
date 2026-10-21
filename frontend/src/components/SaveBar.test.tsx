import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { SaveBar } from './SaveBar'

describe('SaveBar', () => {
  it('is the first thing in the form, with Save last in the bar (top right) and submits the form', async () => {
    const onSubmit = vi.fn((e: React.FormEvent) => e.preventDefault())
    render(
      <form aria-label="settings" onSubmit={onSubmit}>
        <SaveBar title="Things" saving={false} onCancel={() => {}} />
        <input aria-label="field" />
      </form>,
    )
    const form = screen.getByRole('form', { name: 'settings' })
    const buttons = Array.from(form.querySelectorAll('button'))
    expect(buttons.map((b) => b.textContent)).toEqual(['Cancel', 'Save'])
    // Both buttons come before any field in document order, and the group is pushed to the right.
    expect(form.querySelector('input')!.compareDocumentPosition(buttons[1]) & Node.DOCUMENT_POSITION_PRECEDING).toBeTruthy()
    expect(buttons[1].parentElement!.className).toContain('ml-auto')

    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    expect(onSubmit).toHaveBeenCalledOnce()
  })

  it('shows progress, errors and the saved confirmation', () => {
    const { rerender } = render(<SaveBar saving saved={false} />)
    expect(screen.getByRole('status')).toHaveTextContent('Saving…')
    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled()
    rerender(<SaveBar saving={false} error="Nope" />)
    expect(screen.getByRole('status')).toHaveTextContent('Nope')
    rerender(<SaveBar saving={false} saved />)
    expect(screen.getByRole('status')).toHaveTextContent('Saved.')
  })
})
