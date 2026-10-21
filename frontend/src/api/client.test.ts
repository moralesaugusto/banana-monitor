import { describe, expect, it } from 'vitest'
import { extractDetail } from './client'

describe('extractDetail', () => {
  it('extracts a plain string detail (a plugin/route raising HTTPException)', () => {
    expect(extractDetail('{"detail": "A Proxmox API token id is required"}')).toBe(
      'A Proxmox API token id is required',
    )
  })

  it('joins a list of pydantic validation errors (FastAPI\'s own request-validation 422)', () => {
    const body = JSON.stringify({
      detail: [
        { loc: ['body', 'name'], msg: 'Field required', type: 'missing' },
        { loc: ['body', 'config'], msg: 'Input should be a valid dictionary', type: 'dict_type' },
      ],
    })
    expect(extractDetail(body)).toBe('Field required; Input should be a valid dictionary')
  })

  it('falls back to the raw text for a non-JSON body', () => {
    expect(extractDetail('Internal Server Error')).toBe('Internal Server Error')
  })

  it('falls back to the raw text when detail is missing or not a recognized shape', () => {
    expect(extractDetail('{"ok": true}')).toBe('{"ok": true}')
  })
})

describe('extractDetail validator prefix', () => {
  it('drops pydantic\'s "Value error, " prefix', () => {
    const body = '{"detail": [{"msg": "Value error, 10.0.0.0/99 is not a network"}]}'
    expect(extractDetail(body)).toBe('10.0.0.0/99 is not a network')
  })
})
