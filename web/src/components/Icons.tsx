import type { ReactNode } from 'react'

// Small line icons drawn inline, so they take the text color (and the dark
// theme) for free and need no icon library. Decorative: the text next to them
// is what screen readers read.
function Icon({ children }: { children: ReactNode }) {
  return (
    <svg
      className="icon"
      viewBox="0 0 24 24"
      width="20"
      height="20"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {children}
    </svg>
  )
}

export const WalletIcon = () => (
  <Icon>
    <path d="M4 7h14a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a1 1 0 0 1-1-1V7Z" />
    <path d="M4 7V6a2 2 0 0 1 2-2h10v3" />
    <circle cx="16" cy="13.5" r="1" />
  </Icon>
)

export const BarsIcon = () => (
  <Icon>
    <path d="M4 20h16" />
    <path d="M7 16v-4M12 16V8M17 16V5" />
  </Icon>
)

export const ChartIcon = () => (
  <Icon>
    <path d="M4 4v16h16" />
    <path d="m7 15 4-4 3 3 5-6" />
  </Icon>
)

export const ListIcon = () => (
  <Icon>
    <path d="M7 7h13M7 12h13M7 17h13" />
    <path d="M3.5 7h.01M3.5 12h.01M3.5 17h.01" />
  </Icon>
)

export const CoinsIcon = () => (
  <Icon>
    <ellipse cx="9" cy="7" rx="5" ry="2.5" />
    <path d="M4 7v4c0 1.4 2.2 2.5 5 2.5s5-1.1 5-2.5V7" />
    <path d="M10 16.4c.9 1.2 3 2.1 5.5 2.1 2.8 0 5-1.1 5-2.5v-4c0-1.2-1.6-2.2-3.8-2.5" />
  </Icon>
)

export const BankIcon = () => (
  <Icon>
    <path d="m3 9 9-5 9 5" />
    <path d="M5 10v7M10 10v7M14 10v7M19 10v7" />
    <path d="M3 20h18" />
  </Icon>
)

export const UploadIcon = () => (
  <Icon>
    <path d="M12 15V4m0 0-4 4m4-4 4 4" />
    <path d="M4 15v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3" />
  </Icon>
)

export const PlusIcon = () => (
  <Icon>
    <path d="M12 5v14M5 12h14" />
  </Icon>
)

export const LogoMark = () => (
  <svg className="logo-mark" viewBox="0 0 24 24" width="24" height="24" aria-hidden="true">
    <rect width="24" height="24" rx="6" fill="var(--accent)" />
    <path d="m6 15 4-4 3 3 5-6" fill="none" stroke="#fff" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
)
