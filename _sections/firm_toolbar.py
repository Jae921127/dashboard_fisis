# firm_toolbar.py
"""
Toolbar for:
- Firm of interest (shows finance_nm, stores finance_cd; default 0010607)
- Entire market definition: [폐] 제외 / [폐] 포함
- Competing groups: 국내 / 외국계 (both can be ON)
- Custom groups (multi-create) with "확인"
- Period controls: 주기(분기/년) -> term Q/Y; 시작년월/종료년월 (YYYYMM) with validation
- [RUN IT] button: emits all params; app should only run when clicked

Stores exposed:
- ft-store-selected-firm: str | None
- ft-store-market-include-closed: bool
- ft-store-entire-market: list[str]
- ft-store-custom-groups: dict[str, list[str]]
- ft-store-groups: dict[str, list[str]]        # merged: toggles + custom
- ft-store-term: str                           # "Q" or "Y"
- ft-store-start: str                          # YYYYMM
- ft-store-end: str                            # YYYYMM
- ft-store-run-params: dict                    # consolidated params
- ft-store-run-trigger: int                    # increments on each RUN click
"""

from __future__ import annotations
from typing import Dict, List, Tuple
import re
import pandas as pd
from dash import dcc, html, Input, Output, State, no_update, callback_context, ALL
from dash.exceptions import PreventUpdate
from _helpers.filter import _canon_fin_cd_value, _canon_fin_cd_series


# ---------- Internal helpers ----------

def _filter_closed(df: pd.DataFrame, include_closed: bool) -> pd.DataFrame:
    """Apply [폐] filter on finance_nm."""
    if include_closed:
        return df.copy()
    m = ~df["finance_nm"].astype(str).str.contains("[폐]", regex=False)
    return df[m].copy()


def _df_to_options(df: pd.DataFrame) -> List[dict]:
    """
    Make label/value options for Dropdown.
    Label = finance_nm (what user sees)
    Value = finance_cd (what code uses)
    """
    df2 = df.copy()
    df2 = df2.sort_values(["finance_group", "finance_nm"], kind="mergesort")
    return [{"label": f"{row.finance_nm}", "value": f"{row.finance_cd}"} for _, row in df2.iterrows()]


def _render_custom_list(groups: Dict[str, List[str]], df_map: pd.DataFrame):
    """Render a small summary under the custom builder, now with remove buttons."""
    if not groups:
        return "사용자 지정 그룹이 없습니다."
    rows = []
    nm_by_cd = dict(zip(df_map["finance_cd"], df_map["finance_nm"]))
    for gname, cds in groups.items():
        names = [nm_by_cd.get(c, c) for c in cds]
        rows.append(html.Div([
            html.Button("×", id={"type": "ft-remove-group-btn", "name": gname}, 
                        style={'color':'red', 'border':'none', 'background':'none', 'cursor':'pointer', 'marginRight':'5px'}),
            html.Strong(gname),
            html.Span(f"  ({len(cds)}개): "),
            html.Span(" / ".join(names), style={"color": "#444"})
        ], style={"marginBottom": "4px"}))
    return rows

# ---------- Public helpers ----------

def load_finance_map(csv_path: str) -> pd.DataFrame:
    """
    Load mapping with columns: finance_cd | finance_nm | finance_group.
    Forces string dtype to preserve leading zeros.
    """
    df = pd.read_csv(csv_path, dtype=str,encoding="utf-8-sig")
    needed = {"finance_cd", "finance_nm", "finance_group"}
    missing = needed.difference(df.columns)
    if missing:
        raise ValueError(f"finance map missing columns: {missing}")
    return df[["finance_cd", "finance_nm", "finance_group"]].copy()


def make_firm_toolbar(df_map: pd.DataFrame) -> html.Div:
    """Build the toolbar layout (contains Stores + UI controls)."""
    # Define the content for the first row (RUN IT button is removed)
    row1_children = [
        html.Div([
            html.Label("주기"),
            dcc.RadioItems(id="ft-term", options=[{"label": "분기", "value": "Q"}, {"label": "년", "value": "Y"}], value="Q"),
        ], className="toolbar-group"),
        html.Div([
            html.Label("시작년월"),
            dcc.Input(id="ft-start", type="text", value="202001", debounce=True, placeholder="YYYYMM"),
        ], className="toolbar-group"),
        html.Div([
            html.Label("종료년월"),
            dcc.Input(id="ft-end", type="text", value="202312", debounce=True, placeholder="YYYYMM"),
        ], className="toolbar-group"),
        html.Span(id="ft-validate-msg", style={"color": "#c62828", "fontSize": "10px", "alignSelf": "center"}),
        html.Div([
            html.Label("전체시장정의"),
            dcc.RadioItems(id="ft-market-closed", options=[{"label": "[폐] 제외", "value": "exclude"}, {"label": "[폐] 포함", "value": "include"}], value="exclude"),
        ], className="toolbar-group"),
        html.Div([
            html.Label("관심 회사"),
            dcc.Dropdown(id="ft-firm", options=_df_to_options(_filter_closed(df_map, include_closed=False)), placeholder="회사 선택", value="0010607", clearable=True, style={"minWidth": "220px"}),
        ], className="toolbar-group"),
    ]

    # Define the content for the second row (unchanged)
    row2_children = [
        html.Div([
            html.Label("경쟁 그룹"),
            dcc.Checklist(id="ft-dom-foreign", options=[{"label": "국내", "value": "DOMESTIC"}, {"label": "외국계", "value": "FOREIGN"}], value=[]),
        ], className="toolbar-group"),
        html.Div([
            html.Label("맞춤 그룹"),
            dcc.Input(id="ft-custom-name", type="text", placeholder="그룹 이름", debounce=True, style={"width": "120px"}),
            dcc.Dropdown(id="ft-custom-cds", options=_df_to_options(_filter_closed(df_map, include_closed=False)), multi=True, placeholder="회사 선택", value=[], style={"minWidth": "280px"}),
            html.Button("확인", id="ft-custom-add", n_clicks=0, className="btn"),
        ], className="toolbar-group"),
        html.Div(id="ft-custom-list", style={"fontSize": "10px", "color": "#555", "alignSelf": "center"}),
    ]

    return html.Div(id="ft-toolbar", children=[
        # Stores (unchanged)
        dcc.Store(id="ft-store-selected-firm", data="0010607"), dcc.Store(id="ft-store-market-include-closed", data=False),
        dcc.Store(id="ft-store-entire-market", data=[]), dcc.Store(id="ft-store-custom-groups", data={}),
        dcc.Store(id="ft-store-groups", data={}), dcc.Store(id="ft-store-term", data="Q"),
        dcc.Store(id="ft-store-start", data="202001"), dcc.Store(id="ft-store-end", data="202312"),
        dcc.Store(id="ft-store-run-params", data={}), dcc.Store(id="ft-store-run-trigger", data=0),
        dcc.Store(id="ft-store-expanded", data=True),

        # The header bar now contains the RUN IT button
        html.Div(style={"display": "flex", "justifyContent": "space-between", "alignItems": "center"}, children=[
            html.Button("조회하기", id="ft-run", n_clicks=0, className="btn", style={"fontWeight": 700}),
            html.Button([html.Span("download", className="icon"), "설명서 다운로드"], id="btn-download-explain", className="btn"),
            html.Button("▾", id="ft-toggle", n_clicks=0, className="btn")
        ]),

        # The body now explicitly stacks its children vertically
        html.Div(id="ft-body", style={'display': 'flex', 'flexDirection': 'row'}, children=[
            html.Div(row1_children, className="toolbar-row"),
            html.Div(row2_children, className="toolbar-row", style={"marginTop": "8px"}),
        ]),
        dcc.Download(id="download-explain")
    ])





def register_firm_toolbar_callbacks(app, df_map: pd.DataFrame) -> None:
    """
    Wire up all callbacks for the toolbar.
    """
    @app.callback(
        Output("download-explain", "data"),
        Input("btn-download-explain", "n_clicks"),
        prevent_initial_call=True,
    )
    def download_explanation(n_clicks):
        """Sends the specified docx file to the user's browser for download."""
        return dcc.send_file("_local/설명서+계정항목.zip")

    # -- Validation helpers inside closure (no export)
    def _valid_yyyymm(s: str) -> bool:
        if not isinstance(s, str) or not re.fullmatch(r"\d{6}", s or ""):
            return False
        y = int(s[:4]); m = int(s[4:6])
        if y < 2010: return False
        if not (1 <= m <= 12): return False
        return True

    def _clamp_and_msg(start: str, end: str) -> Tuple[str, str, str, bool]:
        """Return (start, end, message, ok). Keeps inputs; only returns msg + ok flag."""
        ok_s = _valid_yyyymm(start)
        ok_e = _valid_yyyymm(end)
        msg = []
        if not ok_s:
            msg.append("시작년월 형식 오류(YYYYMM, 연도≥2010, 월 01–12).")
        if not ok_e:
            msg.append("종료년월 형식 오류(YYYYMM, 연도≥2010, 월 01–12).")
        if ok_s and ok_e and int(start) > int(end):
            msg.append("시작년월 ≤ 종료년월 이어야 합니다.")
            ok_s = ok_e = False
        ok = ok_s and ok_e
        return start, end, " ".join(msg), ok

    # -- 1) Market toggle -> update options + entire market list + store include-closed + default firm value if needed
    @app.callback(
        Output("ft-firm", "options"),
        Output("ft-custom-cds", "options"),
        Output("ft-store-entire-market", "data"),
        Output("ft-store-market-include-closed", "data"),
        Output("ft-firm", "value"),  # keep or set default 0010607 if still valid
        Input("ft-market-closed", "value"),
        State("ft-firm", "value"),
        prevent_initial_call=False,
    )
    def _update_market_options(market_mode: str, current_firm: str | None):
        include_closed = (market_mode == "include")
        df_f = _filter_closed(df_map, include_closed)
        df_f["finance_cd"] = _canon_fin_cd_series(df_f["finance_cd"])
        opts = _df_to_options(df_f)
        entire_market = df_f["finance_cd"].tolist()

        # keep current_firm if still present; else default to 0010607 if available; else None
        keep = current_firm if current_firm in entire_market else ("0010607" if "0010607" in entire_market else None)
        return opts, opts, entire_market, include_closed, keep

    # -- 2) Firm select -> store selected finance_cd
    @app.callback(
        Output("ft-store-selected-firm", "data"),
        Input("ft-firm", "value"),
        prevent_initial_call=False,
    )
    def _store_firm(finance_cd: str | None):
        finance_cd = _canon_fin_cd_value(finance_cd)
        return finance_cd

    # -- 3) Add/replace a custom group (honor market filter)
    # NEW CALLBACK 1: Handles ADDING a custom group
    @app.callback(
        Output("ft-store-custom-groups", "data", allow_duplicate=True),
        Output("ft-custom-name", "value"),
        Output("ft-custom-cds", "value"),
        Input("ft-custom-add", "n_clicks"),
        State("ft-custom-name", "value"),
        State("ft-custom-cds", "value"),
        State("ft-store-custom-groups", "data"),
        State("ft-store-entire-market", "data"),
        prevent_initial_call=True,
    )
    def _add_custom_group(n_clicks, name, cds, current, entire_market):
        if not n_clicks: raise PreventUpdate
        name = (name or "").strip()
        current = current or {}
        if not name or not cds: return current, no_update, no_update

        market_set = set(entire_market or [])
        filtered_cds = [c for c in cds if c in market_set]
        if not filtered_cds: return current, "", []

        current[name] = filtered_cds
        return current, "", []

    # NEW CALLBACK 2: Handles REMOVING a custom group
    @app.callback(
        Output("ft-store-custom-groups", "data"),
        Input({"type": "ft-remove-group-btn", "name": ALL}, "n_clicks"),
        State("ft-store-custom-groups", "data"),
        prevent_initial_call=True,
    )
    def _remove_custom_group(n_clicks, current_groups):
        if not any(n_clicks): raise PreventUpdate

        triggered_id = callback_context.triggered_id
        if not triggered_id: raise PreventUpdate

        group_to_remove = triggered_id["name"]

        current_groups = current_groups or {}
        if group_to_remove in current_groups:
            current_groups.pop(group_to_remove)

        return current_groups

    # NEW CALLBACK 3: Renders the list of custom groups whenever the store changes
    @app.callback(
        Output("ft-custom-list", "children"),
        Input("ft-store-custom-groups", "data"),
    )
    def _render_group_list(groups):
        return _render_custom_list(groups or {}, df_map)

    # -- 4) Build merged groups store from toggles + custom groups (honor market filter)
    @app.callback(
        Output("ft-store-groups", "data"),
        Input("ft-dom-foreign", "value"),
        Input("ft-store-entire-market", "data"),
        Input("ft-store-custom-groups", "data"),
        prevent_initial_call=False,
    )
    def _build_groups(toggles: List[str], entire_market: List[str], custom: Dict[str, List[str]]):
        toggles = toggles or []
        entire_set = set(entire_market or [])
        out: Dict[str, List[str]] = {}

        # Predefined groups, conditioned on market
        if "DOMESTIC" in toggles:
            dom = df_map[df_map["finance_group"] == "국내생보사"]["finance_cd"].tolist()
            out["국내"] = sorted(list(entire_set.intersection(dom)))
        if "FOREIGN" in toggles:
            frn = df_map[df_map["finance_group"] == "외국생보사"]["finance_cd"].tolist()
            out["외국계"] = sorted(list(entire_set.intersection(frn)))

        # Custom groups, conditioned on market
        for gname, cds in (custom or {}).items():
            out[gname] = sorted([c for c in cds if c in entire_set])

        return out

    # -- 5) Period controls: validate inputs, store term/start/end, enable/disable RUN
    @app.callback(
        Output("ft-validate-msg", "children"),
        Output("ft-run", "disabled"),
        Output("ft-store-term", "data"),
        Output("ft-store-start", "data"),
        Output("ft-store-end", "data"),
        Input("ft-term", "value"),
        Input("ft-start", "value"),
        Input("ft-end", "value"),
        prevent_initial_call=False,
    )
    def _validate_and_store(term: str, start: str, end: str):
        term = term or "Q"
        start = (start or "").strip()
        end = (end or "").strip()
        s, e, msg, ok = _clamp_and_msg(start, end)
        run_disabled = not ok
        return msg, run_disabled, term, s, e
    
    @app.callback(
        Output("ft-body", "style"),
        Input("ft-store-expanded", "data"),
        prevent_initial_call=False,
    )
    def _apply_expand_style(expanded):
        base = {
            "display": "flex", "gap": "8px", "alignItems": "end",
            "flexWrap": "nowrap", "whiteSpace": "nowrap",
            "fontSize": "11px","overflowY" : "visible"
        }
        if not expanded:
            base["display"] = "none"
        return base
    

    @app.callback(
        Output("ft-store-expanded", "data"),
        Input("ft-toggle", "n_clicks"),           # manual toggle
        Input("ft-store-run-trigger", "data"),    # auto-collapse after a run
        State("ft-store-expanded", "data"),
        prevent_initial_call=False,
    )
    def _set_expanded(n_toggle, run_counter, expanded):
        # Which input fired?
        trig = callback_context.triggered[0]["prop_id"].split(".")[0] if callback_context.triggered else None

        # First load: keep whatever is stored (default True unless you changed it)
        if trig is None:
            return expanded if expanded is not None else True

        # RUN completed -> collapse
        if trig == "ft-store-run-trigger":
            return False

        # Toggle button -> invert
        if trig == "ft-toggle":
            return not bool(expanded)

        return expanded


    # -- 6) RUN IT: consolidate params and raise a run trigger
    @app.callback(
        Output("ft-store-run-params", "data"),
        Output("ft-store-run-trigger", "data"),
        Input("ft-run", "n_clicks"),
        State("ft-store-selected-firm", "data"),
        State("ft-store-market-include-closed", "data"),
        State("ft-store-entire-market", "data"),
        State("ft-store-groups", "data"),
        State("ft-store-term", "data"),
        State("ft-store-start", "data"),
        State("ft-store-end", "data"),
        State("ft-run", "disabled"),
        State("ft-store-run-trigger", "data"),
        prevent_initial_call=True,
    )
    def _run_it(n_clicks, firm_cd, include_closed, entire_market, groups, term, start, end, disabled, prev_cnt):
        if not n_clicks or disabled:
            raise no_update
        params = {
            "financeCd": firm_cd,
            "includeClosed": bool(include_closed),
            "entireMarket": list(entire_market or []),
            "groups": dict(groups or {}),
            "term": term or "Q",
            "startBaseMm": start,
            "endBaseMm": end,
        }
        return params, int(prev_cnt or 0) + 1




