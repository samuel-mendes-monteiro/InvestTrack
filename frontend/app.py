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
from formatting import brl, parse_decimal, pct, quantity

API_URL = os.getenv("API_URL", "http://localhost:8000")
ASSET_TYPES = {"Ação": "STOCK", "FII": "FII", "ETF": "ETF", "BDR": "BDR"}
OP_TYPES = {"Compra": "BUY", "Venda": "SELL"}
OP_LABELS = {v: k for k, v in OP_TYPES.items()}

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
except ApiError as e:
    st.error(str(e))
    st.stop()

totals = portfolio["totals"]
# The API sends numbers as strings ("0"), so compare as Decimal, not with 0.
open_positions = [p for p in portfolio["positions"] if Decimal(p["quantity"]) != 0]

# A segmented control with a key keeps the chosen view across reruns
# (st.tabs would jump back to the first tab after every interaction).
view = st.segmented_control(
    "Visão", ["Carteira", "Operações"], key="view", default="Carteira", label_visibility="collapsed"
)

# --- portfolio view ----------------------------------------------------------

if view != "Operações":
    if not portfolio["positions"]:
        st.info("Nenhuma operação ainda. Registre a primeira compra na barra lateral.")
    else:
        c1, c2, c3, c4 = st.columns(4)
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

else:
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
