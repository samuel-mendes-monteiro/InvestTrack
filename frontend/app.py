"""InvestTrack web interface (Streamlit).

Run with:  streamlit run frontend/app.py
The API must be running (uvicorn investtrack.api:app). Its address comes
from the API_URL environment variable (default http://localhost:8000).

How Streamlit works: the whole script runs again from the top on every
click. Actions (create, delete) are done in callbacks, which run *before*
that rerun, so the page always shows data that includes the change.
"""

import os
from datetime import date, datetime
from decimal import Decimal

import pandas as pd
import plotly.express as px
import streamlit as st

from api_client import ApiClient, ApiError
from formatting import brl, parse_decimal, pct, per_share, quantity

API_URL = os.getenv("API_URL", "http://localhost:8000")
ASSET_TYPES = {"Ação": "STOCK", "FII": "FII", "ETF": "ETF", "BDR": "BDR"}
OP_TYPES = {"Compra": "BUY", "Venda": "SELL"}
OP_LABELS = {v: k for k, v in OP_TYPES.items()}
INCOME_TYPES = {"Dividendo": "DIVIDEND", "JCP": "JCP", "Rendimento (FII)": "DISTRIBUTION"}
INCOME_LABELS = {v: k for k, v in INCOME_TYPES.items()}
STOCK_EVENT_LABELS = {
    "SPLIT": "Desdobramento",
    "REVERSE_SPLIT": "Grupamento",
    "BONUS": "Bonificação",
}
MONTHS = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]

st.set_page_config(page_title="InvestTrack", page_icon="📈", layout="wide")
api = ApiClient(API_URL)


def local_time(iso: str) -> str:
    """'2026-11-14T13:44:43Z' -> '14/11 10:44' in the viewer's timezone."""
    return f"{datetime.fromisoformat(iso).astimezone():%d/%m %H:%M}"


def operation_label(o: dict) -> str:
    """'#3 · 10/03/2026 · Venda 50 PETR4 a R$ 50,00'"""
    day = date.fromisoformat(o["date"])
    action = f"{OP_LABELS[o['op_type']]} {quantity(o['quantity'])} {o['ticker']}"
    return f"#{o['id']} · {day:%d/%m/%Y} · {action} a {brl(o['price'])}"


def income_label(i: dict) -> str:
    """'#2 · 15/01/2026 · JCP ITSA4 de R$ 85,00 líquido'"""
    day = date.fromisoformat(i["date"])
    kind = INCOME_LABELS[i["income_type"]]
    return f"#{i['id']} · {day:%d/%m/%Y} · {kind} {i['ticker']} de {brl(i['net'])} líquido"


def income_table(items: list[dict]) -> pd.DataFrame:
    def day(iso):
        return date.fromisoformat(iso).strftime("%d/%m/%Y") if iso else "—"

    return pd.DataFrame(
        [
            {
                "Pagamento": day(i["date"]),
                "Tipo": INCOME_LABELS[i["income_type"]],
                "Ticker": i["ticker"],
                "Data com": day(i["record_date"]),
                "Qtd": quantity(i["quantity"]) if i["quantity"] is not None else "—",
                "Valor/ação": per_share(i["rate"]),
                "Bruto": brl(i["amount"]),
                "IR": brl(i["tax"]),
                "Líquido": brl(i["net"]),
                "Origem": "B3" if i["source"] == "B3" else "Manual",
            }
            for i in items
        ]
    )


# --- callbacks (run before the page is redrawn) ------------------------------


def flash(kind: str, message: str) -> None:
    st.session_state["flash"] = (kind, message)


def field_decimal(label: str, text: str):
    """Parse a form field, naming the field in the error message."""
    if not text.strip():
        raise ValueError(f"preencha o campo {label}")
    try:
        return parse_decimal(text)
    except ValueError:
        raise ValueError(f"{label} '{text}' não é um número válido") from None


def on_create() -> None:
    s = st.session_state
    try:
        if not s.f_ticker.strip():
            raise ValueError("informe o ticker")
        payload = {
            "ticker": s.f_ticker.strip().upper(),
            "op_type": OP_TYPES[s.f_op_type],
            "date": s.f_date.isoformat(),
            # Sent as strings so the values reach the API as exact decimals.
            "quantity": str(field_decimal("Quantidade", s.f_quantity)),
            "price": str(field_decimal("Preço", s.f_price)),
            "fees": str(field_decimal("Taxas", s.f_fees or "0")),
            "asset_type": ASSET_TYPES[s.f_asset_type],
        }
        api.create_operation(payload)
    except (ValueError, ApiError) as e:
        flash("error", f"Operação não registrada: {e}")
        return
    flash("success", f"{s.f_op_type} de {s.f_quantity} {payload['ticker']} registrada.")
    for key in ("f_ticker", "f_quantity", "f_price", "f_fees"):
        s[key] = ""


def on_delete(operation_id: int) -> None:
    try:
        api.delete_operation(operation_id)
    except ApiError as e:
        flash("error", f"Não foi possível apagar: {e}")
        return
    flash("success", f"Operação #{operation_id} apagada.")


def bonus_label(e: dict) -> str:
    """'PETR4 · 10% em 01/02/2026'"""
    day = date.fromisoformat(e["record_date"]).strftime("%d/%m/%Y")
    percent = quantity((Decimal(e["multiplier"]) - 1) * 100)
    return f"{e['ticker']} · {percent}% em {day}"


def on_set_bonus_cost(bonus: dict) -> None:
    s = st.session_state
    try:
        unit_cost = field_decimal("Custo atribuído", s.b_cost)
        api.set_bonus_cost(bonus["ticker"], bonus["record_date"], str(unit_cost))
    except (ValueError, ApiError) as e:
        flash("error", f"Custo não salvo: {e}")
        return
    flash("success", f"Custo atribuído de {bonus_label(bonus)} salvo.")
    s["b_cost"] = ""


def on_delete_bonus_cost(bonus: dict) -> None:
    try:
        api.delete_bonus_cost(bonus["ticker"], bonus["record_date"])
    except ApiError as e:
        flash("error", f"Não foi possível remover: {e}")
        return
    flash("success", f"Custo atribuído de {bonus_label(bonus)} removido.")


def on_create_income() -> None:
    s = st.session_state
    try:
        if not s.i_ticker:
            raise ValueError("escolha o ticker")
        payload = {
            "ticker": s.i_ticker,
            "income_type": INCOME_TYPES[s.i_type],
            "date": s.i_date.isoformat(),
            "amount": str(field_decimal("Valor bruto", s.i_amount)),
            "tax": str(field_decimal("IR retido", s.i_tax or "0")),
        }
        api.create_income(payload)
    except (ValueError, ApiError) as e:
        flash("error", f"Provento não registrado: {e}")
        return
    flash("success", f"{s.i_type} de {s.i_ticker} registrado.")
    for key in ("i_amount", "i_tax"):
        s[key] = ""


def on_delete_income(income_id: int) -> None:
    try:
        api.delete_income(income_id)
    except ApiError as e:
        flash("error", f"Não foi possível apagar: {e}")
        return
    flash("success", f"Provento #{income_id} apagado.")


# --- page --------------------------------------------------------------------

st.title("📈 InvestTrack")

if not api.is_up():
    st.error(f"A API não está respondendo em {API_URL}. Inicie com:")
    st.code("uvicorn investtrack.api:app --reload", language="bash")
    st.stop()

with st.sidebar:
    st.header("Nova operação")
    with st.form("new_operation"):
        st.radio("Tipo", list(OP_TYPES), key="f_op_type", horizontal=True)
        st.text_input("Ticker", key="f_ticker", placeholder="PETR4")
        st.selectbox(
            "Classe do ativo",
            list(ASSET_TYPES),
            key="f_asset_type",
            help="Usada só na primeira vez que o ticker aparece.",
        )
        st.date_input(
            "Data", key="f_date", value=date.today(), max_value=date.today(), format="DD/MM/YYYY"
        )
        st.text_input("Quantidade", key="f_quantity", placeholder="100")
        st.text_input("Preço unitário (R$)", key="f_price", placeholder="30,50")
        st.text_input("Taxas (R$)", key="f_fees", placeholder="0,00")
        st.form_submit_button("Registrar", type="primary", on_click=on_create, width="stretch")

if "flash" in st.session_state:
    kind, message = st.session_state.pop("flash")
    getattr(st, kind)(message)

try:
    portfolio = api.portfolio()
    operations = api.operations()
    incomes = api.incomes()
except ApiError as e:
    st.error(str(e))
    st.stop()

totals = portfolio["totals"]
# The API sends numbers as strings ("0"), so compare as Decimal, not with 0.
open_positions = [p for p in portfolio["positions"] if Decimal(p["quantity"]) != 0]

# A segmented control with a key keeps the chosen view across reruns
# (st.tabs would jump back to the first tab after every interaction).
view = st.segmented_control(
    "Visão",
    ["Carteira", "Operações", "Proventos"],
    key="view",
    default="Carteira",
    label_visibility="collapsed",
)

# --- portfolio view ----------------------------------------------------------

if view not in ("Operações", "Proventos"):
    if not portfolio["positions"]:
        st.info("Nenhuma operação ainda. Registre a primeira compra na barra lateral.")
    else:
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Patrimônio", brl(totals["current_value"]))
        c2.metric("Investido", brl(totals["invested"]))
        c3.metric(
            "Resultado",
            brl(totals["result"]),
            delta=pct(totals["result_pct"]) if totals["result_pct"] is not None else None,
        )
        c4.metric(
            "Lucro realizado",
            brl(totals["realized_profit"]),
            help="Lucro ou prejuízo de vendas já feitas, inclusive de posições encerradas.",
        )
        pending_total = Decimal(totals["income_pending"])
        c5.metric(
            "Proventos",
            brl(totals["income"]),
            delta=f"{brl(pending_total)} a receber" if pending_total else None,
            delta_color="off",
            help="Dividendos, JCP e rendimentos já recebidos, descontado o IR retido.",
        )

        missing = [p["ticker"] for p in open_positions if p["current_price"] is None]
        if missing:
            st.warning(f"Sem cotação para {', '.join(missing)}: os totais ficam incompletos.")
        stale = [p for p in open_positions if p["price_stale"]]
        if stale:
            when = ", ".join(f"{p['ticker']} ({local_time(p['price_as_of'])})" for p in stale)
            st.warning(f"Fonte de cotações indisponível. Usando o último preço conhecido: {when}.")

        st.subheader("Posições")
        table = pd.DataFrame(
            [
                {
                    "Ticker": p["ticker"],
                    "Qtd": quantity(p["quantity"]),
                    "Preço médio": brl(p["avg_price"]),
                    "Cotação": brl(p["current_price"]),
                    "Investido": brl(p["invested"]),
                    "Valor atual": brl(p["current_value"]),
                    "Resultado": f"{brl(p['result'])} ({pct(p['result_pct'])})"
                    if p["result"] is not None
                    else "—",
                    "Proventos": brl(p["income"]),
                }
                for p in open_positions
            ]
        )
        st.dataframe(table, hide_index=True, width="stretch")

        st.subheader("Distribuição")
        col_chart, _ = st.columns([1, 1])  # half width: a pie doesn't need more
        with col_chart:
            valued = [p for p in open_positions if p["current_value"] is not None]
            if valued:
                chart_data = pd.DataFrame(
                    {
                        "Ticker": [p["ticker"] for p in valued],
                        # float only for drawing: no calculation depends on it
                        "Valor": [float(p["current_value"]) for p in valued],
                    }
                )
                fig = px.pie(chart_data, names="Ticker", values="Valor", hole=0.45)
                fig.update_traces(
                    textinfo="label+percent",
                    textposition="inside",
                    insidetextorientation="horizontal",
                    hovertemplate="%{label}: R$ %{value:,.2f}<extra></extra>",
                )
                fig.update_layout(showlegend=False, height=320, margin=dict(t=10, b=10, l=10, r=10))
                st.plotly_chart(fig, width="stretch")
            else:
                st.caption("Sem cotações para montar o gráfico.")

# --- operations view ---------------------------------------------------------

elif view == "Operações":
    if not operations:
        st.info("Nenhuma operação registrada.")
    else:
        tickers = sorted({o["ticker"] for o in operations})
        chosen = st.selectbox("Filtrar por ticker", ["Todos", *tickers])
        shown = [o for o in operations if chosen == "Todos" or o["ticker"] == chosen]

        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "#": o["id"],
                        "Data": date.fromisoformat(o["date"]).strftime("%d/%m/%Y"),
                        "Tipo": OP_LABELS[o["op_type"]],
                        "Ticker": o["ticker"],
                        "Qtd": quantity(o["quantity"]),
                        "Preço": brl(o["price"]),
                        "Taxas": brl(o["fees"]),
                    }
                    for o in shown
                ]
            ),
            hide_index=True,
            width="stretch",
        )

        applied = api.stock_events()
        if applied:
            st.subheader("Desdobramentos e bonificações")
            st.caption(
                "Aplicados automaticamente a partir dos eventos da B3, no fim da data com. "
                "Frações de ação são vendidas pela B3 em leilão e não aparecem aqui."
            )
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "Data com": date.fromisoformat(e["record_date"]).strftime("%d/%m/%Y"),
                            "Evento": STOCK_EVENT_LABELS[e["event_type"]],
                            "Ticker": e["ticker"],
                            "Antes": quantity(e["quantity_before"]),
                            "Depois": quantity(e["quantity_after"]),
                            "Custo atribuído": (
                                "não informado"
                                if e["unit_cost"] is None
                                else per_share(e["unit_cost"])
                            )
                            if e["event_type"] == "BONUS"
                            else "",
                        }
                        for e in applied
                    ]
                ),
                hide_index=True,
                width="stretch",
            )
            bonuses = [e for e in applied if e["event_type"] == "BONUS"]
            if any(e["unit_cost"] is None for e in bonuses):
                st.warning(
                    "Há bonificação sem custo atribuído: as ações novas entraram com custo "
                    "zero, o que deixa o preço médio abaixo do valor para o IR. Informe o "
                    "custo abaixo."
                )
            if bonuses:
                with st.expander("Custo atribuído das bonificações"):
                    st.caption(
                        "O valor por ação está no aviso aos acionistas da empresa e no informe "
                        "de rendimentos da corretora. A B3 não publica esse dado."
                    )
                    labels = {bonus_label(e): e for e in bonuses}
                    chosen = st.selectbox("Bonificação", list(labels), key="b_event")
                    bonus = labels[chosen]
                    st.text_input("Custo atribuído por ação (R$)", key="b_cost", placeholder="7,82")
                    c1, c2, _ = st.columns([1, 1, 3])
                    c1.button("Salvar", type="primary", on_click=on_set_bonus_cost, args=(bonus,))
                    c2.button(
                        "Remover",
                        key="b_delete",
                        disabled=bonus["unit_cost"] is None,
                        on_click=on_delete_bonus_cost,
                        args=(bonus,),
                    )

        with st.expander("Apagar uma operação"):
            options = {operation_label(o): o["id"] for o in shown}
            # No default choice: deleting must always be a deliberate selection.
            label = st.selectbox(
                "Operação", list(options), index=None, placeholder="Escolha a operação a apagar"
            )
            st.button(
                "Apagar",
                type="secondary",
                disabled=label is None,
                on_click=on_delete,
                args=(options.get(label),),
            )
            st.caption(
                "A posição é recalculada automaticamente. Se apagar a operação "
                "deixar uma venda posterior sem ações, a API recusa."
            )

# --- income view -------------------------------------------------------------

else:
    received = [i for i in incomes if not i["pending"]]
    pending = [i for i in incomes if i["pending"]]
    st.caption(
        "Proventos de ações, FIIs e ETFs são calculados sozinhos: eventos publicados pela B3 × "
        "ações que você tinha no fim da data com. No JCP, desconta 15% de IR retido."
    )

    if pending:
        st.subheader(f"A receber · {brl(sum(Decimal(i['net']) for i in pending))}")
        st.dataframe(income_table(pending), hide_index=True, width="stretch")

    st.subheader("Recebidos")
    if not received:
        st.info("Nenhum provento recebido ainda.")
    else:
        years = sorted({int(i["date"][:4]) for i in received}, reverse=True)
        year = st.selectbox("Ano", years)
        months = api.monthly_income(year)
        shown = [i for i in received if i["date"].startswith(str(year))]
        # Summed from the full-precision items, not from the monthly totals: those
        # are already rounded, and adding rounded values drifts by cents.
        total = sum(Decimal(i["net"]) for i in shown)

        c1, c2, c3 = st.columns(3)
        c1.metric("Recebido no ano (líquido)", brl(total))
        c2.metric("IR retido no ano", brl(sum(Decimal(i["tax"]) for i in shown)))
        c3.metric("Média por mês com provento", brl(total / len(months) if months else 0))

        chart_rows = [
            {
                "Mês": f"{MONTHS[m['month'] - 1]}/{m['year'] % 100}",
                "Tipo": label,
                "Valor": float(m[key]),  # float only for drawing
            }
            for m in months
            for label, key in (
                ("Dividendo", "dividend"),
                ("JCP", "jcp"),
                ("Rendimento (FII)", "distribution"),
            )
            if Decimal(m[key])
        ]
        if chart_rows:
            fig = px.bar(pd.DataFrame(chart_rows), x="Mês", y="Valor", color="Tipo")
            fig.update_traces(hovertemplate="%{x}: R$ %{y:,.2f}<extra></extra>")
            fig.update_layout(
                height=320,
                margin=dict(t=10, b=10, l=10, r=10),
                yaxis_title=None,
                xaxis_title=None,
                legend_title=None,
            )
            st.plotly_chart(fig, width="stretch")

        st.dataframe(income_table(shown), hide_index=True, width="stretch")

    tickers = sorted({o["ticker"] for o in operations})
    with st.expander("Registrar provento manualmente"):
        st.caption(
            "Só para o que a B3 não publica, como BDRs ou proventos com mais de um ano. "
            "Um provento que já aparece acima seria contado duas vezes."
        )
        if not tickers:
            st.info("Registre uma compra antes: proventos são sempre de um ativo da carteira.")
        else:
            with st.form("new_income"):
                c1, c2, c3 = st.columns(3)
                c1.radio("Tipo", list(INCOME_TYPES), key="i_type")
                # A list instead of free text: a typo in the ticker is the most likely mistake.
                c2.selectbox("Ticker", tickers, key="i_ticker")
                c2.date_input(
                    "Data de pagamento",
                    key="i_date",
                    value=date.today(),
                    max_value=date.today(),
                    format="DD/MM/YYYY",
                )
                c3.text_input("Valor bruto (R$)", key="i_amount", placeholder="120,50")
                c3.text_input(
                    "IR retido (R$)",
                    key="i_tax",
                    placeholder="0,00",
                    help="Use o valor do extrato da corretora.",
                )
                st.form_submit_button(
                    "Registrar provento", type="primary", on_click=on_create_income
                )

    manual = [i for i in incomes if i["source"] == "MANUAL"]
    if manual:
        with st.expander("Apagar um provento manual"):
            options = {income_label(i): i["id"] for i in manual}
            label = st.selectbox(
                "Provento", list(options), index=None, placeholder="Escolha o provento a apagar"
            )
            st.button(
                "Apagar",
                key="delete_income",
                disabled=label is None,
                on_click=on_delete_income,
                args=(options.get(label),),
            )
            st.caption("Proventos da B3 não podem ser apagados: eles vêm das suas operações.")
