from dash import dcc, html, Input, Output, State, callback_context, no_update
from dash.dependencies import MATCH, ALL
from dash.exceptions import PreventUpdate
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd
import re

from _analytics.market_share import compute_full_market_share_data
from _utils.build_master import load_or_build_master_for_market
from _visual.graph_hier_bar import (
    make_hier_stacked_figure, node_parent_values, donut_for_hovered_node,
    select_rescaler_from_values, natural_key, months_sorted, parse_custom_nodes
)
from _visual.line_overlay import add_line_overlay
from _visual.delta_plot import make_delta_plot
from _helpers.graph import _extract_hover, _hover_key
from _helpers.filter import _canon_fin_cd_series, _canon_fin_cd_value, _filter_master_data_for_section


def _get_sub_section_index(base_month, date_ranges, global_start, global_end):
    if not date_ranges: return 0
    for i, (start, end) in enumerate(date_ranges):
        eff_start = start if start != "start" else global_start
        eff_end = end if end != "end" else global_end
        if eff_start <= base_month <= eff_end:
            return i
    return None

def _section(sec: str, title: str):
    """Builds the static HTML structure for a section, including containers for dynamic plots."""
    return html.Div(className="layout", children=[
        # Stores for state management (unchanged)
        dcc.Store(id={"type": "hover-node", "sec": sec}, data=None),
        dcc.Store(id={"type": "hover-month", "sec": sec}, data=None),
        dcc.Store(id={"type": "level-path", "sec": sec}, data=[]),
        dcc.Store(id={"type": "custom-nodes", "sec": sec}, data=None),
        dcc.Store(id={"type": "overlay-spec-store", "sec": sec}, data=None),
        dcc.Store(id={"type": "section-params-store", "sec": sec}, data=None),
        dcc.Store(id={"type": "ms-data-store", "sec": sec}, data=None),
        dcc.Store(id={"type": "compared-firms", "sec": sec}, data=[]),
        dcc.Store(id={"type": "selected-colid", "sec": sec}, data=None),
        
        html.Div(className="panel", children=[
            html.Div(className="toolbar", children=[
                html.Button([html.Span("arrow_back", className="icon"), "Back"], id={"type": "btn-back", "sec": sec}, className="btn"),
                html.Span(title, className="title"),
                html.Div(id={"type": "colid-selector-container", "sec": sec}, style={'marginLeft': 'auto'})
            ]),
            
            # Market Share / Treemap plot (remains at the top)
            html.Div(style={"display": "flex", "gap": "12px", "alignItems": "stretch", "width": "90%", "marginTop": "10px"},
                children=[
                    html.Div(style={"flex": "2.5", "border": "1px solid #eee", "borderRadius": "10px"}, children=[dcc.Graph(id={"type": "market-share-treemap", "sec": sec}, style={"height": "400px"})]),
                    html.Div(id={"type": "ms-line-plot-container", "sec": sec}, style={"display": "flex", "gap": "8px", "flex": "7.5"}),
                ]
            ),
            
            # --- FIX: Moved the main bar chart container UP ---
            html.Div(style={"width": "100%", "marginTop":"10px"},
                children=[
                    html.Div(style={"position": "relative", "display": "flex", "flex": "1 1 auto", "minWidth": 0}, children=[
                        html.Div(id={"type": "bar-container", "sec": sec}, style={"display": "flex", "gap": "8px", "flex": "1 1 auto", "width": "100%"}),
                        html.Div(id={"type": "hover-overlay", "sec": sec}, style={"display": "none"}, children=[
                            dcc.Graph(id={"type": "hover-donut", "sec": sec}, config={"displayModeBar": False, "staticPlot": True}),
                            html.Div(id={"type": "summary-content", "sec": sec}, style={"padding": "8px"})
                        ]),
                    ])
                ],
            ),

            # --- FIX: Moved the RadioItems to its own toolbar between the plots ---
            html.Div(className="toolbar-row", style={"justifyContent": "flex-end", "margin": "10px 0 4px 0"}, children=[
                dcc.RadioItems(id={"type": "delta-view-selector", "sec": sec},
                    options=[{'label': 'All', 'value': 'all'}, {'label': '전기대비', 'value': 'prev'},
                             {'label': '전년동기대비', 'value': '1y'}, {'label': '전전년동기대비', 'value': '2y'}],
                    value='all', labelStyle={'display': 'inline-block', 'marginRight': '10px'},
                    inputStyle={'marginRight': '4px'})
            ]),

            # --- FIX: Moved the delta plot container DOWN ---
            html.Div(id={"type": "delta-plot-container", "sec": sec}, style={"display": "flex", "gap": "8px", "width": "100%"}),
        ]),
    ])

def make_hier_sections(section_cfgs, hier, namer):
    """Creates the layout for all sections, dynamically creating side-by-side plots."""
    views = []
    for cfg in section_cfgs:
        v = _section(cfg["sec"], cfg["title"])
        num_sub = cfg.get("sub_sec", 1)

        if num_sub > 1:
            v.children[2].data = {f'path_{i}': [] for i in range(num_sub)}
            v.children[3].data = {f'nodes_{i}': parse_custom_nodes(cfg["spec"][i], hier) for i in range(num_sub)}
            v.children[4].data = {f'overlay_{i}': {"expr": cfg["expr"][i], "expr_nm": cfg["expr_nm"][i]} for i in range(num_sub)}
            v.children[5].data = {"is_hybrid": True, "sub_sec": num_sub, "specs": cfg["spec"], "colids": cfg.get("colid"), "terms": cfg.get("term"), "dates": cfg.get("date")}
        else:
            spec_str = cfg["spec"][0] if isinstance(cfg.get("spec"), list) else cfg.get("spec", "")
            expr_str = cfg["expr"][0] if isinstance(cfg.get("expr"), list) else cfg.get("expr")
            expr_nm_str = cfg["expr_nm"][0] if isinstance(cfg.get("expr_nm"), list) else cfg.get("expr_nm")
            colid_val = cfg["colid"][0] if isinstance(cfg.get("colid"), list) else cfg.get("colid")
            term_val = cfg["term"][0] if isinstance(cfg.get("term"), list) else cfg.get("term")
            v.children[2].data = []
            v.children[3].data = parse_custom_nodes(spec_str, hier)
            v.children[4].data = {"expr": expr_str, "expr_nm": expr_nm_str}
            v.children[5].data = {"is_hybrid": False, "colid": colid_val, "term": term_val, "min_d": cfg.get("min_d"), "max_d": cfg.get("max_d")}

        colid_options, default_colid = [], None
        if "colid" in cfg and isinstance(cfg["colid"], list) and len(cfg["colid"]) > 1:
            spec_for_naming = (cfg["spec"][0] if isinstance(cfg.get("spec"), list) else cfg.get("spec", "")).split(" + ")[0]
            list_no_for_naming = spec_for_naming.split(":")[0]

            for col in cfg["colid"]:
                label = namer.column_label(list_no_for_naming, None, col, include_id=False)
                colid_options.append({"label": label, "value": col})
            if colid_options: default_colid = colid_options[0]["value"]
        
        # If colid is not a list, get the single value or fallback
        elif "colid" in cfg:
            default_colid = cfg["colid"][0] if isinstance(cfg["colid"], list) else cfg["colid"]

        # Store the default value in our new store (it's the 9th child, index 8)
        v.children[8].data = default_colid
        
        colid_selector_container = v.children[9].children[0].children[2] # Find the container
        if colid_options:
            colid_selector_container.children = dcc.RadioItems(
                id={"type": "colid-selector", "sec": cfg["sec"]}, options=colid_options, value=default_colid,
                labelStyle={'display': 'inline-block', 'marginRight': '10px'}, inputStyle={'marginRight': '4px'})
        
        # Find the plot containers by their path in the layout
        ms_container = v.children[9].children[1].children[1]
        bar_container = v.children[9].children[2].children[0].children[0]
        delta_container = v.children[9].children[4]
        
        
        # Dynamically create the graph components for all sub-sections
        delta_container.children = [html.Div(id={"type": "delta-subplot-wrapper", "sec": cfg["sec"], "sub": i}, style={'flex': 1}, children=[dcc.Graph(id={"type": "delta-plot", "sec": cfg["sec"], "sub": i}, style={"height": "250px"})]) for i in range(num_sub)]
        bar_container.children = [html.Div(id={"type": "bar-subplot-wrapper", "sec": cfg["sec"], "sub": i}, style={'flex': 1}, children=[dcc.Graph(id={"type": "bar", "sec": cfg["sec"], "sub": i}, style={"height": "420px"}, clear_on_unhover=True)]) for i in range(num_sub)]
        ms_container.children = [html.Div(id={"type": "ms-subplot-wrapper", "sec": cfg["sec"], "sub": i}, style={'flex': 1}, children=[dcc.Graph(id={"type": "market-share-line-plot", "sec": cfg["sec"], "sub": i}, style={"height": "400px"})]) for i in range(num_sub)]

        views.append(v)
    return views

def register_hier_section_callbacks(app, hier, namer, list_nos, colid, term, section_cfgs, hier_json_path, cache_csv_path=None):
    
    @app.callback(
        Output({"type": "selected-colid", "sec": MATCH}, "data"),
        Input({"type": "colid-selector", "sec": MATCH}, "value"),
        prevent_initial_call=True,
    )
    def _update_selected_colid(selected_colid):
        """Stores the user-selected column ID."""
        return selected_colid

    @app.callback(
        Output({"type": "compared-firms", "sec": MATCH}, "data"),
        Input({"type": "market-share-treemap", "sec": MATCH}, "clickData"),
        State({"type": "compared-firms", "sec": MATCH}, "data"),
        prevent_initial_call=True,
    )
    def _update_compared_firms(clickData, compared_cds):
        """
        Handles clicks on the treemap to add or remove firms from the comparison list.
        This function has a toggle behavior.
        """
        if not clickData:
            raise PreventUpdate
            
        clicked_id = clickData["points"][0].get("id")
        
        if clicked_id and clicked_id.isdigit():
            new_list = compared_cds[:]
            
            if clicked_id in new_list:
                new_list.remove(clicked_id)
            else:
                new_list.append(clicked_id)
            return new_list

        return no_update
    
    @app.callback(
        Output({"type": "delta-subplot-wrapper", "sec": MATCH, "sub": ALL}, "style"),
        Output({"type": "bar-subplot-wrapper", "sec": MATCH, "sub": ALL}, "style"),
        Output({"type": "ms-subplot-wrapper", "sec": MATCH, "sub": ALL}, "style"),
        Input("ft-store-master", "data"),
        State({"type": "section-params-store", "sec": MATCH}, "data"),
        State("ft-store-run-params", "data"),
    )
    def _update_subplot_widths(master, section_params, run_params):
        """
        Calculates and sets the proportional widths for side-by-side sub-plots.
        """
        num_sub = section_params.get("sub_sec", 1)
        if not master or not run_params or not section_params.get("is_hybrid"):
            return [no_update] * num_sub, [no_update] * num_sub, [no_update] * num_sub
        
        df_master = pd.DataFrame(master)
        styles = []

        for i in range(num_sub):
            date_range = (section_params.get("dates") or [])[i]
            sub_params = {"min_d": date_range[0], "max_d": date_range[1]}
            sub_df, _, _ = _filter_master_data_for_section(df_master, sub_params, "", "")
            
            num_months = len(sub_df["base_month"].unique())
            styles.append({'flex': num_months if num_months > 0 else 1, 'minWidth': 0})
        
        return styles, styles, styles
    
    @app.callback(
        Output({"type":"bar","sec": MATCH, "sub": ALL}, "figure"),
        Input("ft-store-master", "data"),
        Input({"type":"level-path","sec": MATCH}, "data"),
        Input({"type": "compared-firms", "sec": MATCH}, "data"),
        Input({"type": "selected-colid", "sec": MATCH}, "data"),
        State("ft-store-run-params", "data"),
        State({"type":"custom-nodes","sec": MATCH}, "data"),
        State({"type": "overlay-spec-store", "sec": MATCH}, "data"),
        State({"type": "section-params-store", "sec": MATCH}, "data"),
        State("ft-store-selected-firm", "data"),
    )
    def _update_fig_section(master, level_path, compared_cds, selected_colid, run_params, custom_nodes, overlay_spec, section_params, firm_cd):
        num_sub = section_params.get("sub_sec", 1)
        if not master or not run_params:
            return [no_update] * num_sub

        df_master = pd.DataFrame(master)
        firm_cd_norm = _canon_fin_cd_value(firm_cd)
        groups = run_params.get("groups", {})
        all_figs = []

        patterns = ["", "x", "/", ".", "-"]
        
        for i in range(num_sub):
            firms_to_plot = {}
            if firm_cd_norm:
                firms_to_plot[firm_cd_norm] = {"pattern": patterns[0]}
            
            if section_params.get("term"): term = section_params.get("term")
            else: term = run_params.get("term")

            p_idx = 1
            for cd in (compared_cds or []):
                if cd != firm_cd_norm and p_idx < len(patterns):
                    firms_to_plot[cd] = {"pattern": patterns[p_idx]}
                    p_idx += 1
            
            if section_params.get("is_hybrid"):
                dates_list = section_params.get("dates") or []
                colids_list = section_params.get("colids") or []
                date_range = dates_list[i] if i < len(dates_list) else ["start", "end"]
                start_date, end_date = date_range[0], date_range[1]
                if start_date == 'start':
                    start_date = run_params.get("startBaseMm")
                if end_date == 'end':
                    end_date = run_params.get("endBaseMm")

                sub_colid_val = selected_colid or (colids_list[i] if i < len(colids_list) else colid)
                sub_params = {"min_d": start_date, "max_d": end_date}
                sub_df, _, _ = _filter_master_data_for_section(df_master, sub_params, colid, term)
                sub_path = level_path.get(f'path_{i}', [])
                sub_nodes = custom_nodes.get(f'nodes_{i}', [])
                sub_overlay = overlay_spec.get(f'overlay_{i}', {})
            else: 
                sub_params = {
                    "min_d": run_params.get("startBaseMm"),
                    "max_d": run_params.get("endBaseMm")
                }
                df_filtered, final_colid, _ = _filter_master_data_for_section(df_master, sub_params, colid, term)
                sub_df = df_filtered
                sub_path, sub_nodes, sub_overlay = level_path or [], custom_nodes, overlay_spec
                sub_colid_val = selected_colid or final_colid
            
            sub_scope = sub_df[sub_df.finance_cd == firm_cd_norm] if firm_cd_norm else sub_df

            if not sub_df.empty:
                fig_sub = make_hier_stacked_figure(
                    hier, sub_df, list_nos, sub_colid_val, sub_path, namer, sub_nodes,
                    firms_to_plot=firms_to_plot
                )
                
                if sub_overlay and sub_overlay.get("expr"):
                   add_line_overlay(
                        fig_sub, df_firm=(sub_scope if firm_cd_norm else None), df_market=sub_df,
                        groups=groups, months=months_sorted(sub_df), colid=sub_colid_val,
                        expr=sub_overlay["expr"], expr_nm=sub_overlay.get("expr_nm"),
                        hier=hier, namer=namer,
                        compared_cds=compared_cds
                    )
                all_figs.append(fig_sub)
            else:
                all_figs.append(go.Figure())
        
        return all_figs

    @app.callback(
        Output({"type": "delta-plot", "sec": MATCH, "sub": ALL}, "figure"),
        Input("ft-store-master", "data"),
        Input({"type":"level-path","sec": MATCH}, "data"),
        Input({"type": "delta-view-selector", "sec": MATCH}, "value"),
        Input({"type": "compared-firms", "sec": MATCH}, "data"),
        Input({"type": "selected-colid", "sec": MATCH}, "data"), # <-- ADD THIS INPUT
        State("ft-store-run-params", "data"),
        State({"type":"custom-nodes","sec": MATCH}, "data"),
        State({"type": "section-params-store", "sec": MATCH}, "data"),
        State("ft-store-selected-firm", "data"),
    )
    def _update_delta_plot(master, level_path, delta_view_selection, compared_cds, selected_colid, run_params, custom_nodes, section_params, firm_cd):
        num_sub = section_params.get("sub_sec", 1)
        if not master or not run_params:
            return [no_update] * num_sub

        df_master = pd.DataFrame(master)
        firm_cd_norm = _canon_fin_cd_value(firm_cd)
        groups = run_params.get("groups", {})
        entire_market = run_params.get("entireMarket", [])
        selected_firm_name = namer.finance_label(firm_cd_norm, False) if firm_cd_norm else ""
        all_figs = []

        for i in range(num_sub):
            if section_params.get("term"): term = section_params.get("term")
            else: term = run_params.get("term")
            if section_params.get("is_hybrid"):
                dates_list = section_params.get("dates") or []
                colids_list = section_params.get("colids") or []
                date_range = dates_list[i] if i < len(dates_list) else ["start", "end"]

                start_date, end_date = date_range[0], date_range[1]
                if start_date == 'start':
                    start_date = run_params.get("startBaseMm")
                if end_date == 'end':
                    end_date = run_params.get("endBaseMm")

                sub_colid_val = selected_colid or (colids_list[i] if i < len(colids_list) else colid)
                # --- FIX: Use the corrected start_date and end_date variables ---
                sub_params = {"min_d": start_date, "max_d": end_date}
                sub_df, _, _ = _filter_master_data_for_section(df_master, sub_params, colid, term)
                sub_path = level_path.get(f'path_{i}', [])
                sub_nodes = custom_nodes.get(f'nodes_{i}', [])
            else:
                sub_params = {
                    "min_d": run_params.get("startBaseMm"),
                    "max_d": run_params.get("endBaseMm")
                }
                df_filtered, final_colid, _ = _filter_master_data_for_section(df_master, sub_params, colid, term)
                sub_df = df_filtered
                sub_path, sub_nodes = level_path or [], custom_nodes
                sub_colid_val = selected_colid or final_colid
            

            if sub_df.empty:
                all_figs.append(go.Figure())
                continue

            collected_series_sub = {}
            def get_entity_series(df):
                _, _, parent_vals = node_parent_values(df, hier, list_nos, sub_colid_val, sub_path, sub_nodes)
                if parent_vals.empty: return None
                return parent_vals.groupby("base_month")["value"].sum()

            if firm_cd_norm:
                series = get_entity_series(sub_df[sub_df.finance_cd == firm_cd_norm])
                if series is not None: collected_series_sub[selected_firm_name] = series
            
            series = get_entity_series(sub_df[sub_df.finance_cd.isin(entire_market)])
            if series is not None: collected_series_sub["Market"] = series
            
            for gname, cds in groups.items():
                series = get_entity_series(sub_df[sub_df.finance_cd.isin(cds)])
                if series is not None: collected_series_sub[gname] = series

            for comp_cd in (compared_cds or []):
                if comp_cd != firm_cd_norm:
                    series = get_entity_series(sub_df[sub_df.finance_cd == comp_cd])
                    if series is not None:
                        comp_name = namer.finance_label(comp_cd, False)
                        collected_series_sub[comp_name] = series

            fig_sub = make_delta_plot(
                collected_series_sub,
                selected_firm_name,
                term,
                view_selection=delta_view_selection
            )
            all_figs.append(fig_sub)

        return all_figs
    
    @app.callback(
        Output({"type":"hover-donut","sec": MATCH}, "figure"),
        Output({"type":"hover-overlay","sec": MATCH}, "style"),
        Output({"type":"summary-content","sec": MATCH}, "children"),
        Input({"type":"bar","sec": MATCH, "sub": ALL}, "hoverData"),
        State({"type":"level-path","sec": MATCH}, "data"),
        State("ft-store-master", "data"),
        State("ft-store-run-params", "data"),
        State("ft-store-selected-firm", "data"),
        State({"type": "section-params-store", "sec": MATCH}, "data"),
        State({"type":"custom-nodes","sec": MATCH}, "data"),
        prevent_initial_call=True,
    )
    def _update_hover_overlays(hoverData_list, level_path, master, run_params, firm_cd, section_params, custom_nodes):
        hoverData = next((h for h in hoverData_list if h), None)
        if not hoverData or not master or not run_params:
            return go.Figure(), {"display": "none"}, no_update

        node_key, base_month, hovered_firm_cd = _extract_hover(hoverData)
        if not node_key or not base_month:
            return go.Figure(), {"display": "none"}, no_update

        df_master = pd.DataFrame(master)
        # For the donut, prioritize the firm that was actually hovered on.
        # Fall back to the main selected firm if the hover data is incomplete.
        firm_cd_for_donut = hovered_firm_cd or _canon_fin_cd_value(firm_cd)

        global_start, global_end = run_params.get("startBaseMm"), run_params.get("endBaseMm")

        if section_params.get("is_hybrid"):
            sub_index = _get_sub_section_index(base_month, section_params.get("dates"), global_start, global_end)
            if sub_index is None: raise PreventUpdate
            
            sub_params = {"min_d": section_params["dates"][sub_index][0], "max_d": section_params["dates"][sub_index][1], "colid": section_params["colids"][sub_index], "term": (section_params.get("terms") or [term]*section_params["sub_sec"])[sub_index]}
            final_path = level_path.get(f'path_{sub_index}', [])
            final_nodes = custom_nodes.get(f'nodes_{sub_index}', [])
            df_filtered, final_colid, _ = _filter_master_data_for_section(df_master, sub_params, colid, term)
        else:
            df_filtered, final_colid, _ = _filter_master_data_for_section(df_master, section_params, colid, term)
            final_path, final_nodes = level_path, custom_nodes

        df_scope = df_filtered[df_filtered.finance_cd == firm_cd_for_donut] if firm_cd_for_donut else df_filtered
        if df_scope.empty:
            return go.Figure(), {"display": "none"}, no_update
        
        donut_fig, _, _, _ = donut_for_hovered_node(hier, df_scope, final_colid, node_key, str(base_month), namer=namer)
        
        parent_listno, nodes, parent_vals = node_parent_values(
            df_master=df_scope, hier_by_list=hier, list_nos=list_nos, colid=final_colid,
            level_path=(final_path or []), custom_nodes=final_nodes,
        )
        
        items = []
        if parent_listno == "__MULTI__":
            for ln in nodes:
                v = float(parent_vals[(parent_vals["node_id"] == ln) & (parent_vals["base_month"] == str(base_month))]["value"].sum())
                lbl = namer.list_label(ln, include_id=False); items.append((lbl, v))
        elif parent_listno == "__CUSTOM__":
            for nid in nodes:
                v = float(parent_vals[(parent_vals["node_id"] == nid) & (parent_vals["base_month"] == str(base_month))]["value"].sum())
                if nid.startswith("acc:"):
                    _, lst, acd = nid.split(":"); lbl = namer.account_label(lst, acd, descendent=False, include_id=False)
                else:
                    lst = nid.split(":")[1]; lbl = namer.list_label(lst, include_id=False)
                items.append((lbl, v))
        else:
            for acd in nodes:
                v = float(parent_vals[(parent_vals["node_id"] == acd) & (parent_vals["base_month"] == str(base_month))]["value"].sum())
                lbl = namer.account_label(parent_listno, acd, descendent=False, include_id=False)
                items.append((lbl, v))
        items.sort(key=lambda x: natural_key(x[0]))
        
        vals = [abs(v) for _, v in items]; scale_s, unit_s = select_rescaler_from_values(vals)
        total_abs = sum(vals) or 1.0
        
        title_text = f"현재 계정 요약: 볼륨 | 구성비"
        if unit_s:
            title_text += f" - ({unit_s})"
        summary_title = html.Div(title_text, className="title", style={'fontSize': '11px', 'marginBottom': '8px'})
        
        summary_rows = []
        for lbl, v in items:
            share = abs(v) / total_abs
            right = html.Span(f"{(v/(scale_s or 1.0)):,.2f} | {share*100:,.2f}%", className="mono")
            summary_rows.append(html.Div(
                className="kv",
                children=[
                    html.Span(lbl, style={"marginRight":"4px","whiteSpace":"nowrap","overflow":"hidden","textOverflow":"ellipsis"}),
                    right
                ]
            ))  
        summary_content = [summary_title] + summary_rows
        
        all_months = months_sorted(df_scope)
        active_overlay_style = {
            "display": "flex", "flexDirection": "column",
            "position": "absolute", "top": "8px", "zIndex": 10,
            "background": "rgba(255, 255, 255, 0.95)", "borderRadius": "12px", 
            "boxShadow": "0 6px 16px rgba(0,0,0,0.25)", "pointerEvents": "none",
            "maxWidth": "450px",
        }
        try:
            hover_index = all_months.index(str(base_month))
            position_ratio = (hover_index + 0.5) / len(all_months)
            if position_ratio < 2/3: active_overlay_style.update({'right': '8px', 'left': 'auto'})
            else: active_overlay_style.update({'left': '8px', 'right': 'auto'})
        except (ValueError, ZeroDivisionError):
            active_overlay_style.update({'right': '8px', 'left': 'auto'})
        
        return donut_fig, active_overlay_style, summary_content

    @app.callback(
        Output({"type":"level-path","sec": MATCH}, "data"),
        Input({"type":"bar","sec": MATCH, "sub": ALL}, "clickData"),
        Input({"type":"btn-back","sec": MATCH}, "n_clicks"),
        State({"type":"level-path","sec": MATCH}, "data"),
        State({"type": "section-params-store", "sec": MATCH}, "data"),
        prevent_initial_call=True,
    )
    def _nav_section(clickData_list, back_clicks, level_path, section_params):
        ctx = callback_context
        if not ctx.triggered:
            raise PreventUpdate

        triggered_id = ctx.triggered_id
        is_hybrid = section_params.get("is_hybrid")

        # --- FIX 1: Correctly check for a dictionary ID for the back button ---
        if isinstance(triggered_id, dict) and triggered_id.get("type") == "btn-back":
            if is_hybrid:
                return {key: path[:-1] for key, path in (level_path or {}).items()}
            else:
                return (level_path or [])[:-1]

        if isinstance(triggered_id, dict) and triggered_id.get("type") == "bar":
            clicked_sub_index = triggered_id.get("sub", 0)
            clickData = clickData_list[clicked_sub_index]
            if not clickData or not clickData.get("points"): raise PreventUpdate

            # --- FIX 2: Extract the node_key directly from customdata, removing the need for _hover_key ---
            try:
                key = clickData["points"][0]["customdata"]["node_key"]
            except (KeyError, IndexError):
                raise PreventUpdate
            
            if not key: raise PreventUpdate

            if is_hybrid:
                path_key = f'path_{clicked_sub_index}'
                new_path_dict = dict(level_path or {})
                current_sub_path = new_path_dict.get(path_key, [])
                # Append the new key to the specific sub-path
                new_path_dict[path_key] = current_sub_path + [key]
                return new_path_dict
            else:
                return (level_path or []) + [key]

        return no_update
    
    # In _sections/hier_section.py

    @app.callback(
        Output({"type": "market-share-line-plot", "sec": MATCH, "sub": ALL}, "figure"),
        Output({"type": "ms-data-store", "sec": MATCH}, "data"),
        Input("ft-store-master", "data"),
        Input({"type":"level-path","sec": MATCH}, "data"),
        Input({"type": "compared-firms", "sec": MATCH}, "data"),
        Input({"type": "selected-colid", "sec": MATCH}, "data"),
        State("ft-store-run-params", "data"),
        State({"type":"custom-nodes","sec": MATCH}, "data"),
        State("ft-store-selected-firm", "data"),
        State({"type": "section-params-store", "sec": MATCH}, "data"),
    )
    def _update_ms_line_plot(master, level_path, compared_cds, selected_colid, run_params, custom_nodes, firm_cd, section_params):
        num_sub = section_params.get("sub_sec", 1)
        if not master or not run_params:
            return [no_update] * num_sub, no_update
        df_master = pd.DataFrame(master)
        firm_cd_norm = _canon_fin_cd_value(firm_cd)
        groups = run_params.get("groups", {})
        entire_market = run_params.get("entireMarket", [])
        all_figs = []
        color_palette = px.colors.qualitative.Plotly
        treemap_data_store = pd.DataFrame()
        
        for i in range(num_sub):
            fig_sub = go.Figure()
            if section_params.get("term"): term = section_params.get("term")
            else: term = run_params.get("term")

            if section_params.get("is_hybrid"):
                dates_list, colids_list, terms_list = section_params.get("dates", []), section_params.get("colids", []), section_params.get("terms", [])
                date_range = dates_list[i] if i < len(dates_list) else ["start", "end"]
                start_date, end_date = date_range[0], date_range[1]
                if start_date == 'start':
                    start_date = run_params.get("startBaseMm")
                if end_date == 'end':
                    end_date = run_params.get("endBaseMm")

                sub_colid_val = selected_colid or (colids_list[i] if i < len(colids_list) else colid)
                sub_params = {"min_d": start_date, "max_d": end_date}
                sub_path = level_path.get(f'path_{i}', [])
                sub_nodes = custom_nodes.get(f'nodes_{i}', [])
            else: # Standard Section
                sub_params = {
                    "min_d": run_params.get("startBaseMm"),
                    "max_d": run_params.get("endBaseMm")
                }
                sub_colid_val = selected_colid or section_params.get("colid") or colid
                sub_path, sub_nodes = level_path or [], custom_nodes

            sub_df, _, _ = _filter_master_data_for_section(df_master, sub_params, colid, term)

            if sub_df.empty:
                all_figs.append(fig_sub)
                continue
            
            # 3. Calculate Market Share data ONLY for this subplot
            ms_data = compute_full_market_share_data(sub_df, hier_by_list=hier, list_nos=list_nos, colid=sub_colid_val, level_path=sub_path, entire_market_cds=entire_market, groups=groups, custom_nodes=sub_nodes)
            df_per_firm = ms_data["per_firm"]
            group_analytics = ms_data["groups"]

            # For the first subplot, save its data to be used by the treemap
            if i == 0:
                treemap_data_store = df_per_firm

            # 4. Plot the traces for this subplot
            if firm_cd_norm and not df_per_firm.empty:
                df_firm_trace = df_per_firm[df_per_firm["finance_cd"] == firm_cd_norm]
                fig_sub.add_trace(go.Scatter(x=df_firm_trace["base_month"], y=df_firm_trace["share_pct"], name=namer.finance_label(firm_cd_norm, False), mode='lines+markers', line=dict(width=4, color="#1f77b4")))
            
            for gname, g_data in group_analytics.items():
                df_agg, df_avg = g_data.get("agg"), g_data.get("avg")
                if df_agg is not None and not df_agg.empty:
                    fig_sub.add_trace(go.Scatter(x=df_agg["base_month"], y=df_agg["share_pct"], name=f"{gname}_전체", mode='lines', line=dict(dash='dash')))
                if df_avg is not None and not df_avg.empty:
                    fig_sub.add_trace(go.Scatter(x=df_avg["base_month"], y=df_avg["share_pct"], name=f"{gname}_평균", mode='lines', line=dict(dash='dot')))
            
            color_idx = 0
            for comp_cd in (compared_cds or []):
                if comp_cd == firm_cd_norm: continue
                df_comp_trace = df_per_firm[df_per_firm["finance_cd"] == comp_cd]
                if not df_comp_trace.empty:
                    color = color_palette[color_idx % len(color_palette)]
                    fig_sub.add_trace(go.Scatter(x=df_comp_trace["base_month"], y=df_comp_trace["share_pct"], name=namer.finance_label(comp_cd, False), mode='lines', line=dict(width=2, color=color, dash='solid')))
                    color_idx += 1
            
            fig_sub.update_layout(title_text="M/S Trend", yaxis_ticksuffix="%", hovermode="x unified", margin=dict(l=20, r=20, t=40, b=20), showlegend=(i==0), legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0))
            all_figs.append(fig_sub)
                
        return all_figs, treemap_data_store.to_dict("records")
    
    @app.callback(
        Output({"type": "market-share-treemap", "sec": MATCH}, "figure"),
        Input({"type": "market-share-line-plot", "sec": MATCH, "sub": ALL}, "hoverData"),
        State({"type": "ms-data-store", "sec": MATCH}, "data"),
        State("ft-store-selected-firm", "data"),
        State("ft-store-run-params", "data"),
        prevent_initial_call=True
    )
    def _update_treemap(hoverData_list, ms_data, firm_cd, run_params):
        hoverData = next((h for h in hoverData_list if h), None)
        
        if not ms_data or not run_params or not hoverData: 
            raise PreventUpdate

        df_per_firm = pd.DataFrame(ms_data)
        firm_cd_norm = _canon_fin_cd_value(firm_cd)
        groups = run_params.get("groups", {})

        if hoverData and hoverData.get("points"):
            base_month = str(hoverData["points"][0]["x"])
        else:
            raise PreventUpdate

        df_month = df_per_firm[df_per_firm["base_month"] == base_month].copy()
        if df_month.empty: raise PreventUpdate
        
        def _clean_name(name): return re.sub(r"(주식|회사|보험)", "", name)
        def _format_delta_hover(v):
            if pd.isna(v): return "—"
            return f"{v:+.2f}pp"

        ids, labels, parents, values, customdata, colors = [], [], [], [], [], []
        root_id = "Market"
        ids.append(root_id); labels.append(root_id); parents.append(""); values.append(0); customdata.append(["", "", "", ""]); colors.append(0)

        for gname in groups:
            ids.append(gname); labels.append(f"<b>{gname}</b>"); parents.append(root_id); values.append(0); customdata.append(["", "", "", ""]); colors.append(0)

        total_firms = len(df_month)
        for _, row in df_month.iterrows():
            cd = row["finance_cd"]
            parent = root_id
            for gname, g_cds in groups.items():
                if cd in g_cds:
                    parent = gname
                    break
            
            d_prev = row.get("d_prev_pp", 0) or 0
            rank_change = row.get("rank_change", 0) or 0
            rank_change_str = f"▲{int(abs(rank_change))}" if rank_change > 0 else (f"▼{int(abs(rank_change))}" if rank_change < 0 else "—")
            rank_val = row.get('rank')
            rank_str = f"{int(rank_val)}/{total_firms}" if pd.notna(rank_val) else f"—/{total_firms}"
            
            ids.append(cd)
            labels.append(f"<b>{_clean_name(namer.finance_label(cd, False))}</b>" if cd == firm_cd_norm else _clean_name(namer.finance_label(cd, False)))
            parents.append(parent)
            values.append(row["share_pct"])
            customdata.append([_format_delta_hover(row.get('d_1y_pp')), _format_delta_hover(row.get('d_2y_pp')), rank_str, rank_change_str])
            colors.append(1 if d_prev > 0 else (-1 if d_prev < 0 else 0))

        fig = go.Figure(go.Treemap(
            ids=ids, labels=labels, parents=parents, values=values, customdata=customdata,
            marker_colors=colors, marker_colorscale=[[0, 'red'], [0.5, 'grey'], [1, 'green']],
            textinfo="label+value",
            hovertemplate="<b>%{label}</b><br>MS: %{value:.2f}%<br>Rank: %{customdata[2]} (Δ%{customdata[3]})<br>Δ1Y: %{customdata[0]} | Δ2Y: %{customdata[1]}<extra></extra>",
            root_color="lightgrey"
        ))
        fig.update_layout(title_text=f"Market Share Breakdown for {base_month}", margin=dict(l=10, r=10, t=30, b=10))

        return fig