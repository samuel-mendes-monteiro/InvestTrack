import type { ReactNode } from 'react'
import { Link } from 'react-router'
import { BankIcon, ChartIcon, CoinsIcon, ListIcon, LogoMark, UploadIcon, WalletIcon } from '../components/Icons'

const FEATURES: { icon: ReactNode; title: string; text: string }[] = [
  {
    icon: <WalletIcon />,
    title: 'Carteira',
    text: 'Posição, preço médio com taxas e resultado de cada ativo, ajustados para desdobramentos, grupamentos e bonificações.',
  },
  {
    icon: <ChartIcon />,
    title: 'Rentabilidade',
    text: 'Retorno ponderado pelo tempo desde a primeira operação, lado a lado com o CDI e o Ibovespa.',
  },
  {
    icon: <CoinsIcon />,
    title: 'Proventos',
    text: 'Dividendos, JCP e rendimentos de FIIs calculados a partir do que a B3 publica, inclusive o que ainda vai cair.',
  },
  {
    icon: <BankIcon />,
    title: 'Renda fixa',
    text: 'CDB, LCI e LCA em % do CDI, prefixados ou IPCA+, com IOF e IR regressivo calculados todo dia.',
  },
  {
    icon: <UploadIcon />,
    title: 'Importação da B3',
    text: 'Traga as operações do extrato de negociação da B3 em Excel, com prévia e sem duplicar nada.',
  },
  {
    icon: <ListIcon />,
    title: 'Operações',
    text: 'O histórico de compras e vendas é a única fonte de verdade: corrigiu uma operação antiga, tudo se recalcula.',
  },
]

const STEPS = [
  { title: 'Crie sua conta', text: 'Só e-mail e senha. Cada pessoa vê apenas a própria carteira.' },
  { title: 'Registre ou importe', text: 'Lance as operações à mão ou importe o extrato da B3 de uma vez.' },
  { title: 'Acompanhe', text: 'Cotações, proventos e rentabilidade se atualizam sozinhos.' },
]

/** What a visitor sees before logging in: what InvestTrack is, and the way in. */
export function LandingPage() {
  return (
    <div className="landing">
      <header className="public-nav">
        <Link to="/" className="brand-link">
          <LogoMark />
          InvestTrack
        </Link>
        <nav aria-label="Seções">
          <a href="#recursos">Recursos</a>
          <a href="#como-funciona">Como funciona</a>
        </nav>
        <span className="spacer" />
        <Link to="/entrar" className="button">
          Entrar
        </Link>
        <Link to="/criar-conta" className="button primary">
          Criar conta
        </Link>
      </header>

      <main>
        <section className="hero">
          <div className="hero-text">
            <p className="eyebrow">Ações, FIIs, ETFs e renda fixa da B3</p>
            <h1>Todos os seus investimentos numa carteira só.</h1>
            <p className="lead">
              Registre suas operações de qualquer corretora e veja patrimônio, preço médio, proventos e rentabilidade
              calculados com exatidão, centavo por centavo.
            </p>
            <div className="hero-actions">
              <Link to="/criar-conta" className="button primary large">
                Começar agora
              </Link>
              <Link to="/entrar" className="button large">
                Já tenho conta
              </Link>
            </div>
          </div>
          <HeroPreview />
        </section>

        <section id="recursos" className="landing-section" aria-labelledby="recursos-title">
          <h2 id="recursos-title">Tudo o que a planilha não faz direito</h2>
          <div className="feature-grid">
            {FEATURES.map((f) => (
              <article key={f.title} className="card feature">
                <span className="feature-icon">{f.icon}</span>
                <h3>{f.title}</h3>
                <p className="muted">{f.text}</p>
              </article>
            ))}
          </div>
        </section>

        <section id="como-funciona" className="landing-section" aria-labelledby="como-funciona-title">
          <h2 id="como-funciona-title">Como funciona</h2>
          <ol className="steps">
            {STEPS.map((s, i) => (
              <li key={s.title} className="card">
                <span className="step-number">{i + 1}</span>
                <h3>{s.title}</h3>
                <p className="muted">{s.text}</p>
              </li>
            ))}
          </ol>
        </section>

        <section className="card cta">
          <h2>Pronto para ver sua carteira inteira?</h2>
          <Link to="/criar-conta" className="button primary large">
            Criar conta
          </Link>
        </section>
      </main>

      <footer className="landing-footer muted">InvestTrack · projeto de código aberto, licença MIT</footer>
    </div>
  )
}

/**
 * A drawing of the Carteira screen, made of the app's own card styles. The
 * numbers are made up, so it's hidden from screen readers and marked as an example.
 */
function HeroPreview() {
  return (
    <div className="hero-preview" aria-hidden="true">
      <div className="metric metric-hero">
        <div className="metric-label">Patrimônio</div>
        <div className="metric-value">R$ 48.215,30</div>
        <div className="metric-detail">
          <span className="chip positive">+12,4%</span> desde o início
        </div>
      </div>
      <div className="preview-rows card">
        {[
          ['PETR4', 'R$ 12.480,00', '+18,2%', 'positive'],
          ['HGLG11', 'R$ 8.920,50', '-2,1%', 'negative'],
          ['IVVB11', 'R$ 7.310,00', '+9,7%', 'positive'],
        ].map(([ticker, value, change, tone]) => (
          <div key={ticker} className="preview-row">
            <strong>{ticker}</strong>
            <span>{value}</span>
            <span className={`chip ${tone}`}>{change}</span>
          </div>
        ))}
      </div>
      <span className="preview-note">Exemplo ilustrativo</span>
    </div>
  )
}
