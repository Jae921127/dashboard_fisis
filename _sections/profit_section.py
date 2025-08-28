from dash import dcc, html, Input, Output, State, callback_context, no_update
from dash.dependencies import MATCH, ALL
from dash.exceptions import PreventUpdate
import plotly.graph_objects as go
import pandas as pd
import re
import plotly.express as px
from plotly.subplots import make_subplots

from _analytics.market_share import compute_full_market_share_data
from _visual.graph_hier_bar import (
    node_parent_values, donut_for_hovered_node,
    select_rescaler_from_values, natural_key, months_sorted, parse_custom_nodes, get_children, get_top_level_accounts, values_for_accounts
)
from _visual.line_overlay import _eval_expr_cross_sectional
from _helpers.filter import _canon_fin_cd_value, _filter_master_data_for_section

def _extract_cross_sectional_interaction(event_data):
    """Helper to extract relevant data from cross-sectional plot events."""
    if not event_data or not event_data.get("points"):
        return None, None, None
    
    pt = event_data["points"][0]
    node_label = pt.get("y") 
    custom_data = pt.get("customdata", {})
    node_key = custom_data.get("node_key")
    firm_cd = custom_data.get("firm_cd")
    
    return node_key, firm_cd, node_label

def _section(sec: str, title: str):
    """Builds the static HTML structure for a single Profitability section."""
    return html.Div(className="layout", children=[

        dcc.Store(id={"type": "ps-level-path", "sec": sec}, data=[]),
        dcc.Store(id={"type": "ps-ms-data-store", "sec": sec}, data=None),
        dcc.Store(id={"type": "ps-compared-firms", "sec": sec}, data=[]),
        dcc.Store(id={"type": "ps-selected-colid", "sec": sec}, data=None),
        dcc.Store(id={"type": "ps-section-params-store", "sec": sec}, data=None),
        dcc.Store(id={"type": "ps-last-hovered-month", "sec": sec}, data=None), 
        
        html.Div(className="panel", children=[
            html.Div(className="toolbar-row", style={'justifyContent': 'space-between'}, children=[
                html.Div(className='toolbar-group', children=[
                    html.Button([html.Span("arrow_back", className="icon"), "Back"], id={"type": "ps-btn-back", "sec": sec}, className="btn"),
                    html.Span(title, className="title", style={'marginLeft': '10px'}),
                ]),
                html.Div(id={"type": "ps-colid-selector-container", "sec": sec}, className='toolbar-group')
            ]),
  
            html.Div(style={"display": "flex", "gap": "12px", "alignItems": "stretch", "width": "92%", "marginTop": "10px"},
                children=[
                    html.Div(style={"flex": "2.5", "border": "1px solid #eee", "borderRadius": "10px"}, children=[dcc.Graph(id={"type": "ps-market-share-treemap", "sec": sec}, style={"height": "400px"})]),
                    html.Div(id={"type": "ps-ms-line-plot-container", "sec": sec}, style={"display": "flex", "gap": "8px", "flex": "7.5"}),
                ]
            ),
               
            html.Div(style={"width": "100%", "marginTop":"10px", "border": "1px solid #eee", "borderRadius": "10px"},
                children=[html.Div(id={"type": "ps-hierarchy-line-plot-container", "sec": sec}, style={"display": "flex", "gap": "8px"})]
            ),

            html.Div(style={"width": "100%", "marginTop":"10px", "border": "1px solid #eee", "borderRadius": "10px", "position": "relative"},
                children=[
                     html.Div(id={"type": "ps-cross-sectional-plot-container", "sec": sec}, style={"display": "flex", "gap": "8px"}),
                     html.Div(id={"type": "ps-hover-overlay", "sec": sec}, style={"display": "none"}, children=[
                         dcc.Graph(id={"type": "ps-hover-donut", "sec": sec}, config={"displayModeBar": False, "staticPlot": True}),
                         html.Div(id={"type": "ps-summary-content", "sec": sec}, style={"padding": "8px"})
                     ]),
                ]
            ),
        ]),
    ])

def make_profit_sections(section_cfgs, namer, hier):
    """Creates the layout for all Profitability sections."""
    views = []
    for cfg in section_cfgs:
        v = _section(cfg["sec"], cfg["title"])
        num_sub = cfg.get("sub_sec", 1)
        v.children[4].data = cfg 
        
        ms_container = v.children[6].children[1].children[1]
        hier_line_container = v.children[6].children[2].children[0]
        cross_sec_container = v.children[6].children[3].children[0]

        ms_container.children = [html.Div(id={"type": "ps-ms-subplot-wrapper", "sec": cfg["sec"], "sub": i}, style={'flex': 1}, children=[dcc.Graph(id={"type": "ps-market-share-line-plot", "sec": cfg["sec"], "sub": i}, style={"height": "400px"})]) for i in range(num_sub)]
        hier_line_container.children = [html.Div(id={"type": "ps-hier-line-subplot-wrapper", "sec": cfg["sec"], "sub": i}, style={'flex': 1}, children=[dcc.Graph(id={"type": "ps-hierarchy-line-plot", "sec": cfg["sec"], "sub": i}, style={"height": "400px"}, clear_on_unhover=True)]) for i in range(num_sub)]
        cross_sec_container.children = [html.Div(id={"type": "ps-cross-sec-subplot-wrapper", "sec": cfg["sec"], "sub": i}, style={'flex': 1}, children=[dcc.Graph(id={"type": "ps-cross-sectional-plot", "sec": cfg["sec"], "sub": i}, style={"height": "400px"}, clear_on_unhover=True)]) for i in range(num_sub)]

        colid_options, default_colid = [], None
        if "colid" in cfg and isinstance(cfg["colid"], list) and len(cfg["colid"]) > 1:
            spec_for_naming = (cfg["spec"][0] if isinstance(cfg["spec"], list) else cfg["spec"]).split(" + ")[0]
            list_no_for_naming = spec_for_naming.split(":")[0]

            for col in cfg["colid"]:
                label = namer.column_label(list_no_for_naming, None, col, include_id=False)
                colid_options.append({"label": label, "value": col})
            if colid_options: default_colid = colid_options[0]["value"]
        elif "colid" in cfg:
            default_colid = cfg["colid"][0] if isinstance(cfg["colid"], list) else cfg["colid"]

        
        v.children[3].data = default_colid 
        colid_selector_container = v.children[6].children[0].children[1]
        if colid_options:
            colid_selector_container.children = dcc.RadioItems(
                id={"type": "ps-colid-selector", "sec": cfg["sec"]}, options=colid_options, value=default_colid,
                labelStyle={'display': 'inline-block', 'marginRight': '10px'}, inputStyle={'marginRight': '4px'})
        views.append(v)
    return views

def register_profit_section_callbacks(app, hier, namer, list_nos, colid, term, section_cfgs):
    
    @app.callback(
        Output({"type": "ps-selected-colid", "sec": MATCH}, "data"),
        Input({"type": "ps-colid-selector", "sec": MATCH}, "value"),
        prevent_initial_call=True,
    )
    def _update_selected_colid(selected_colid):
        """Stores the user-selected column ID."""
        return selected_colid

    @app.callback(
        Output({"type": "ps-compared-firms", "sec": MATCH}, "data"),
        Input({"type": "ps-market-share-treemap", "sec": MATCH}, "clickData"),
        State({"type": "ps-compared-firms", "sec": MATCH}, "data"),
        prevent_initial_call=True,
    )
    def _update_compared_firms(clickData, compared_cds):
        """Adds/removes firms to the comparison list on treemap click."""
        if not clickData: raise PreventUpdate
        clicked_id = clickData["points"][0].get("id")
        if clicked_id and clicked_id.isdigit():
            new_list = compared_cds[:] if compared_cds else []
            if clicked_id in new_list: new_list.remove(clicked_id)
            else: new_list.append(clicked_id)
            return new_list
        return no_update

    @app.callback(
        Output({"type": "ps-market-share-line-plot", "sec": MATCH, "sub": ALL}, "figure"),
        Output({"type": "ps-ms-data-store", "sec": MATCH}, "data"),
        Input("ft-store-master", "data"),
        Input({"type": "ps-level-path", "sec": MATCH}, "data"),
        Input({"type": "ps-compared-firms", "sec": MATCH}, "data"),
        Input({"type": "ps-selected-colid", "sec": MATCH}, "data"),
        State("ft-store-run-params", "data"),
        State({"type": "ps-section-params-store", "sec": MATCH}, "data"),
        State("ft-store-selected-firm", "data"),
    )
    def _update_ms_line_plot(master, level_path, compared_cds, selected_colid, run_params, section_cfg, firm_cd):
        num_sub = section_cfg.get("sub_sec", 1)
        mode = section_cfg.get("mode")
        if not master or not run_params or not selected_colid:
            return [go.Figure()] * num_sub, no_update

        df_master = pd.DataFrame(master)
        firm_cd_norm = _canon_fin_cd_value(firm_cd)
        entire_market = run_params.get("entireMarket", [])
        spec_config = section_cfg.get("spec")
        spec_list = [spec_config] if isinstance(spec_config, str) else (spec_config or [])
        
        treemap_spec_str = (spec_list[0] or "").split(' + ')[0]
        treemap_nodes = parse_custom_nodes(treemap_spec_str, hier) if not level_path else None
        treemap_ms_data = compute_full_market_share_data(df_master, hier_by_list=hier, list_nos=list_nos, colid=selected_colid, level_path=level_path, entire_market_cds=entire_market, groups=run_params.get("groups", {}), custom_nodes=treemap_nodes)
        final_df_for_treemap = treemap_ms_data["per_firm"]
        
        all_figs = []
        color_palette = px.colors.qualitative.Plotly


        for i in range(num_sub):
            fig_sub = go.Figure()
            spec_for_subplot = spec_list[i] if i < len(spec_list) else ""
            
            spec_L_str, spec_R_str = "", ""
            if mode == 'side-by-side':
                parts = [p.strip() for p in spec_for_subplot.split('+')]
                spec_L_str = parts[0] if len(parts) > 0 else ""
                spec_R_str = parts[1] if len(parts) > 1 else ""
            else: # account_horizontal
                spec_L_str = spec_for_subplot

            list_name_L = namer.list_label(spec_L_str.split(':')[0], include_id=False) if spec_L_str else "L"
            list_name_R = namer.list_label(spec_R_str.split(':')[0], include_id=False) if spec_R_str else "R"

            data_L, data_R = pd.DataFrame(), pd.DataFrame()
            if spec_L_str:
                nodes_L = parse_custom_nodes(spec_L_str, hier) if not level_path else None
                ms_data_L = compute_full_market_share_data(df_master, hier_by_list=hier, list_nos=list_nos, colid=selected_colid, level_path=level_path, entire_market_cds=entire_market, groups=run_params.get("groups", {}), custom_nodes=nodes_L)
                data_L = ms_data_L["per_firm"]
            
            if spec_R_str:
                nodes_R = parse_custom_nodes(spec_R_str, hier) if not level_path else None
                ms_data_R = compute_full_market_share_data(df_master, hier_by_list=hier, list_nos=list_nos, colid=selected_colid, level_path=level_path, entire_market_cds=entire_market, groups=run_params.get("groups", {}), custom_nodes=nodes_R)
                data_R = ms_data_R["per_firm"]
            
            date_range = (section_cfg.get("date") or [["start", "end"]])[i]
            start_date, end_date = date_range[0], date_range[1]
            if start_date == 'start': start_date = run_params.get("startBaseMm")
            if end_date == 'end': end_date = run_params.get("endBaseMm")
            
            if not data_L.empty: data_L = data_L[(data_L['base_month'] >= start_date) & (data_L['base_month'] <= end_date)]
            if not data_R.empty: data_R = data_R[(data_R['base_month'] >= start_date) & (data_R['base_month'] <= end_date)]

            entities_to_plot = [firm_cd_norm] + (compared_cds or [])
            for entity_idx, entity_cd in enumerate(entities_to_plot):
                if not entity_cd: continue
                is_main_firm = (entity_cd == firm_cd_norm)
                entity_name = namer.finance_label(entity_cd, False)
                color = "#1f77b4" if is_main_firm else color_palette[(entity_idx) % len(color_palette)]
                
                if not data_L.empty:
                    df_trace_L = data_L[data_L["finance_cd"] == entity_cd]
                    if not df_trace_L.empty:
                        fig_sub.add_trace(go.Scatter(x=df_trace_L["base_month"], y=df_trace_L["share_pct"], name=f"{entity_name} ({list_name_L})", mode='lines+markers' if is_main_firm else 'lines', line=dict(width=3 if is_main_firm else 2, color=color, dash='solid')))
                if not data_R.empty:
                    df_trace_R = data_R[data_R["finance_cd"] == entity_cd]
                    if not df_trace_R.empty:
                        fig_sub.add_trace(go.Scatter(x=df_trace_R["base_month"], y=df_trace_R["share_pct"], name=f"{entity_name} ({list_name_R})", mode='lines+markers' if is_main_firm else 'lines', line=dict(width=3 if is_main_firm else 2, color=color, dash='dash')))

            fig_sub.update_layout(title_text="M/S Trend", yaxis_ticksuffix="%", hovermode="x unified", margin=dict(l=20,r=20,t=40,b=20), showlegend=(i==0), legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0))
            all_figs.append(fig_sub)
            
        return all_figs, final_df_for_treemap.to_dict("records")

    @app.callback(
        Output({"type": "ps-market-share-treemap", "sec": MATCH}, "figure"),
        Input({"type": "ps-market-share-line-plot", "sec": MATCH, "sub": ALL}, "hoverData"),
        State({"type": "ps-ms-data-store", "sec": MATCH}, "data"),
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
        base_month = str(hoverData["points"][0]["x"])
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
                if cd in g_cds: parent = gname; break
            d_prev = row.get("d_prev_pp", 0) or 0
            rank_change = row.get("rank_change", 0) or 0
            rank_change_str = f"▲{int(abs(rank_change))}" if rank_change > 0 else (f"▼{int(abs(rank_change))}" if rank_change < 0 else "—")
            rank_val = row.get('rank'); rank_str = f"{int(rank_val)}/{total_firms}" if pd.notna(rank_val) else f"—/{total_firms}"
            ids.append(cd)
            labels.append(f"<b>{_clean_name(namer.finance_label(cd, False))}</b>" if cd == firm_cd_norm else _clean_name(namer.finance_label(cd, False)))
            parents.append(parent); values.append(row["share_pct"])
            customdata.append([_format_delta_hover(row.get('d_1y_pp')), _format_delta_hover(row.get('d_2y_pp')), rank_str, rank_change_str])
            colors.append(1 if d_prev > 0 else (-1 if d_prev < 0 else 0))

        fig = go.Figure(go.Treemap(
            ids=ids, labels=labels, parents=parents, values=values, customdata=customdata,
            marker_colors=colors, marker_colorscale=[[0, 'red'], [0.5, 'grey'], [1, 'green']], textinfo="label+value",
            hovertemplate="<b>%{label}</b><br>MS: %{value:.2f}%<br>Rank: %{customdata[2]} (Δ%{customdata[3]})<br>Δ1Y: %{customdata[0]} | Δ2Y: %{customdata[1]}<extra></extra>",
            root_color="lightgrey"
        ))
        fig.update_layout(title_text=f"Market Share Breakdown for {base_month}", margin=dict(l=10, r=10, t=30, b=10))
        return fig
    
    @app.callback(
        Output({"type": "ps-last-hovered-month", "sec": MATCH}, "data"),
        Input({"type": "ps-hierarchy-line-plot", "sec": MATCH, "sub": ALL}, "hoverData"),
        prevent_initial_call=True,
    )
    def _store_hovered_month(hoverData_list):
        """Stores the month hovered on the hierarchy time-series plot."""
        hoverData = next((h for h in hoverData_list if h), None)
        if hoverData and hoverData.get("points"):
            return str(hoverData["points"][0]["x"])
        raise PreventUpdate

    @app.callback(
        Output({"type": "ps-hierarchy-line-plot", "sec": MATCH, "sub": ALL}, "figure"),
        Input("ft-store-master", "data"),
        Input({"type": "ps-level-path", "sec": MATCH}, "data"),
        Input({"type": "ps-compared-firms", "sec": MATCH}, "data"),
        Input({"type": "ps-selected-colid", "sec": MATCH}, "data"),
        State("ft-store-run-params", "data"),
        State({"type": "ps-section-params-store", "sec": MATCH}, "data"),
        State("ft-store-selected-firm", "data"),
    )
    def _update_hierarchy_line_plot(master, level_path, compared_cds, selected_colid, run_params, section_cfg, firm_cd):
        num_sub = section_cfg.get("sub_sec", 1)
        if not master or not run_params or not selected_colid: return [go.Figure()] * num_sub
        df_master = pd.DataFrame(master)
        firm_cd_norm = _canon_fin_cd_value(firm_cd)
        all_figs = []
        firms_to_plot = [firm_cd_norm] if firm_cd_norm else []
        if compared_cds: firms_to_plot.extend([cd for cd in compared_cds if cd not in firms_to_plot])
        line_styles = [{'dash': 'solid', 'width': 3}, {'dash': 'dot', 'width': 2}, {'dash': 'dashdot', 'width': 2}, {'dash': 'longdash', 'width': 2}]
        colors = px.colors.qualitative.Plotly

        spec_config = section_cfg.get("spec")
        spec_list = [spec_config] if isinstance(spec_config, str) else (spec_config or [])
    
        
        
        for i in range(num_sub):
            spec_for_subplot = spec_list[i] if i < len(spec_list) else ""
            fig_sub = go.Figure()
            mode = section_cfg.get("mode")
            date_range = (section_cfg.get("date") or [["start", "end"]])[i]
            start_date, end_date = date_range[0], date_range[1]
            if start_date == 'start': start_date = run_params.get("startBaseMm")
            if end_date == 'end': end_date = run_params.get("endBaseMm")

            traces_to_add = []
            all_values_for_scaling = []
            color_map = {}
            if mode == 'account_horizontal':
                first_firm_df = df_master[df_master.finance_cd == firms_to_plot[0]] if firms_to_plot else pd.DataFrame()
                if not first_firm_df.empty:
                    nodes_for_level = parse_custom_nodes(spec_for_subplot, hier) if not level_path else None
                    _, canonical_nodes, _ = node_parent_values(first_firm_df, hier, list_nos, selected_colid, level_path, custom_nodes=nodes_for_level, mode=mode)
                    color_map = {node_id: colors[idx % len(colors)] for idx, node_id in enumerate(canonical_nodes)}
            
            for firm_idx, current_firm_cd in enumerate(firms_to_plot):
                firm_df = df_master[df_master.finance_cd == current_firm_cd]
                if firm_df.empty: continue
                firm_name = namer.finance_label(current_firm_cd, include_id=False)
                style = line_styles[firm_idx % len(line_styles)]
                spec_for_subplot = (section_cfg.get("spec") or [""])[i]

                if mode == 'side-by-side':
                    parts = [p.strip() for p in spec_for_subplot.split('+')]
                    spec_L_str, spec_R_str = (parts[0] if len(parts) > 0 else ""), (parts[1] if len(parts) > 1 else "")
                    
                      list_name_L = namer.list_label(spec_L_str.split(':')[0], include_id=False) if spec_L_str else "L"
                    list_name_R = namer.list_label(spec_R_str.split(':')[0], include_id=False) if spec_R_str else "R"

                    if spec_L_str:
                        list_no_L = parse_custom_nodes(spec_L_str, hier)[0].split(":")[1]
                        path_L = [f"acc:{list_no_L}:{p}" for p in level_path]
                        nodes_L = parse_custom_nodes(spec_L_str, hier)
                        _, _, parent_vals_L = node_parent_values(firm_df, hier, [list_no_L], selected_colid, level_path, custom_nodes=nodes_L, mode=mode)
                        series_L = parent_vals_L.groupby('base_month')['value'].sum()
                        series_filtered_L = series_L[(series_L.index >= start_date) & (series_L.index <= end_date)]
                        all_values_for_scaling.extend(series_filtered_L.values)
                        traces_to_add.append({'series': series_filtered_L, 'name': f"{firm_name} ({list_name_L})", 'line': dict(dash='solid', color=colors[firm_idx])})

                    if spec_R_str:
                        list_no_R = parse_custom_nodes(spec_R_str, hier)[0].split(":")[1]
                        path_R = [f"acc:{list_no_R}:{p}" for p in level_path]
                        nodes_R = parse_custom_nodes(spec_R_str, hier)
                        _, _, parent_vals_R = node_parent_values(firm_df, hier, [list_no_R], selected_colid, level_path, custom_nodes=nodes_R, mode=mode)
                        series_R = parent_vals_R.groupby('base_month')['value'].sum()
                        series_filtered_R = series_R[(series_R.index >= start_date) & (series_R.index <= end_date)]
                        all_values_for_scaling.extend(series_filtered_R.values)
                        traces_to_add.append({'series': series_filtered_R, 'name': f"{firm_name} ({list_name_R})", 'line': dict(dash='dash', color=colors[firm_idx])})

                else: # account_horizontal
                    nodes_for_level = parse_custom_nodes(spec_for_subplot, hier) if not level_path else None
                    _, current_nodes, parent_vals = node_parent_values(firm_df, hier, list_nos, selected_colid, level_path, custom_nodes=nodes_for_level, mode=mode)
                    
                    for node_id in current_nodes:
                        df_trace = parent_vals[parent_vals['node_id'] == node_id]
                        df_trace = df_trace[(df_trace['base_month'] >= start_date) & (df_trace['base_month'] <= end_date)]
                        if df_trace.empty: continue
                        try: 
                            _, listno, accd = node_id.split(":"); trace_name = namer.account_label(listno, accd, descendent=False, include_id=False)
                        except: trace_name = node_id
                        
                        series = df_trace.set_index('base_month')['value']
                        all_values_for_scaling.extend(series.values)
                        traces_to_add.append({'series': series, 'name': f"{trace_name} ({firm_name})", 'mode': 'lines', 'line': dict(dash=style['dash'], width=style['width'], color=color_map.get(node_id))})

            scale, unit_lab = select_rescaler_from_values(all_values_for_scaling)
            rep_list_no = (section_cfg.get("spec", [""])[0] or "").split(':')[0].split(' + ')[0]
            y_axis_title = namer.column_label(rep_list_no, None, selected_colid, include_id=False)
            if unit_lab:
                y_axis_title = f"{y_axis_title} ({unit_lab})"


            for trace_data in traces_to_add:
                series = trace_data.pop("series")
                fig_sub.add_trace(go.Scatter(
                    x=series.index, y=[v / scale for v in series.values], **trace_data
                ))

            fig_sub.update_layout(title_text="Time-Series of Current Hierarchy Level", yaxis_title=y_axis_title, hovermode="x unified", margin=dict(l=20,r=20,t=40,b=20), showlegend=True, legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0))
            all_figs.append(fig_sub)
            
        return all_figs
    
    @app.callback(
        Output({"type": "ps-cross-sectional-plot", "sec": MATCH, "sub": ALL}, "figure"),
        Input("ft-store-master", "data"),
        Input({"type": "ps-level-path", "sec": MATCH}, "data"),
        Input({"type": "ps-compared-firms", "sec": MATCH}, "data"),
        Input({"type": "ps-selected-colid", "sec": MATCH}, "data"),
        Input({"type": "ps-last-hovered-month", "sec": MATCH}, "data"),
        State("ft-store-run-params", "data"),
        State({"type": "ps-section-params-store", "sec": MATCH}, "data"),
    )
    def _update_cross_sectional_plot(master, level_path, compared_cds, selected_colid, hovered_month, run_params, section_cfg):
        num_sub = section_cfg.get("sub_sec", 1)
        if not master or not run_params or not selected_colid: return [go.Figure()] * num_sub
        df_master = pd.DataFrame(master)
        all_figs = []
        main_firm_cd = _canon_fin_cd_value(run_params.get("financeCd"))
        firms_to_plot = [main_firm_cd] if main_firm_cd else []
        if compared_cds: firms_to_plot.extend([cd for cd in compared_cds if cd not in firms_to_plot])
        patterns = ["", "x", "/", ".", "-"]
        colors = px.colors.qualitative.Plotly
        
        spec_config = section_cfg.get("spec")
        spec_list = [spec_config] if isinstance(spec_config, str) else (spec_config or [])
        

        for i in range(num_sub):
            spec_for_subplot = spec_list[i] if i < len(spec_list) else ""
            base_month = hovered_month or (months_sorted(df_master)[-1] if not df_master.empty else None)
            if not base_month:
                all_figs.append(go.Figure()); continue
            mode = section_cfg.get("mode")
            spec_list = (section_cfg.get("spec") or [""])
            fig_sub = None

            if mode == 'account_horizontal':
                fig_sub = go.Figure()

                spec_str_for_subplot = spec_list[i if num_sub > 1 else 0]
                if level_path:
                    _, parent_list_no, parent_acd = level_path[-1].split(":")
                    child_nodes_acd = get_children(hier.get(parent_list_no, {}), parent_acd)
                else:
                    nodes = parse_custom_nodes(spec_str_for_subplot, hier)
                    parent_list_no = nodes[0].split(":")[1]
                    child_nodes_acd = [n.split(":")[2] for n in nodes]

                if not child_nodes_acd:
                    all_figs.append(go.Figure()); continue
                
                y_labels_map = {acd: namer.account_label(parent_list_no, acd, descendent=False, include_id=False) for acd in child_nodes_acd}
                y_categories_sorted = sorted(y_labels_map.keys(), key=lambda k: natural_key(y_labels_map[k]))
                y_labels_sorted = [y_labels_map[cat] for cat in y_categories_sorted]

                color_map = {acd: colors[idx % len(colors)] for idx, acd in enumerate(y_categories_sorted)}

                for firm_idx, current_firm_cd in enumerate(firms_to_plot):
                    firm_df = df_master[df_master.finance_cd == current_firm_cd]
                    if firm_df.empty: continue
                    
                    _, _, parent_vals = node_parent_values(firm_df, hier, [parent_list_no], selected_colid, level_path)
                    month_vals = parent_vals[parent_vals.base_month == base_month].set_index('node_id')
                    
                    x_values = [month_vals.loc[acd, "value"] if acd in month_vals.index else 0 for acd in y_categories_sorted]
                    firm_name = namer.finance_label(current_firm_cd, include_id=False)
                    bar_colors = [color_map.get(acd) for acd in y_categories_sorted]
                    
                    fig_sub.add_trace(go.Bar(
                        y=y_labels_sorted, x=x_values, name=firm_name, orientation='h',
                        marker=dict(color=bar_colors, pattern=dict(shape=patterns[firm_idx % len(patterns)])), # Apply colors here
                        customdata=[{"node_key": f"acc:{parent_list_no}:{cat}", "firm_cd": current_firm_cd} for cat in y_categories_sorted]
                    ))
                fig_sub.update_layout(barmode='group', title_text=f"Composition for {base_month}", yaxis={'categoryorder':'array', 'categoryarray': y_labels_sorted}, margin=dict(l=10,r=10,t=30,b=10))



            elif mode == 'side-by-side':
                fig_sub = make_subplots(rows=1, cols=2, specs=[[{}, {}]], shared_yaxes=True, horizontal_spacing=0.0)
                spec_for_subplot = (section_cfg.get("spec") or [""])[i]
                parts = [p.strip() for p in spec_for_subplot.split('+')]
                spec1_str, spec2_str = (parts[0] if len(parts) > 0 else ""), (parts[1] if len(parts) > 1 else "")
                
                if not spec1_str or not spec2_str:
                    all_figs.append(go.Figure()); continue
                
                if level_path:
                    parent_acd = level_path[-1]
                    list1_no = parse_custom_nodes(spec1_str, hier)[0].split(":")[1]
                    list2_no = parse_custom_nodes(spec2_str, hier)[0].split(":")[1]
                    y_nodes_acd = get_children(hier.get(list1_no, {}), parent_acd)
                else:
                    nodes1, nodes2 = parse_custom_nodes(spec1_str, hier), parse_custom_nodes(spec2_str, hier)
                    list1_no = nodes1[0].split(":")[1]
                    list2_no = nodes2[0].split(":")[1]
                    y_nodes_acd = get_top_level_accounts(hier.get(list1_no, {}))

                if not y_nodes_acd:
                    all_figs.append(go.Figure()); continue

                y_labels_map = {acd: namer.account_label(list1_no, acd, descendent=False, include_id=False) for acd in y_nodes_acd}
                y_categories_sorted_acd = sorted(y_labels_map.keys(), key=lambda k: natural_key(y_labels_map[k]))
                y_labels_sorted = [y_labels_map[k] for k in y_categories_sorted_acd]
                all_vals_for_scaling = []
                data_to_plot = []
                for firm_idx, current_firm_cd in enumerate(firms_to_plot):
                    firm_df = df_master[df_master.finance_cd == current_firm_cd]
                    if firm_df.empty: continue

                    path_L = [f"acc:{list1_no}:{p}" for p in level_path]
                    path_R = [f"acc:{list2_no}:{p}" for p in level_path]

                    _, _, vals1 = node_parent_values(firm_df, hier, [list1_no], selected_colid, level_path, mode=mode)
                    _, _, vals2 = node_parent_values(firm_df, hier, [list2_no], selected_colid, level_path, mode=mode)
                    month_vals1 = vals1[vals1.base_month == base_month].set_index('node_id')
                    month_vals2 = vals2[vals2.base_month == base_month].set_index('node_id')

                    x_vals1 = [month_vals1.loc[acd, "value"] if acd in month_vals1.index else 0 for acd in y_categories_sorted_acd]
                    x_vals2 = [month_vals2.loc[acd, "value"] if acd in month_vals2.index else 0 for acd in y_categories_sorted_acd]
                    
                    all_vals_for_scaling.extend(x_vals1)
                    all_vals_for_scaling.extend(x_vals2)
                    data_to_plot.append({"firm_cd": current_firm_cd, "x1": x_vals1, "x2": x_vals2})

                max_abs_val = max(abs(v) for v in all_vals_for_scaling) if all_vals_for_scaling else 1
                scale, unit_lab = select_rescaler_from_values(all_vals_for_scaling)
                axis_limit = (max_abs_val / scale) * 1.1 if scale != 0 else max_abs_val * 1.1

                for firm_data in data_to_plot:
                    current_firm_cd = firm_data["firm_cd"]
                    firm_name = namer.finance_label(current_firm_cd, include_id=False)
                    pattern = patterns[firms_to_plot.index(current_firm_cd) % len(patterns)]
                    
                    x_vals1_scaled = [v / scale for v in firm_data["x1"]]
                    x_vals2_scaled = [v / scale for v in firm_data["x2"]]
                    
                    customdata1 = [{"node_key": f"acc:{list1_no}:{acd}", "firm_cd": current_firm_cd} for acd in y_categories_sorted_acd]
                    customdata2 = [{"node_key": f"acc:{list2_no}:{acd}", "firm_cd": current_firm_cd} for acd in y_categories_sorted_acd]

                    fig_sub.add_trace(go.Bar(name=f"{firm_name} (L)", y=y_labels_sorted, x=x_vals1_scaled, orientation='h', marker_color='mediumseagreen', marker=dict(pattern=dict(shape=pattern)), customdata=customdata1, showlegend=True), row=1, col=1)
                    fig_sub.add_trace(go.Bar(name=f"{firm_name} (R)", y=y_labels_sorted, x=x_vals2_scaled, orientation='h', marker_color='indianred', marker=dict(pattern=dict(shape=pattern)), customdata=customdata2, showlegend=False), row=1, col=2)

                expr = (section_cfg.get("expr") or [""])[i] if "expr" in section_cfg and isinstance(section_cfg["expr"], list) else section_cfg.get("expr")
                if expr:
                    expr_nm = (section_cfg.get("expr_nm") or [""])[i] if "expr_nm" in section_cfg and isinstance(section_cfg["expr_nm"], list) else section_cfg.get("expr_nm")
                    main_firm_df = df_master[df_master.finance_cd == main_firm_cd]
                    if not main_firm_df.empty:
                        overlay_values_map = _eval_expr_cross_sectional(main_firm_df, expr, selected_colid, account_cds=y_categories_sorted_acd, base_month=base_month)
                        for idx, acd in enumerate(y_categories_sorted_acd):
                            val = overlay_values_map.get(acd)
                            if val is not None:
                                fig_sub.add_annotation(
                                    x=0, y=y_labels_sorted[idx], text=f"{val:,.2f}",
                                    showarrow=False, xref=f"x{1}", yref="y1",
                                    font=dict(color="black", size=10), bgcolor="rgba(255, 255, 255, 0.7)"
                                )

                list1_name = namer.list_label(list1_no, include_id=False)
                list2_name = namer.list_label(list2_no, include_id=False)

                value_axis_title = namer.column_label(list1_no, None, selected_colid, include_id=False)
                if unit_lab:
                    value_axis_title = f"{value_axis_title} ({unit_lab})"

                tick_values = pd.to_numeric(pd.cut(pd.Series([-axis_limit*scale, axis_limit*scale]), bins=5).unique().categories.right)
                tick_labels = [f'{abs(v/scale):,.0f}' for v in tick_values]

                fig_sub.update_layout(
                    title_text=f"Side-by-Side View for {base_month}",
                    barmode='group',
                    yaxis=dict(categoryorder='array', categoryarray=y_labels_sorted, showticklabels=True),
                    margin=dict(l=10, r=10, t=40, b=10),
                    showlegend=False
                )
                fig_sub.update_xaxes(title_text=f"{list1_name} | {value_axis_title}", range=[axis_limit, 0], tickvals=tick_values/scale, ticktext=tick_labels, row=1, col=1)
                fig_sub.update_xaxes(title_text=f"{list2_name} | {value_axis_title}", range=[0, axis_limit], tickvals=tick_values/scale, ticktext=tick_labels, row=1, col=2)

            if fig_sub: all_figs.append(fig_sub)
            else: all_figs.append(go.Figure())
        return all_figs


    @app.callback(
        Output({"type": "ps-level-path", "sec": MATCH}, "data"),
        Input({"type": "ps-cross-sectional-plot", "sec": MATCH, "sub": ALL}, "clickData"),
        Input({"type": "ps-btn-back", "sec": MATCH}, "n_clicks"),
        State({"type": "ps-level-path", "sec": MATCH}, "data"),
        State({"type": "ps-section-params-store", "sec": MATCH}, "data"), 
        prevent_initial_call=True,
    )
    def _nav_section(clickData_list, back_clicks, level_path, section_cfg):
        """Handles drill-down and back navigation."""
        ctx = callback_context
        if not ctx.triggered: raise PreventUpdate
        triggered_id = ctx.triggered_id

        if isinstance(triggered_id, str) and "ps-btn-back" in triggered_id:
            return (level_path or [])[:-1] # Go back one level

        if isinstance(triggered_id, dict) and triggered_id.get("type") == "ps-cross-sectional-plot":
            clickData = next((c for c in clickData_list if c), None)
            if not clickData: raise PreventUpdate
            node_key, _, _ = _extract_cross_sectional_interaction(clickData)
            if not node_key: raise PreventUpdate
            
            try:
                _, list_no, acd = node_key.split(":")
                if get_children(hier.get(list_no, {}), acd):
                    mode = section_cfg.get("mode")
                    if mode == 'side-by-side':
                        path_to_add = acd
                    else:
                        path_to_add = node_key

                    return (level_path or []) + [path_to_add]
                else: 
                    return no_update 
            except: return no_update

        return no_update


    @app.callback(
        Output({"type": "ps-hover-donut", "sec": MATCH}, "figure"),
        Output({"type": "ps-hover-overlay", "sec": MATCH}, "style"),
        Output({"type": "ps-summary-content", "sec": MATCH}, "children"),
        Input({"type": "ps-cross-sectional-plot", "sec": MATCH, "sub": ALL}, "hoverData"),
        State("ft-store-master", "data"),
        State({"type": "ps-selected-colid", "sec": MATCH}, "data"),
        State({"type": "ps-last-hovered-month", "sec": MATCH}, "data"),
        State({"type": "ps-section-params-store", "sec": MATCH}, "data"),
        prevent_initial_call=True,
    )
    def _update_hover_overlays(hoverData_list, master, selected_colid, hovered_month, section_cfg):
        hoverData = next((h for h in hoverData_list if h), None)
        if not hoverData or not master or not hovered_month or not selected_colid:
            return go.Figure(), {"display": "none"}, no_update

        point_data = hoverData["points"][0]
        node_key, firm_cd, hovered_label = _extract_cross_sectional_interaction(hoverData)
        if not node_key or not firm_cd: return go.Figure(), {"display": "none"}, no_update
        
        df_master = pd.DataFrame(master)
        df_scope = df_master[df_master.finance_cd == firm_cd]
        if df_scope.empty: return go.Figure(), {"display": "none"}, no_update

        if section_cfg.get("mode") == 'side-by-side':
            try:
                spec_for_subplot = section_cfg.get("spec")[point_data['curveNumber'] // 2]
                parts = [p.strip() for p in spec_for_subplot.split('+')]
                list1_no, list2_no = parse_custom_nodes(parts[0], hier)[0].split(":")[1], parse_custom_nodes(parts[1], hier)[0].split(":")[1]
                hover_list, hover_acd = node_key.split(":")[1], node_key.split(":")[2]
                key_L, key_R = (f"acc:{list1_no}:{hover_acd}", f"acc:{list2_no}:{hover_acd}")

                donut_fig = make_subplots(rows=1, cols=2, specs=[[{'type': 'pie'}, {'type': 'pie'}]], subplot_titles=(namer.list_label(list1_no, False), namer.list_label(list2_no, False)), horizontal_spacing=0.05)
                donut_L_full_fig, _, _, _ = donut_for_hovered_node(hier, df_scope, selected_colid, key_L, hovered_month, namer=namer)
                donut_fig.add_trace(donut_L_full_fig.data[0], row=1, col=1)
                donut_R_full_fig, _, _, _ = donut_for_hovered_node(hier, df_scope, selected_colid, key_R, hovered_month, namer=namer)
                donut_fig.add_trace(donut_R_full_fig.data[0], row=1, col=2)
                donut_fig.update_layout(showlegend=True, margin=dict(l=10, r=10, t=30, b=10), height=250)

                def get_summary_data(n_key):
                    try:
                        _, ln, acd = n_key.split(":")
                        children = get_children(hier.get(ln, {}), acd)
                        if not children: return []
                        vals = values_for_accounts(df_scope[df_scope.list_no == ln], children, selected_colid)
                        month_vals = vals[vals.base_month == hovered_month].groupby("account_cd")["value"].sum()
                        return sorted([(namer.account_label(ln, c, descendent=True, include_id=False), month_vals.get(c, 0)) for c in children], key=lambda x: natural_key(x[0]))
                    except: return []

                summary_data_L, summary_data_R = get_summary_data(key_L), get_summary_data(key_R)
                all_summary_values = [v for _, v in summary_data_L] + [v for _, v in summary_data_R]
                scale, unit_lab = select_rescaler_from_values(all_summary_values)
                
                def format_summary_html(data, title):
                    rows = [html.B(title, style={'fontSize': '11px'})]
                    total = sum(abs(v) for _, v in data) or 1.0
                    for lbl, val in data:
                        rows.append(html.Div(f"{lbl}: {val/scale:,.1f} ({abs(val)/total:.1%})", style={'fontSize': '10px'}))
                    return html.Div(rows, style={'flex': 1, 'padding': '0 5px'})

                summary_title = html.Div(f"{hovered_label} Composition" + (f" ({unit_lab})" if unit_lab else ""), className="title")
                summary_content = html.Div([
                    summary_title,
                    html.Div([format_summary_html(summary_data_L, namer.list_label(list1_no, False)), 
                            format_summary_html(summary_data_R, namer.list_label(list2_no, False))], 
                            style={'display': 'flex', 'marginTop': '5px'})
                ])
            except Exception:
                return no_update, {"display": "none"}, no_update
        else:
            donut_fig, _, _, _ = donut_for_hovered_node(hier, df_scope, selected_colid, node_key, hovered_month, namer=namer)
            
            summary_items = []
            try:
                _, list_no, acd = node_key.split(":")
                children = get_children(hier.get(list_no, {}), acd)
                if children:
                    vals = values_for_accounts(df_scope, children, selected_colid)
                    month_vals = vals[vals.base_month == hovered_month].groupby("account_cd")["value"].sum()
                    summary_items = sorted([(namer.account_label(list_no, c, descendent=True, include_id=False), month_vals.get(c, 0)) for c in children], key=lambda x: natural_key(x[0]))
            except:
                summary_items = []
            
            all_summary_values = [v for _, v in summary_items]
            scale, unit_lab = select_rescaler_from_values(all_summary_values)
            total = sum(abs(v) for v in all_summary_values) or 1.0

            summary_title_text = f"{hovered_label} Composition"
            if unit_lab: summary_title_text += f" ({unit_lab})"

            summary_rows = [html.Div(className="kv", children=[
                html.Span(lbl),
                html.Span(f"{val/scale:,.1f} ({abs(val)/total:.1%})", className="mono")
            ]) for lbl, val in summary_items]

            summary_content = [html.Div(summary_title_text, className="title")] + summary_rows

        active_overlay_style = {
            "display": "block", "position": "absolute", "zIndex": 10,
            "background": "rgba(255, 255, 255, 0.85)", "borderRadius": "12px", 
            "boxShadow": "0 6px 16px rgba(0,0,0,0.15)", "width": "450px", "padding": "8px",
            "pointerEvents": "none"
        }
        
        try:
            y_frac = 1 - (point_data.get("pointNumber", 0) / len(point_data.get("fullData", {}).get("y", [1,1])))
            if y_frac > 0.6: active_overlay_style.update({'top': '8px', 'bottom': 'auto'})
            else: active_overlay_style.update({'bottom': '8px', 'top': 'auto'})
        except:
            active_overlay_style.update({'top': '8px', 'bottom': 'auto'})

        return donut_fig, active_overlay_style, summary_content
