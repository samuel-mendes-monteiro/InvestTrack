import { useState, type ReactNode } from 'react'
import { Link } from 'react-router'
import { ImportDialog } from '../operations/ImportDialog'

const STEPS: { title: string; body: ReactNode }[] = [
  {
    title: 'Entre na Área do Investidor da B3',
    body: (
      <>
        Acesse <strong>investidor.b3.com.br</strong> e entre com seu CPF e senha. É o mesmo acesso para todas as suas
        corretoras: a B3 junta as operações de todas elas.
      </>
    ),
  },
  {
    title: 'Abra Extratos → Negociação',
    body: <>No menu, vá em Extratos e escolha a aba Negociação, que lista as compras e vendas da bolsa.</>,
  },
  {
    title: 'Escolha o período desde a sua primeira compra',
    body: (
      <>
        O preço médio depende de todo o histórico. Se faltar a compra de um ativo, a venda dele aparece como
        &quot;recusada&quot; na prévia, para não calcular um preço médio errado. Na dúvida, pegue o maior período que a B3
        oferecer.
      </>
    ),
  },
  {
    title: 'Baixe o extrato em Excel',
    body: (
      <>
        Use a opção de exportar ou baixar e escolha <strong>Excel (.xlsx)</strong>. O arquivo vai para a pasta de
        downloads do seu computador ou celular.
      </>
    ),
  },
  {
    title: 'Importe no InvestTrack',
    body: (
      <>
        Clique em <strong>Importar extrato agora</strong>, aqui embaixo, e escolha o arquivo. Antes de salvar, aparece uma
        prévia: <strong>novas</strong> entram, <strong>já registradas</strong> não se repetem, <strong>recusadas</strong>{' '}
        faltam compras anteriores, e <strong>ignoradas</strong> são opções, termo ou futuro, que o InvestTrack não
        acompanha. Confira e clique em Importar.
      </>
    ),
  },
]

const NOTES: ReactNode[] = [
  <>
    <strong>Taxas:</strong> o extrato da B3 não traz corretagem nem emolumentos. As operações entram com taxa zero; se quiser
    o preço médio com taxas, edite cada uma em Operações.
  </>,
  <>
    <strong>Pode importar de novo:</strong> o que já foi importado é reconhecido. Dá para baixar um extrato novo todo mês e
    importar só por cima.
  </>,
  <>
    <strong>Renda fixa</strong> não está nesse extrato: registre CDB, LCI e LCA em Nova operação → Renda fixa.
  </>,
  <>
    <strong>Proventos</strong> não precisam de extrato: dividendos, JCP e rendimentos são calculados sozinhos a partir das
    suas posições.
  </>,
]

/** Step by step: getting the trade statement out of B3's site and into the app. */
export function ImportGuidePage() {
  const [importing, setImporting] = useState(false)

  return (
    <div className="page guide">
      <p className="guide-back">
        <Link to="/">← Voltar para a Carteira</Link>
      </p>

      <section className="card welcome-hero">
        <h1>Como importar seu histórico da B3</h1>
        <p className="lead">
          Todas as suas compras e vendas de ações, FIIs e ETFs, de todas as corretoras, entram de uma vez.
        </p>
      </section>

      <ol className="guide-steps">
        {STEPS.map((s, i) => (
          <li key={s.title} className="card">
            <span className="step-number">{i + 1}</span>
            <div>
              <h2>{s.title}</h2>
              <p className="muted">{s.body}</p>
            </div>
          </li>
        ))}
      </ol>

      <div className="guide-cta">
        <button className="primary" onClick={() => setImporting(true)}>
          Importar extrato agora
        </button>
      </div>

      <section className="card" aria-labelledby="guide-notes-title">
        <h2 id="guide-notes-title">Bom saber</h2>
        <ul className="guide-notes">
          {NOTES.map((n, i) => (
            <li key={i}>{n}</li>
          ))}
        </ul>
      </section>

      {importing && <ImportDialog onClose={() => setImporting(false)} />}
    </div>
  )
}
