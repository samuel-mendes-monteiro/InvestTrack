import { useState } from 'react'
import { useImport, usePreviewImport } from '../api/queries'
import { domainMessage } from '../api/errors'
import { Modal } from '../components/Modal'
import { Metric } from '../components/Metric'
import { brDate, brl, quantity } from '../format'
import { IMPORT_STATUS, OP_TYPES, SKIP_REASONS } from '../labels'

/**
 * Import B3's trade statement in two steps: choosing the file asks the API
 * for a preview (nothing saved), and only the button saves the new trades.
 */
export function ImportDialog({ onClose }: { onClose: () => void }) {
  const [file, setFile] = useState<File | null>(null)
  const preview = usePreviewImport()
  const save = useImport()

  function choose(chosen: File | null) {
    setFile(chosen)
    save.reset()
    if (chosen) preview.mutate(chosen)
    else preview.reset()
  }

  const result = save.data ?? preview.data // after importing, rows say IMPORTED
  const imported = save.data?.rows.filter((r) => r.status === 'IMPORTED').length

  return (
    <Modal title="Importar extrato da B3" onClose={onClose}>
      <div className="stack">
        <p className="muted">
          Na Área do Investidor da B3 (investidor.b3.com.br), abra Extratos → Negociação, escolha o período e exporte em
          Excel. Operações já registradas são reconhecidas e não se repetem. O extrato não traz as taxas: as operações
          entram com taxa zero, e você pode editá-las depois.
        </p>
        <label>
          Extrato de Negociação (.xlsx)
          <input
            type="file"
            accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            onChange={(e) => choose(e.target.files?.[0] ?? null)}
          />
        </label>

        {preview.isPending && <p className="muted">Lendo o extrato…</p>}
        {(preview.error ?? save.error) && (
          <p className="alert error" role="alert">
            {(preview.error ?? save.error)!.message}
          </p>
        )}
        {imported != null && (
          <p className="alert success" role="status">
            {imported} {imported === 1 ? 'operação importada' : 'operações importadas'}.
          </p>
        )}

        {result && (
          <>
            <div className="metrics">
              <Metric label="Novas" value={String(result.new)} />
              <Metric label="Já registradas" value={String(result.duplicates)} />
              <Metric label="Recusadas" value={String(result.rejected)} />
              <Metric label="Ignoradas" value={String(result.skipped)} />
            </div>

            {result.rows.length > 0 && (
              <div className="table-wrap scroll-y">
                <table className="data" aria-label="Linhas do extrato">
                  <thead>
                    <tr>
                      <th className="num">Linha</th>
                      <th>Situação</th>
                      <th>Data</th>
                      <th>Tipo</th>
                      <th>Ticker</th>
                      <th className="num">Qtd</th>
                      <th className="num">Preço</th>
                      <th>Motivo</th>
                    </tr>
                  </thead>
                  <tbody>
                    {result.rows.map((r) => (
                      <tr key={r.line} className={r.status === 'REJECTED' ? 'negative' : r.status === 'DUPLICATE' ? 'muted' : ''}>
                        <td className="num">{r.line}</td>
                        <td>{IMPORT_STATUS[r.status]}</td>
                        <td>{brDate(r.date)}</td>
                        <td>{OP_TYPES[r.op_type]}</td>
                        <td>{r.ticker}</td>
                        <td className="num">{quantity(r.quantity)}</td>
                        <td className="num">{brl(r.price)}</td>
                        <td className="wrap">{r.error ? domainMessage(r.error) : ''}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {result.skipped_rows.length > 0 && (
              <ul className="muted small">
                {result.skipped_rows.map((s) => (
                  <li key={s.line}>
                    Linha {s.line} ignorada: {SKIP_REASONS[s.reason]} · {s.detail}
                  </li>
                ))}
              </ul>
            )}

            {result.rejected > 0 && !save.data && (
              <p className="alert warning">
                As linhas recusadas venderiam mais do que você tem. Elas ficam de fora; registre antes as compras que
                faltam (por exemplo, com um extrato de um período mais antigo) e importe de novo.
              </p>
            )}
          </>
        )}

        <div className="actions">
          <button onClick={onClose}>{save.data ? 'Fechar' : 'Cancelar'}</button>
          {!save.data && (
            <button
              className="primary"
              disabled={!file || !preview.data || preview.data.new === 0 || save.isPending}
              onClick={() => file && save.mutate(file)}
            >
              {save.isPending ? 'Importando…' : `Importar ${preview.data?.new ?? 0} operações`}
            </button>
          )}
        </div>
      </div>
    </Modal>
  )
}
