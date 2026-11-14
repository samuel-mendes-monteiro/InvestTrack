import type { ReactNode } from 'react'

/** A headline number: label, value, and an optional line under it. */
export function Metric({
  label,
  value,
  detail,
  tone,
  help,
}: {
  label: string
  value: string
  detail?: ReactNode
  tone?: 'positive' | 'negative'
  help?: string
}) {
  return (
    <div className="metric" title={help}>
      <div className="metric-label">{label}</div>
      <div className="metric-value">{value}</div>
      {detail && <div className={`metric-detail ${tone ?? ''}`}>{detail}</div>}
    </div>
  )
}
