import { useState, type FormEvent } from 'react'
import {
  useAddPartialRedemption,
  useDeletePartialRedemption,
  useRedeem,
  type FixedIncome,
} from '../api/queries'
import { Modal } from '../components/Modal'
import { brDate, brl, decimalField, sumDecimals, todayIso } from '../format'
import { FI_STATUS } from '../labels'
import { rateLabel } from './rate'

/**
 * The money taken out of one investment, in one form: an amount is a partial
 * redemption; "Resgatar tudo" is the total one (deleting it is in the edit
 * form). Reads `investment` from the list, so after each change the
 * refetched list re-renders this dialog with the new numbers.
 */
export function InvestmentDialog({ investment: f, onClose }: { investment: FixedIncome; onClose: () => void }) {
  const today = todayIso()
  const [day, setDay] = useState(today)
  const [gross, setGross] = useState('')
  const [all, setAll] = useState(false)
  const [invalid, setInvalid] = useState<string | null>(null)
  const addPartial = useAddPartialRedemption()
  const deletePartial = useDeletePartialRedemption()
  const redeem = useRedeem()

  const mutations = [addPartial, deletePartial, redeem]
  const busy = mutations.some((m) => m.isPending)
  const error = invalid ?? mutations.find((m) => m.isError)?.error?.message ?? null
  const active = f.status === 'ACTIVE'

  function reset() {
    setInvalid(null)
    mutations.forEach((m) => m.reset()) // one error at a time: the last action's
  }

  function submit(event: FormEvent) {
    event.preventDefault()
    reset()
    // Everything is the total redemption, not a withdrawal of the whole value:
    // the API values it on that day itself, and the investment is then over.
    if (all) {
      redeem.mutate({ id: f.id, day })
      return
    }
    let value: string
    try {
      value = decimalField('Valor resgatado', gross)
    } catch (e) {
      setInvalid((e as Error).message)
      return
    }
    addPartial.mutate({ id: f.id, date: day, gross: value }, { onSuccess: () => setGross('') })
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

        {f.partial_redemptions.length > 0 && (
          <section>
            <h3>Resgates parciais</h3>
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
          </section>
        )}

        <section>
          <h3>Resgatar</h3>
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
          ) : active ? (
            <form onSubmit={submit} className="inline-form">
              <label>
                Data
                <input type="date" required min={f.start} max={today} value={day} onChange={(e) => setDay(e.target.value)} />
              </label>
              <label>
                Valor resgatado, bruto (R$)
                {/* With "tudo", the value as of the last CDI: the API computes the chosen day's own. */}
                <input
                  inputMode="decimal"
                  value={all ? (f.gross == null ? '' : brl(f.gross).replace('R$ ', '')) : gross}
                  onChange={(e) => setGross(e.target.value)}
                  placeholder={all ? 'Tudo' : '1.000,00'}
                  readOnly={all}
                />
              </label>
              <button type="submit" className="primary" disabled={busy}>
                Resgatar
              </button>
              <label className="check">
                <input type="checkbox" checked={all} onChange={(e) => setAll(e.target.checked)} />
                Resgatar tudo
              </label>
            </form>
          ) : null}
          {active && (
            <small>
              {all
                ? `Encerra a aplicação na data escolhida. O valor acima é o${f.as_of ? ` de ${brDate(f.as_of)}, último dia com CDI publicado` : ' mais recente'}; o do dia do resgate é calculado ao resgatar.`
                : 'Valor antes do IR e do IOF, como aparece no extrato do banco. O restante continua rendendo; cada resgate paga IR só sobre a parte do rendimento que ele levou.'}
            </small>
          )}
        </section>

        <div className="actions">
          <button onClick={onClose}>Fechar</button>
        </div>
      </div>
    </Modal>
  )
}
