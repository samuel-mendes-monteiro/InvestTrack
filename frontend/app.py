"""InvestTrack web interface (Streamlit).

Run with:  streamlit run frontend/app.py
The API must be running (uvicorn investtrack.api:app). Its address comes
from the API_URL environment variable (default http://localhost:8000).

How Streamlit works: the whole script runs again from the top on every
click. Actions (create, delete) are done in callbacks, which run *before*
that rerun, so the page always shows data that includes the change.
"""

import os
from datetime import date, datetime, timedelta
from decimal import Decimal

import pandas as pd
import plotly.express as px
import streamlit as st

from api_client import ApiClient, ApiError, NotLoggedInError, domain_error
from formatting import brl, parse_decimal, pct, per_share, quantity

API_URL = os.getenv("API_URL", "http://localhost:8000")
ASSET_TYPES = {"Ação": "STOCK", "FII": "FII", "ETF": "ETF", "BDR": "BDR"}
OP_TYPES = {"Compra": "BUY", "Venda": "SELL"}
OP_LABELS = {v: k for k, v in OP_TYPES.items()}
INCOME_TYPES = {"Dividendo": "DIVIDEND", "JCP": "JCP", "Rendimento (FII)": "DISTRIBUTION"}
INCOME_LABELS = {v: k for k, v in INCOME_TYPES.items()}
IMPORT_STATUS = {
    "NEW": "Nova",
    "DUPLICATE": "Já registrada",
    "REJECTED": "Recusada",
    "IMPORTED": "Importada",
}
SKIP_REASONS = {
    "UNSUPPORTED_MARKET": "mercado não suportado (opções, termo, futuro...)",
    "UNKNOWN_TYPE": "não é compra nem venda",
    "UNREADABLE_ROW": "linha ilegível",
}
FI_PRODUCTS = ["CDB", "LCI", "LCA"]
FI_INDEXERS = {"% do CDI": "CDI", "Prefixado": "PRE", "IPCA+": "IPCA"}
FI_STATUS = {"ACTIVE": "Aplicado", "REDEEMED": "Resgatado", "MATURED": "Vencido"}
STOCK_EVENT_LABELS = {
    "SPLIT": "Desdobramento",
    "REVERSE_SPLIT": "Grupamento",
    "BONUS": "Bonificação",
}
MONTHS = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]

st.set_page_config(page_title="InvestTrack", page_icon="📈", layout="wide")
# The session token lives in this browser tab's session state: closing or
# reloading the tab logs out. The API keeps only the token's hash.
api = ApiClient(API_URL, token=st.session_state.get("token"))


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


def on_login() -> None:
    s = st.session_state
    try:
        s["token"] = ApiClient(API_URL).login(s.l_email, s.l_password)
    except ApiError as e:
        flash("error", str(e))
    s["l_password"] = ""  # never keep the password around


def on_register() -> None:
    s = st.session_state
    try:
        if s.r_password != s.r_password2:
            raise ApiError("As senhas não são iguais.")
        client = ApiClient(API_URL)
        client.register(s.r_email, s.r_password)
        s["token"] = client.login(s.r_email, s.r_password)
    except ApiError as e:
        flash("error", str(e))
    s["r_password"] = s["r_password2"] = ""


def on_logout() -> None:
    try:
        api.logout()
    except ApiError:
        pass  # logging out locally is what matters
    st.session_state.pop("token", None)


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


def on_update(operation_id: int) -> None:
    # The fields' keys end with the id: choosing another operation creates new
    # widgets, prefilled with its values, instead of keeping the old ones' text.
    s = st.session_state

    def field(name: str):
        return s[f"e_{name}_{operation_id}"]

    try:
        if not field("ticker").strip():
            raise ValueError("informe o ticker")
        payload = {
            "ticker": field("ticker").strip().upper(),
            "op_type": OP_TYPES[field("op_type")],
            "date": field("date").isoformat(),
            "quantity": str(field_decimal("Quantidade", field("quantity"))),
            "price": str(field_decimal("Preço", field("price"))),
            "fees": str(field_decimal("Taxas", field("fees") or "0")),
            "asset_type": ASSET_TYPES[field("asset_type")],
        }
        api.update_operation(operation_id, payload)
    except (ValueError, ApiError) as e:
        flash("error", f"Operação não alterada: {e}")
        return
    flash("success", f"Operação #{operation_id} alterada.")


def edit_operation_form(o: dict) -> None:
    key = o["id"]
    with st.form(f"edit_operation_{key}"):
        st.radio(
            "Tipo",
            list(OP_TYPES),
            index=list(OP_TYPES.values()).index(o["op_type"]),
            key=f"e_op_type_{key}",
            horizontal=True,
        )
        c1, c2 = st.columns(2)
        c1.text_input("Ticker", value=o["ticker"], key=f"e_ticker_{key}")
        c2.selectbox(
            "Classe do ativo",
            list(ASSET_TYPES),
            key=f"e_asset_type_{key}",
            help="Usada só se o ticker mudar para um que ainda não existe.",
        )
        c1.date_input(
            "Data",
            value=date.fromisoformat(o["date"]),
            max_value=date.today(),
            format="DD/MM/YYYY",
            key=f"e_date_{key}",
        )
        c2.text_input("Quantidade", value=quantity(o["quantity"]), key=f"e_quantity_{key}")
        c1.text_input("Preço unitário (R$)", value=quantity(o["price"]), key=f"e_price_{key}")
        c2.text_input("Taxas (R$)", value=quantity(o["fees"]), key=f"e_fees_{key}")
        st.form_submit_button("Salvar alterações", type="primary", on_click=on_update, args=(key,))


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


def fi_rate(f: dict) -> str:
    """'110% do CDI', '12,5% a.a.' or 'IPCA + 6,5% a.a.'"""
    rate = quantity(f["rate"])
    match f["indexer"]:
        case "CDI":
            return f"{rate}% do CDI"
        case "IPCA":
            return f"IPCA + {rate}% a.a."
        case _:
            return f"{rate}% a.a."


def fi_label(f: dict) -> str:
    return f"#{f['id']} · {f['name']} · {fi_rate(f)} · {brl(f['amount'])}"


def on_create_fixed_income() -> None:
    s = st.session_state
    try:
        if not s.fi_name.strip():
            raise ValueError("informe o nome")
        payload = {
            "name": s.fi_name.strip(),
            "product": s.fi_product,
            "indexer": FI_INDEXERS[s.fi_indexer],
            "rate": str(field_decimal("Taxa", s.fi_rate)),
            "start": s.fi_start.isoformat(),
            "maturity": s.fi_maturity.isoformat(),
            "amount": str(field_decimal("Valor aplicado", s.fi_amount)),
        }
        api.create_fixed_income(payload)
    except (ValueError, ApiError) as e:
        flash("error", f"Aplicação não registrada: {e}")
        return
    flash("success", f"{payload['name']} registrado.")
    for key in ("fi_name", "fi_rate", "fi_amount"):
        s[key] = ""


def on_redeem(investment_id: int, day: date | None) -> None:
    try:
        api.redeem_fixed_income(investment_id, day.isoformat() if day else None)
    except ApiError as e:
        flash("error", f"Resgate não registrado: {e}")
        return
    flash("success", "Resgate registrado." if day else "Resgate desfeito.")


def on_partial_redemption(investment_id: int) -> None:
    s = st.session_state
    try:
        gross = field_decimal("Valor resgatado", s.fi_partial_gross)
        api.add_partial_redemption(investment_id, s.fi_partial_date.isoformat(), str(gross))
    except (ValueError, ApiError) as e:
        flash("error", f"Resgate parcial não registrado: {e}")
        return
    flash("success", f"Resgate parcial de {brl(gross)} registrado.")
    s.fi_partial_gross = ""


def on_delete_partial_redemption(investment_id: int, redemption_id: int) -> None:
    try:
        api.delete_partial_redemption(investment_id, redemption_id)
    except ApiError as e:
        flash("error", f"Não foi possível apagar: {e}")
        return
    flash("success", "Resgate parcial apagado.")


def on_delete_fixed_income(investment_id: int) -> None:
    try:
        api.delete_fixed_income(investment_id)
    except ApiError as e:
        flash("error", f"Não foi possível apagar: {e}")
        return
    flash("success", f"Aplicação #{investment_id} apagada.")


def on_import(data: bytes) -> None:
    try:
        result = api.import_b3(data)
    except ApiError as e:
        flash("error", f"Importação não feita: {e}")
        return
    imported = sum(1 for r in result["rows"] if r["status"] == "IMPORTED")
    flash("success", f"{imported} operações importadas.")
    st.session_state["upload_key"] = st.session_state.get("upload_key", 0) + 1  # clears the file


def import_section() -> None:
    with st.expander("Importar extrato da B3", expanded=not operations):
        st.caption(
            "Na Área do Investidor da B3 (investidor.b3.com.br), abra Extratos → Negociação, "
            "escolha o período e exporte em Excel. Operações já registradas são reconhecidas "
            "e não se repetem. O extrato não traz as taxas: as operações entram com taxa zero."
        )
        upload = st.file_uploader(
            "Extrato de Negociação (.xlsx)",
            type=["xlsx"],
            key=f"statement_{st.session_state.get('upload_key', 0)}",
        )
        if upload is None:
            return
        data = upload.getvalue()
        try:
            preview = api.preview_b3_import(data)
        except ApiError as e:
            st.error(str(e))
            return

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Novas", preview["new"])
        c2.metric("Já registradas", preview["duplicates"])
        c3.metric("Recusadas", preview["rejected"])
        c4.metric("Ignoradas", preview["skipped"])
        if preview["rows"]:
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "Linha": r["line"],
                            "Situação": IMPORT_STATUS[r["status"]],
                            "Data": date.fromisoformat(r["date"]).strftime("%d/%m/%Y"),
                            "Tipo": OP_LABELS[r["op_type"]],
                            "Ticker": r["ticker"],
                            "Qtd": quantity(r["quantity"]),
                            "Preço": brl(r["price"]),
                            "Motivo": domain_error(r["error"]) if r["error"] else "",
                        }
                        for r in preview["rows"]
                    ]
                ),
                hide_index=True,
                width="stretch",
            )
        for s in preview["skipped_rows"]:
            st.caption(f"Linha {s['line']} ignorada: {SKIP_REASONS[s['reason']]} · {s['detail']}")
        if preview["rejected"]:
            st.warning(
                "As linhas recusadas venderiam mais do que você tem. Elas ficam de fora; "
                "registre antes as compras que faltam (por exemplo, com um extrato de um "
                "período mais antigo) e importe de novo."
            )
        st.button(
            f"Importar {preview['new']} operações",
            type="primary",
            disabled=preview["new"] == 0,
            on_click=on_import,
            args=(data,),
        )


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


def show_flash() -> None:
    if "flash" in st.session_state:
        kind, message = st.session_state.pop("flash")
        getattr(st, kind)(message)


def login_page() -> None:
    show_flash()
    _, center, _ = st.columns([1, 2, 1])
    with center:
        enter, create = st.tabs(["Entrar", "Criar conta"])
        with enter, st.form("login"):
            st.text_input("E-mail", key="l_email")
            st.text_input("Senha", key="l_password", type="password")
            st.form_submit_button("Entrar", type="primary", on_click=on_login, width="stretch")
        with create, st.form("register"):
            st.text_input("E-mail", key="r_email")
            st.text_input(
                "Senha", key="r_password", type="password", help="Mínimo de 8 caracteres."
            )
            st.text_input("Repita a senha", key="r_password2", type="password")
            st.form_submit_button(
                "Criar conta", type="primary", on_click=on_register, width="stretch"
            )
            st.caption("A primeira conta criada fica com os dados que já existiam antes do login.")


if "token" not in st.session_state:
    login_page()
    st.stop()

try:
    me = api.me()
except NotLoggedInError:
    st.session_state.pop("token", None)
    flash("warning", "Sua sessão expirou. Entre de novo.")
    st.rerun()

with st.sidebar:
    c1, c2 = st.columns([3, 1])
    c1.caption(f"Conectado como **{me['email']}**")
    c2.button("Sair", on_click=on_logout, key="logout")
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

show_flash()

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
    ["Carteira", "Rentabilidade", "Operações", "Proventos", "Renda fixa"],
    key="view",
    default="Carteira",
    label_visibility="collapsed",
)

# --- portfolio view ----------------------------------------------------------

if view not in ("Rentabilidade", "Operações", "Proventos", "Renda fixa"):
    fixed_total = Decimal(totals["fixed_income"])
    if not portfolio["positions"] and not fixed_total:
        st.info("Nenhuma operação ainda. Registre a primeira compra na barra lateral.")
    else:
        c1, c2, c3, c4, c5 = st.columns(5)
        net_worth = (
            None
            if totals["current_value"] is None
            else Decimal(totals["current_value"]) + fixed_total
        )
        c1.metric(
            "Patrimônio",
            brl(net_worth),
            help=f"Ações, FIIs e ETFs, mais {brl(fixed_total)} em renda fixa (valor líquido).",
        )
        c2.metric(
            "Investido em ações",
            brl(totals["invested"]),
            help="Custo das posições abertas de ações, FIIs e ETFs, sem a renda fixa.",
        )
        c3.metric(
            "Resultado em ações",
            brl(totals["result"]),
            delta=pct(totals["result_pct"]) if totals["result_pct"] is not None else None,
            help="Valor atual menos o custo das posições abertas, sem a renda fixa.",
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
            valued = [
                (p["ticker"], p["current_value"])
                for p in open_positions
                if p["current_value"] is not None
            ]
            if fixed_total:
                valued.append(("Renda fixa", fixed_total))
            if valued:
                chart_data = pd.DataFrame(
                    {
                        "Ticker": [name for name, _ in valued],
                        # float only for drawing: no calculation depends on it
                        "Valor": [float(value) for _, value in valued],
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

# --- performance view --------------------------------------------------------

elif view == "Rentabilidade":
    try:
        perf = api.performance()
    except ApiError as e:
        st.error(str(e))
        st.stop()

    if perf["syncing"]:
        st.info(
            "Baixando o histórico de cotações da B3, do Ibovespa e do CDI. Na primeira vez "
            "leva cerca de um minuto; depois, só o dia novo. Atualize a página em instantes.",
            icon="⏳",
        )
        st.button("Atualizar", key="perf_refresh")
    if not perf["points"]:
        if not perf["syncing"]:
            st.info("Registre uma compra para ver a rentabilidade.")
    else:
        start, as_of = (date.fromisoformat(perf[k]) for k in ("start", "as_of"))
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Carteira", pct(perf["twr"]))
        c2.metric("CDI", pct(perf["cdi"]))
        c3.metric("Ibovespa", pct(perf["ibovespa"]))
        c4.metric(
            "% do CDI",
            f"{Decimal(perf['pct_of_cdi']):.0f}%" if perf["pct_of_cdi"] is not None else "—",
        )
        st.caption(
            f"De {start:%d/%m/%Y} a {as_of:%d/%m/%Y} (último fechamento oficial). "
            "Rentabilidade ponderada pelo tempo (TWR): aportes e vendas não distorcem o "
            "resultado, e os proventos contam como retorno."
        )

        series = {"Carteira": "twr", "CDI": "cdi", "Ibovespa": "ibovespa"}
        chart = pd.DataFrame(
            [
                {"Data": p["date"], "Série": label, "Rentabilidade": float(p[key])}
                for p in perf["points"]
                for label, key in series.items()
                if p[key] is not None  # float only for drawing
            ]
        )
        fig = px.line(chart, x="Data", y="Rentabilidade", color="Série")
        fig.update_traces(hovertemplate="%{x|%d/%m/%Y}: %{y:.2f}%<extra></extra>")
        fig.update_layout(
            height=380,
            margin=dict(t=10, b=10, l=10, r=10),
            yaxis_title=None,
            xaxis_title=None,
            legend_title=None,
            yaxis_ticksuffix="%",
        )
        st.plotly_chart(fig, width="stretch")

# --- operations view ---------------------------------------------------------

elif view == "Operações":
    import_section()
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

        with st.expander("Editar uma operação"):
            st.caption(
                "Útil para incluir as taxas das operações importadas da B3, que vêm "
                "sem taxas. A API recusa a alteração se ela deixar uma venda sem ações."
            )
            editable = {operation_label(o): o for o in shown}
            label = st.selectbox(
                "Operação",
                list(editable),
                index=None,
                placeholder="Escolha a operação a editar",
                key="e_choice",
            )
            if label is not None:
                edit_operation_form(editable[label])

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

# --- fixed income view -------------------------------------------------------

elif view == "Renda fixa":
    try:
        investments = api.fixed_income()
    except ApiError as e:
        st.error(str(e))
        st.stop()

    with st.expander("Nova aplicação", expanded=not investments):
        with st.form("new_fixed_income"):
            c1, c2, c3 = st.columns(3)
            c1.text_input("Nome", key="fi_name", placeholder="CDB Banco X")
            c1.selectbox("Produto", FI_PRODUCTS, key="fi_product")
            c2.radio("Indexador", list(FI_INDEXERS), key="fi_indexer", horizontal=True)
            c2.text_input(
                "Taxa (%)",
                key="fi_rate",
                placeholder="110",
                help=(
                    "% do CDI (ex.: 110), taxa ao ano se prefixado (ex.: 12,5), "
                    "ou taxa ao ano acima da inflação se IPCA+ (ex.: 6,5)."
                ),
            )
            c3.date_input(
                "Data da aplicação",
                key="fi_start",
                value=date.today(),
                max_value=date.today(),
                format="DD/MM/YYYY",
            )
            c3.date_input(
                "Vencimento",
                key="fi_maturity",
                value=date.today() + timedelta(days=365),
                format="DD/MM/YYYY",
            )
            c1.text_input("Valor aplicado (R$)", key="fi_amount", placeholder="5.000,00")
            st.form_submit_button("Registrar", type="primary", on_click=on_create_fixed_income)

    if not investments:
        st.info("Nenhuma aplicação de renda fixa registrada.")
    else:
        active = [f for f in investments if f["status"] == "ACTIVE"]
        if any(f["estimated"] for f in active):
            st.caption(
                "IPCA+: o IPCA do mês só sai por volta do dia 10 do mês seguinte. Até lá, "
                "o valor usa o último IPCA publicado e é uma estimativa."
            )
        if any(f["as_of"] is None for f in investments):
            st.info("Aguardando o histórico do CDI. Atualize a página em instantes.", icon="⏳")

        def total(key):
            return sum(Decimal(f[key]) for f in active if f[key] is not None)

        c1, c2, c3 = st.columns(3)
        c1.metric(
            "Aplicado",
            brl(total("principal")),
            help="Dinheiro aplicado que continua investido, descontados os resgates parciais.",
        )
        c2.metric("Valor bruto", brl(total("gross")))
        c3.metric(
            "Valor líquido",
            brl(total("net")),
            help="Se resgatasse hoje: já descontados IOF e IR. LCI e LCA são isentas.",
        )

        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "#": f["id"],
                        "Nome": f["name"],
                        "Produto": f["product"],
                        "Taxa": fi_rate(f),
                        "Aplicação": date.fromisoformat(f["start"]).strftime("%d/%m/%Y"),
                        "Vencimento": date.fromisoformat(f["maturity"]).strftime("%d/%m/%Y"),
                        "Aplicado": brl(f["amount"]),
                        "Resgates parciais": brl(
                            sum(Decimal(p["gross"]) for p in f["partial_redemptions"])
                        )
                        if f["partial_redemptions"]
                        else "",
                        "Bruto": brl(f["gross"]),
                        "IOF + IR": brl(
                            Decimal(f["iof"]) + Decimal(f["ir"]) if f["ir"] is not None else None
                        ),
                        "Líquido": brl(f["net"]),
                        "Rent. bruta": pct(f["gross_return"]),
                        "Situação": FI_STATUS[f["status"]],
                    }
                    for f in investments
                ]
            ),
            hide_index=True,
            width="stretch",
        )
        st.caption(
            "Valores do último dia útil com CDI publicado. O IR é regressivo pelo tempo "
            "aplicado (22,5% até 180 dias, 20% até 360, 17,5% até 720 e 15% depois), e o IOF "
            "incide em resgates com menos de 30 dias."
        )

        with st.expander("Resgatar ou apagar"):
            options = {fi_label(f): f for f in investments}
            chosen = options[st.selectbox("Aplicação", list(options), key="fi_chosen")]
            day = st.date_input(
                "Data do resgate",
                key="fi_redeem_date",
                value=date.today(),
                max_value=date.today(),
                format="DD/MM/YYYY",
            )
            c1, c2, c3, _ = st.columns([1, 1, 1, 2])
            c1.button("Resgatar", type="primary", on_click=on_redeem, args=(chosen["id"], day))
            c2.button(
                "Desfazer resgate",
                disabled=chosen["redeemed_on"] is None,
                on_click=on_redeem,
                args=(chosen["id"], None),
            )
            c3.button(
                "Apagar",
                key="fi_delete",
                on_click=on_delete_fixed_income,
                args=(chosen["id"],),
            )
            st.caption(
                "Aqui o resgate é do valor total. Para tirar só uma parte, use o resgate parcial."
            )

        if active:
            with st.expander("Resgate parcial"):
                options = {fi_label(f): f for f in active}
                chosen = options[st.selectbox("Aplicação", list(options), key="fi_partial_of")]
                c1, c2 = st.columns(2)
                c1.date_input(
                    "Data",
                    key="fi_partial_date",
                    value=date.today(),
                    max_value=date.today(),
                    format="DD/MM/YYYY",
                )
                c2.text_input(
                    "Valor resgatado, bruto (R$)",
                    key="fi_partial_gross",
                    placeholder="1.000,00",
                    help="Antes do IR e do IOF, como aparece no extrato do banco.",
                )
                st.button(
                    "Registrar resgate parcial",
                    type="primary",
                    on_click=on_partial_redemption,
                    args=(chosen["id"],),
                )
                st.caption(
                    "O restante continua rendendo. Cada resgate paga IR só sobre a parte "
                    "do rendimento que ele levou, pela alíquota do tempo desde a aplicação."
                )
                if chosen["partial_redemptions"]:
                    st.dataframe(
                        pd.DataFrame(
                            [
                                {
                                    "Data": date.fromisoformat(p["date"]).strftime("%d/%m/%Y"),
                                    "Bruto": brl(p["gross"]),
                                    "IOF + IR": brl(
                                        Decimal(p["iof"]) + Decimal(p["ir"])
                                        if p["ir"] is not None
                                        else None
                                    ),
                                    "Líquido": brl(p["net"]),
                                }
                                for p in chosen["partial_redemptions"]
                            ]
                        ),
                        hide_index=True,
                        width="stretch",
                    )
                    labels = {
                        f"{date.fromisoformat(p['date']):%d/%m/%Y} · {brl(p['gross'])}": p["id"]
                        for p in chosen["partial_redemptions"]
                    }
                    label = st.selectbox(
                        "Apagar resgate parcial",
                        list(labels),
                        index=None,
                        placeholder="Escolha o resgate a apagar",
                        key="fi_partial_delete",
                    )
                    st.button(
                        "Apagar resgate",
                        disabled=label is None,
                        on_click=on_delete_partial_redemption,
                        args=(chosen["id"], labels.get(label)),
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
