import { render } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { HealthGauge } from './HealthGauge'

describe('HealthGauge', () => {
  it.each([
    [90, 'health-gauge-green'],
    [60, 'health-gauge-amber'],
    [20, 'health-gauge-red'],
  ])('score %i draws its arc as a gradient, not a flat color', (score, gradientId) => {
    const { container } = render(<HealthGauge score={score} />)

    expect(container.querySelector(`linearGradient#${gradientId}`)).toBeInTheDocument()
    expect(container.querySelector(`linearGradient#${gradientId} stop`)).toBeInTheDocument()
    expect(container.querySelector(`path[stroke="url(#${gradientId})"]`)).toBeInTheDocument()
  })
})
