/** The banana mark; same artwork as public/favicon.svg. Colors are fixed so it reads in both themes. */
export function BananaLogo({ className }: { className?: string }) {
  return (
    <svg className={className} width="28" height="28" viewBox="0 0 48 48" aria-hidden>
      <defs>
        <linearGradient id="banana-logo-body" x1="10" y1="34" x2="38" y2="10" gradientUnits="userSpaceOnUse">
          <stop offset="0" stopColor="#8a6700" />
          <stop offset="0.55" stopColor="#d4a000" />
          <stop offset="1" stopColor="#ffd666" />
        </linearGradient>
      </defs>
      <path
        d="M12 34c-1.5 3 1 6 4.5 5 9-2 17-8.5 20.5-18 1.3-3.6 1.4-7 .6-9.4-.4-1.2-1.9-1.4-2.6-.3-2.6 4-6.4 9-11 12.7-5 4-9.3 6-12 9.9z"
        fill="url(#banana-logo-body)"
        stroke="#6b4e00"
        strokeWidth="1.6"
        strokeLinejoin="round"
      />
      <path d="M34.5 12.2c1 .4 1.7 1.1 2.1 2.1" fill="none" stroke="#fff3cf" strokeWidth="1.8" strokeLinecap="round" opacity="0.6" />
      <path d="M35.5 9.2c1.4-.9 3-1 4.3-.2" fill="none" stroke="#6b4e00" strokeWidth="2.2" strokeLinecap="round" />
    </svg>
  )
}
