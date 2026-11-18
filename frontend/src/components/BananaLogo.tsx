/** The brand mark: three linked nodes, standing for the devices and services being watched.
 * Monochrome (currentColor) so it follows the theme. */
export function BananaLogo({ className, size = 28 }: { className?: string; size?: number }) {
  return (
    <svg className={className} width={size} height={size} viewBox="0 0 48 48" aria-hidden>
      <g stroke="currentColor" strokeWidth="1.6" strokeLinecap="round">
        <line x1="24" y1="14" x2="14" y2="32" />
        <line x1="24" y1="14" x2="34" y2="32" />
        <line x1="14" y1="32" x2="34" y2="32" strokeOpacity="0.5" />
      </g>
      <circle cx="14" cy="32" r="6" fill="currentColor" />
      <circle cx="34" cy="32" r="6" fill="currentColor" />
      <circle cx="24" cy="14" r="6" fill="var(--surface)" stroke="currentColor" strokeWidth="2" />
    </svg>
  )
}
