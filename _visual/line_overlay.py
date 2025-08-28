# _visual/line_overlay.py
from __future__ import annotations
import re
from typing import Dict, List, Optional
import pandas as pd
import plotly.graph_objects as go
from _visual.graph_hier_bar import values_for_accounts, months_sorted, parent_series_for_list

TOKEN_RE = re.compile(r"\s*([+\-*/])?\s*([A-Z]{2}\d{3}(?::[A-Z0-9]+)?)\s*")
RESCALE_CHOICES = [(1_000_000_000_000, "조"), (1_000_000_000, "십억"), (1_000_000, "백만"), (1_000, "천")]


def ensure_numeric(v):
    try:
        return float(v)
    except Exception:
        return 0.0

def select_rescaler_from_values(values) -> tuple[float, str]:
    """Choose the largest scaler in {1e3,1e6,1e9} so that min nonzero abs(value)/scaler >= 1.0."""
    flat = [abs(ensure_numeric(v)) for v in values if ensure_numeric(v) != 0]
    if not flat:
        return 1.0, ""
    min_abs = min(flat)
    for s, lab in RESCALE_CHOICES:
        if min_abs >= s:
            return float(s), lab
    return 1.0, ""

def _months(df: pd.DataFrame) -> List[str]:
    months = sorted({str(x) for x in df["base_month"].unique()})
    return months

def _series_for(df: pd.DataFrame, list_no: str, account_cd: str, colid: str) -> pd.Series:
    """
    Gets a data series for a specific account, using the same robust
    helper function as the main bar chart.
    """
    scope = df[df["list_no"] == list_no]
    
    vals = values_for_accounts(scope, [account_cd], colid)
    
    all_months = months_sorted(df)
    if vals.empty:
        return pd.Series(0.0, index=pd.Index(all_months, name="base_month"))
        
    ser = vals.groupby("base_month")["value"].sum()
    return ser.reindex(all_months).fillna(0.0)

def _eval_expr(df: pd.DataFrame, formula: str, colid: str, hier: dict) -> pd.Series:
    tokens = TOKEN_RE.findall(formula)
    if not tokens:
        return pd.Series(0.0, index=pd.Index(months_sorted(df), name="base_month"))

    op = "+"
    acc = None
    for sign, item in tokens:
        if sign:
            op = sign

        if ":" in item:
            lst, acd = item.split(":")
            s = _series_for(df, lst, acd, colid)
        else:
            list_no = item
            s = parent_series_for_list(df, hier[list_no], colid)

        if acc is None:
            acc = s.copy()
            continue
        if op == "+":
            acc = acc.add(s, fill_value=0.0)
        elif op == "-":
            acc = acc.sub(s, fill_value=0.0)
        elif op == "*":
            acc = acc.mul(s, fill_value=0.0)
        elif op == "/":
            acc = acc.div(s.replace(0, float("nan")), fill_value=0.0).fillna(0.0)
    return acc

def _eval_expr_cross_sectional(
    df: pd.DataFrame, formula: str, colid: str,
    account_cds: List[str], base_month: str
) -> Dict[str, float]:
    """
    Evaluates a formula for a list of accounts at a single point in time.
    Returns a dictionary mapping account_cd to the calculated value.
    """
    tokens = TOKEN_RE.findall(formula)
    if not tokens: return {acd: 0.0 for acd in account_cds}
    
    results = {}
    for acd in account_cds:
        op, acc = "+", None
        for sign, item in tokens:
            if sign: op = sign
            list_no = item
            series = _series_for(df, list_no, acd, colid)
            val = series.get(base_month, 0.0)

            if acc is None: acc = val
            else:
                if op == "+": acc += val
                elif op == "-": acc -= val
                elif op == "*": acc *= val
                elif op == "/": acc = acc / val if val != 0 else 0.0
        results[acd] = acc
    return results

def add_line_overlay(
    fig: go.Figure,
    *,
    df_firm: Optional[pd.DataFrame],
    df_market: pd.DataFrame,
    groups: Dict[str, List[str]],
    months: List[str],
    colid: str,
    expr: str,
    expr_nm: str,
    hier: dict,
    namer=None,
    compared_cds: Optional[List[str]] = None, 
):
    """Draws line chart overlays for the main firm, market, groups, and compared firms."""
    styles = [
        {'color': '#000000', 'dash': 'solid',   'symbol': 'circle'},
        {'color': '#555555', 'dash': 'dash',    'symbol': 'triangle-up'},
        {'color': '#555555', 'dash': 'dot',     'symbol': 'diamond'},
        {'color': '#000000', 'dash': 'dashdot', 'symbol': 'cross'},
        {'color': '#555555', 'dash': 'solid',   'symbol': 'star'},
        {'color': '#555555', 'dash': 'dash',    'symbol': 'square'},
    ]
    scopes_to_process = []
    style_idx = 0
    
    firm_cd_main = None
    if df_firm is not None and not df_firm.empty:
        try:
            firm_cd_main = df_firm["finance_cd"].iloc[0]
            firm_name = namer.finance_label(firm_cd_main, include_id=False)
            scopes_to_process.append({"df": df_firm, "label": firm_name, "style": styles[style_idx]})
            style_idx += 1
        except (IndexError, AttributeError):
            pass
    
    scopes_to_process.append({"df": df_market, "label": "Market", "style": styles[style_idx % len(styles)]})
    style_idx += 1
    
    for gname, cds in (groups or {}).items():
        if not cds: continue
        df_group = df_market[df_market["finance_cd"].isin(cds)]
        scopes_to_process.append({"df": df_group, "label": gname, "style": styles[style_idx % len(styles)]})
        style_idx += 1

    for comp_cd in (compared_cds or []):
        if comp_cd != firm_cd_main: 
             df_comp = df_market[df_market["finance_cd"] == comp_cd]
             if not df_comp.empty:
                 comp_name = namer.finance_label(comp_cd, include_id=False)
                 scopes_to_process.append({"df": df_comp, "label": comp_name, "style": styles[style_idx % len(styles)]})
                 style_idx += 1


    all_series_data = []
    all_values = []
    for scope in scopes_to_process:
        series = _eval_expr(scope["df"], expr, colid, hier=hier)
        if series is not None:
            all_series_data.append({"series": series, "scope": scope})
            all_values.extend(series.values)

    scale, unit = select_rescaler_from_values(all_values)
    y2_title = expr_nm
    if unit:
        y2_title = f"{expr_nm} ({unit})"

    for item in all_series_data:
        series, scope = item["series"], item["scope"]
        label, style = scope["label"], scope["style"]
        
        scaled_y = series.values / scale
        text_labels = [f"{v:,.2f}" for v in scaled_y]

        fig.add_trace(go.Scatter(
            x=months, y=scaled_y, name=label, yaxis="y2", mode="lines+markers+text",
            text=text_labels, textposition="top center", textfont=dict(size=9, color=style['color']),
            marker=dict(symbol=style['symbol'], color=style['color'], size=6),
            line=dict(width=2, color=style['color'], dash=style['dash'])
        ))

    fig.update_layout(
        yaxis2=dict(
            title=dict(text=y2_title, font=dict(size=10)), overlaying="y", side="right",
            showgrid=False, zeroline=False, tickfont=dict(size=8),
        ),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0)
    )
