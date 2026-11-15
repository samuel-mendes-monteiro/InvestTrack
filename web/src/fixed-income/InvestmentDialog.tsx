import { useState, type FormEvent } from 'react'
import {
  useAddPartialRedemption,
  useDeleteFixedIncome,
  useDeletePartialRedemption,
  useRedeem,
  type FixedIncome,
} from '../api/queries'
import { Modal } from '../components/Modal'
import { brDate, brl, decimalField, sumDecimals, todayIso } from '../format'
import { FI_STATUS } from '../labels'
import { rateLabel } from './rate'

/**
 * Everything done to one investment: partial and total redemptions, and
 * deleting it. Reads `investment` from the list, so after each change the
 * refetched list re-renders this dialog with the new numbers.
 */
export function InvestmentDialog({ investment: f, onClose }: { investment: FixedIncome; onClose: () => void }) {
  const today = todayIso()
  const [partialDate, setPartialDate] = useState(today)
  const [gross, setGross] = useState('')
  const [redeemDate, setRedeemDate] = useState(today)
  const [invalid, setInvalid] = useState<string | null>(null)
  const addPartial = useAddPartialRedemption()
  const deletePartial = useDeletePartialRedemption()
  const redeem = useRedeem()
  const remove = useDeleteFixedIncome()

  const mutations = [addPartial, deletePartial, redeem, remove]
  const busy = mutations.some((m) => m.isPending)
  const error = invalid ?? mutations.find((m) => m.isError)?.error?.message ?? null
  const active = f.status === 'ACTIVE'

  function reset() {
    setInvalid(null)
    mutations.forEach((m) => m.reset()) // one error at a time: the last action's
  }

  function submitPartial(event: FormEvent) {
    event.preventDefault()
    reset()
    let value: string
    try {
      value = decimalField('Valor resgatado', gross)
    } catch (e) {
      setInvalid((e as Error).message)
      return
    }
    addPartial.mutate({ id: f.id, date: partialDate, gross: value }, { onSuccess: () => setGross('') })
  }

  function deleteInvestment() {
    reset()
    if (window.confirm(`Apagar a aplicação ${f.name}, com os resgates dela?`)) {
      remove.mutate(f.id, { onSuccess: onClose })
    }
  }

  return (
    <Modal title={`${f.name} · ${rateLabel(f)}`} onClose={onClose}>
      <div className="stack">
        <p className="muted">
          {f.product} aplicado em {brDate(f.start)}, vence em {brDate(f.maturity)} · {FI_STATUS[f.status]}
          {f.redeemed_on && ` em ${brDate(f.redeemed_on)}`}
        </p>

        {error && (
          <p className="alert error" role="alert">
            {error}
          </p>
        )}

        <section>
          <h3>Resgates parciais</h3>
          {f.partial_redemptions.length > 0 && (
            <table className="data" aria-label="Resgates parciais">
              <thead>
                <tr>
                  <th>Data</th>
                  <th className="num">Bruto</th>
                  <th className="num">IOF + IR</th>
                  <th className="num">Líquido</th>
                  <th>
                    <span className="sr-only">Ações</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {f.partial_redemptions.map((p) => (
                  <tr key={p.id}>
                    <td>{brDate(p.date)}</td>
                    <td className="num">{brl(p.gross)}</td>
                    <td className="num">{p.ir == null || p.iof == null ? '—' : brl(sumDecimals([p.iof, p.ir]))}</td>
                    <td className="num">{brl(p.net)}</td>
                    <td>
                      <div className="row-actions">
                        <button
                          disabled={busy}
                          aria-label={`Apagar resgate parcial de ${brDate(p.date)}`}
                          onClick={() => {
                            reset()
                            deletePartial.mutate({ id: f.id, redemptionId: p.id })
                          }}
                        >
                          Apagar
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {active && (
            <form onSubmit={submitPartial} className="inline-form">
              <label>
                Data
                <input type="date" required min={f.start} max={today} value={partialDate} onChange={(e) => setPartialDate(e.target.value)} />
              </label>
              <label>
                Valor resgatado, bruto (R$)
                <input inputMode="decimal" value={gross} onChange={(e) => setGross(e.target.value)} placeholder="1.000,00" />
              </label>
              <button type="submit" className="primary" disabled={busy}>
                Resgatar parte
              </button>
            </form>
          )}
          <small>
            Valor antes do IR e do IOF, como aparece no extrato do banco. O restante continua rendendo; cada resgate paga
            IR só sobre a parte do rendimento que ele levou.
          </small>
        </section>

        <section>
          <h3>Resgate total</h3>
          {f.redeemed_on ? (
            <button
              disabled={busy}
              onClick={() => {
                reset()
                redeem.mutate({ id: f.id, day: null })
              }}
            >
              Desfazer o resgate de {brDate(f.redeemed_on)}
            </button>
          ) : (
            <form
              className="inline-form"
              onSubmit={(e) => {
                e.preventDefault()
                reset()
                redeem.mutate({ id: f.id, day: redeemDate })
              }}
            >
              <label>
                Data do resgate
                <input type="date" required min={f.start} max={today} value={redeemDate} onChange={(e) => setRedeemDate(e.target.value)} />
              </label>
              <button type="submit" disabled={busy}>
                Resgatar tudo
              </button>
            </form>
          )}
        </section>

        <div className="actions">
          <button className="push-left danger" onClick={deleteInvestment} disabled={busy}>
            Apagar aplicação
          </button>
          <button onClick={onClose}>Fechar</button>
        </div>
      </div>
    </Modal>
  )
}
