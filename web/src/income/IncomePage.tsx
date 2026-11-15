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
  const pendingTotal = sumDecimals(pending.map((i) => i.net))
  const monthCount = months.data?.length ?? 0
  const tickers = [...new Set((operations.data ?? []).map((o) => o.ticker))].sort()

  function confirmDelete(i: Income) {
    const what = `${INCOME_TYPES[i.income_type]} de ${i.ticker} em ${brDate(i.date)}, ${brl(i.net)} líquido`
    if (i.id != null && window.confirm(`Apagar o provento #${i.id} (${what})?`)) remove.mutate(i.id)
  }

  const addButton = (
    <button onClick={() => setAdding(true)} disabled={!tickers.length}>
      Registrar provento manual
    </button>
  )

  return (
    <div className="page">
      {remove.isError && (
        <p className="alert error" role="alert">
          Não foi possível apagar: {remove.error.message}
        </p>
      )}

      {/* The same frame as the Carteira and Rentabilidade charts: the year's total big, the chart under it. */}
      <section className="card chart-card" aria-labelledby="income-title">
        <div className="card-head">
          <h2 id="income-title">Proventos recebidos</h2>
          {years.length > 0 && (
            <label className="inline year-select">
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
            <p className="chart-caption">
              <span className="chart-figure positive">{brl(total)}</span>
              <span className="muted">líquidos em {year}</span>
            </p>
            {months.data && months.data.length > 0 && <MonthlyChart months={months.data} />}
          </>
        )}
        <p className="chart-note">
          Proventos de ações, FIIs e ETFs são calculados sozinhos: eventos publicados pela B3 × ações que você tinha no fim
          da data com. No JCP, desconta 15% de IR retido.
        </p>
      </section>

      {received.length > 0 && (
        <div className="metrics">
          <Metric label="IR retido no ano" value={brl(sumDecimals(shown.map((i) => i.tax)))} />
          <Metric
            label="Média por mês com provento"
            value={monthCount ? brl(divideDecimal(total, monthCount)) : '—'}
          />
          <Metric
            label="A receber"
            value={brl(pendingTotal)}
            help="Proventos já anunciados pela B3 que ainda não foram pagos."
          />
        </div>
      )}

      {pending.length > 0 && (
        <section className="card" aria-labelledby="pending-title">
          <div className="card-head">
            <h2 id="pending-title">A receber</h2>
            <span className="muted">{brl(pendingTotal)}</span>
          </div>
          <IncomeTable label="A receber" items={pending} />
        </section>
      )}

      <section className="card" aria-labelledby="received-title">
        <div className="card-head">
          <h2 id="received-title">{year == null ? 'Recebidos' : `Recebidos em ${year}`}</h2>
          {addButton}
        </div>
        {shown.length > 0 ? (
          <IncomeTable label="Recebidos" items={shown} onDelete={confirmDelete} deleting={remove.isPending} />
        ) : (
          <p className="muted">Nada recebido nesse período.</p>
        )}
      </section>

      {adding && <IncomeForm tickers={tickers} onClose={() => setAdding(false)} />}
    </div>
  )
}
