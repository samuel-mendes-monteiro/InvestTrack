import { useState, type ReactNode } from 'react'
import { Link } from 'react-router'
import { BankIcon, ChartIcon, CoinsIcon, PlusIcon, UploadIcon, WalletIcon } from '../components/Icons'
import { ImportDialog } from '../operations/ImportDialog'
import { NewOperationDialog, type Kind } from '../operations/NewOperationDialog'

type Open = { dialog: 'import' } | { dialog: 'new'; kind: Kind } | null

const WAYS: {
  icon: ReactNode
  title: string
  text: string
  badge?: string
  /** A how-to under the card, for the way that needs steps outside the app. */
  guide?: { to: string; label: string }
  open: Exclude<Open, null>
}[] = [
  {
    icon: <UploadIcon />,
    title: 'Importar o extrato da B3',
    text: 'Traga todas as compras e vendas de uma vez, pelo Excel de negociação da Área do Investidor.',
    badge: 'Mais rápido',
    guide: { to: '/ajuda/importar-b3', label: 'Como importar o histórico da B3' },
    open: { dialog: 'import' },
  },
  {
    icon: <PlusIcon />,
    title: 'Registrar uma compra',
    text: 'Ações, FIIs, ETFs e BDRs, uma por vez. O preço do dia é preenchido sozinho.',
    open: { dialog: 'new', kind: 'stock' },
  },
  {
    icon: <BankIcon />,
    title: 'Adicionar renda fixa',
    text: 'CDB, LCI e LCA a % do CDI, prefixados ou IPCA+, com IOF e IR calculados.',
    open: { dialog: 'new', kind: 'fixed-income' },
  },
]

const NEXT: { icon: ReactNode; text: string }[] = [
  { icon: <WalletIcon />, text: 'Patrimônio, preço médio e resultado de cada ativo, com a cotação atual' },
  { icon: <ChartIcon />, text: 'Rentabilidade da carteira lado a lado com o CDI e o Ibovespa' },
  { icon: <CoinsIcon />, text: 'Dividendos, JCP e rendimentos calculados a partir do que a B3 publica' },
]

/**
 * The Carteira of a brand-new account: instead of an empty page, the ways to
 * put the first investment in, each opening its own dialog right here.
 */
export function Welcome() {
  const [open, setOpen] = useState<Open>(null)
  const close = () => setOpen(null)

  return (
    <div className="welcome">
      <section className="card welcome-hero">
        <h1>Bem-vindo ao InvestTrack</h1>
        <p className="lead">Sua carteira ainda está vazia. Escolha como começar:</p>
      </section>

      <div className="welcome-ways">
        {WAYS.map((w) => (
          // The guide link sits under the card, not inside it: a link can't go inside a button.
          <div key={w.title} className="welcome-way-wrap">
            <button className="card welcome-way" onClick={() => setOpen(w.open)}>
              <span className="feature-icon">{w.icon}</span>
              {w.badge && <span className="chip positive welcome-badge">{w.badge}</span>}
              <strong>{w.title}</strong>
              <span className="muted">{w.text}</span>
            </button>
            {w.guide && (
              <Link className="welcome-guide" to={w.guide.to}>
                {w.guide.label} →
              </Link>
            )}
          </div>
        ))}
      </div>

      <section className="welcome-next" aria-labelledby="welcome-next-title">
        <h2 id="welcome-next-title">Depois do primeiro registro, você vê aqui</h2>
        <ul>
          {NEXT.map((n) => (
            <li key={n.text}>
              <span className="welcome-next-icon">{n.icon}</span>
              {n.text}
            </li>
          ))}
        </ul>
      </section>

      {open?.dialog === 'import' && <ImportDialog onClose={close} />}
      {open?.dialog === 'new' && <NewOperationDialog initialKind={open.kind} onClose={close} />}
    </div>
  )
}
