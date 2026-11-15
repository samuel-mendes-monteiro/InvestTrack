import type { ReactNode } from 'react'

/** A headline number: label, value, and an optional line under it. */
export function Metric({
  label,
  value,
  detail,
  tone,
  help,
  hero,
}: {
  label: string
  value: string
  detail?: ReactNode
  tone?: 'positive' | 'negative'
  help?: string
  /** The page's main number: bigger, and set apart from the rest. */
  hero?: boolean
}) {
  return (
    <div className={hero ? 'metric metric-hero' : 'metric'} title={help}>
      <div className="metric-label">{label}</div>
      <div className="metric-value">{value}</div>
      {detail && <div className={`metric-detail ${tone ?? ''}`}>{detail}</div>}
    </div>
  )
}
