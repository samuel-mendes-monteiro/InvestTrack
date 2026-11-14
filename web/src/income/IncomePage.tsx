import { useState } from 'react'
import { useDeleteIncome, useIncomes, useMonthlyIncome, useOperations, type Income } from '../api/queries'
import { Metric } from '../components/Metric'
import { brDate, brl, divideDecimal, sumDecimals } from '../format'
import { INCOME_TYPES } from '../labels'
import { IncomeForm } from './IncomeForm'
import { IncomeTable } from './IncomeTable'
import { MonthlyChart } from './MonthlyChart'

export function IncomePage() {
  const incomes = useIncomes()
  const operations = useOperations()
  const remove = useDeleteIncome()
  const [chosenYear, setChosenYear] = useState<number | null>(null)
  const [adding, setAdding] = useState(false)

  const all = incomes.data ?? []
  const received = all.filter((i) => !i.pending)
  const pending = all.filter((i) => i.pending)
  const years = [...new Set(received.map((i) => Number(i.date.slice(0, 4))))].sort((a, b) => b - a)
  const year = chosenYear ?? years[0] ?? null // newest year until the user picks one
  const months = useMonthlyIncome(year) // hooks run on every render, so before any early return

  if (incomes.isPending) return <p className="muted">Carregando proventos…</p>
  if (incomes.isError) return <p className="alert error">{incomes.error.message}</p>

  const shown = received.filter((i) => year != null && i.date.startsWith(String(year)))
  // Summed from the full-precision items, not from the monthly totals: those
  // are already rounded, and adding rounded values drifts by cents.
  const total = sumDecimals(shown.map((i) => i.net))
  const monthCount = months.data?.length ?? 0
  const tickers = [...new Set((operations.data ?? []).map((o) => o.ticker))].sort()

  function confirmDelete(i: Income) {
    const what = `${INCOME_TYPES[i.income_type]} de ${i.ticker} em ${brDate(i.date)}, ${brl(i.net)} líquido`
    if (i.id != null && window.confirm(`Apagar o provento #${i.id} (${what})?`)) remove.mutate(i.id)
  }

  return (
    <>
      <div className="page-head">
        <p className="muted">
          Proventos de ações, FIIs e ETFs são calculados sozinhos: eventos publicados pela B3 × ações que você tinha no
          fim da data com. No JCP, desconta 15% de IR retido.
        </p>
        <button onClick={() => setAdding(true)} disabled={!tickers.length}>
          Registrar provento manual
        </button>
      </div>
      {remove.isError && (
        <p className="alert error" role="alert">
          Não foi possível apagar: {remove.error.message}
        </p>
      )}

      {pending.length > 0 && (
        <>
          <h2>A receber · {brl(sumDecimals(pending.map((i) => i.net)))}</h2>
          <IncomeTable label="A receber" items={pending} />
        </>
      )}

      <div className="section-head">
        <h2>Recebidos</h2>
        {years.length > 0 && (
          <label className="inline">
            Ano
            <select value={year ?? ''} onChange={(e) => setChosenYear(Number(e.target.value))}>
              {years.map((y) => (
                <option key={y}>{y}</option>
              ))}
            </select>
          </label>
        )}
      </div>

      {!received.length ? (
        <p className="muted">Nenhum provento recebido ainda.</p>
      ) : (
        <>
          <div className="metrics">
            <Metric label="Recebido no ano (líquido)" value={brl(total)} />
            <Metric label="IR retido no ano" value={brl(sumDecimals(shown.map((i) => i.tax)))} />
            <Metric
              label="Média por mês com provento"
              value={monthCount ? brl(divideDecimal(total, monthCount)) : '—'}
            />
          </div>
          {months.data && months.data.length > 0 && <MonthlyChart months={months.data} />}
          <IncomeTable label="Recebidos" items={shown} onDelete={confirmDelete} deleting={remove.isPending} />
        </>
      )}

      {adding && <IncomeForm tickers={tickers} onClose={() => setAdding(false)} />}
    </>
  )
}
