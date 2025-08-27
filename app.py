import re
import pickle
from pathlib import Path
from collections import OrderedDict

import pandas as pd
from dash import (Dash, dcc, html, Input, Output, State, ALL, MATCH,
                  no_update, callback_context)
from dash.exceptions import PreventUpdate

from settings import DEFAULTS, PATHS, INDEX_STRING
from _meta.naming import FISISNamer
from _visual.graph_hier_bar import load_hierarchy
from _sections.firm_toolbar import (load_finance_map, make_firm_toolbar,
                                      register_firm_toolbar_callbacks)
from _sections.hier_section import make_hier_sections, register_hier_section_callbacks
from _sections.profit_section import (make_profit_sections,
                                        register_profit_section_callbacks)
from _utils.build_master import load_or_build_master_for_market
from _helpers.filter import _canon_fin_cd_series

# --- 1. SETUP ---
# API_KEY and login-specific helpers are removed

def load_app_resources(paths):
    """Loads app resources like hier, FIN_MAP, and NAMER, using a cache for speed."""
    cache_file = Path(paths["cache_master_csv"]).parent / "app_resources.pkl"
    if cache_file.exists():
        print("Loading cached resources...")
        with open(cache_file, 'rb') as f:
            resources = pickle.load(f)
        return resources['hier'], resources['FIN_MAP'], resources['NAMER']
    else:
        print("Generating and caching resources...")
        hier = load_hierarchy(paths["hier_json"])
        fin_map = load_finance_map(paths["finance_map_csv"])
        namer = FISISNamer.from_csvs(
            paths["within_naming_csv"],
            paths["list_acc_col_map_csv"],
            finance_xml=paths["finance_xml"],
        )
        with open(cache_file, 'wb') as f:
            pickle.dump({'hier': hier, 'FIN_MAP': fin_map, 'NAMER': namer}, f)
        return hier, fin_map, namer

def lists_from_specs(cfgs):
    """Extracts all unique list numbers (e.g., 'SH001') from a list of section configs."""
    pat = re.compile(r"\bSH\d{3}\b")
    out = set()
    for cfg in cfgs:
        specs = cfg.get("spec") or []
        if isinstance(specs, str): specs = [specs]
        for item in specs:
            if isinstance(item, str): out.update(pat.findall(item))
    return sorted(out)

# --- 2. MAIN APP CREATION ---

def create_app():
    app = Dash(__name__, suppress_callback_exceptions=True)
    app.index_string = INDEX_STRING

    # --- Pre-load all necessary resources ONCE ---
    hier, FIN_MAP, NAMER = load_app_resources(PATHS)
    all_section_configs = [sec for group in DEFAULTS["sections"] for sec in group['content']]
    auto_list_nos = lists_from_specs(all_section_configs)

    # --- Build the entire main application layout ONCE ---
    components_by_sec_id = {}
    for group in DEFAULTS["sections"]:
        group_id, configs = group["section_id"], group["content"]
        if group_id == "G":
            group_components = make_hier_sections(configs, hier, NAMER)
        elif group_id == "P":
            group_components = make_profit_sections(configs, NAMER, hier)
        else:
            group_components = []
        for cfg, comp in zip(configs, group_components):
            components_by_sec_id[cfg["sec"]] = comp

    toplevel_tabs, toplevel_content_containers, first_toplevel_tab_value = [], [], None
    for group in DEFAULTS["sections"]:
        group_label = group["section_label"]
        if first_toplevel_tab_value is None: first_toplevel_tab_value = group_label
        toplevel_tabs.append(dcc.Tab(label=group_label, value=group_label, style={'padding': '4px', 'fontSize': '13px'}, selected_style={'padding': '4px', 'fontSize': '13px'}))
        
        inner_sections_by_tab = OrderedDict()
        for cfg in group["content"]:
            tab_name = cfg["title"].split("::", 1)[0].strip()
            if tab_name not in inner_sections_by_tab: inner_sections_by_tab[tab_name] = []
            inner_sections_by_tab[tab_name].append(cfg)
        
        inner_tabs_list, inner_tab_content_list, first_inner_tab_value = [], [], None
        for inner_tab_name, section_cfgs_inner in inner_sections_by_tab.items():
            inner_tab_value = f"tab-{group_label}-{inner_tab_name}"
            if first_inner_tab_value is None: first_inner_tab_value = inner_tab_value
            inner_tabs_list.append(dcc.Tab(label=inner_tab_name, value=inner_tab_value, style={'padding': '2px', 'fontSize': '11px'}, selected_style={'padding': '2px', 'fontSize': '11px'}))
            components_for_this_inner_tab = [components_by_sec_id.get(cfg["sec"]) for cfg in section_cfgs_inner if cfg["sec"] in components_by_sec_id]
            inner_tab_content_list.append(html.Div(id={"type": "inner-content", "group": group_label, "tab": inner_tab_value}, children=components_for_this_inner_tab, style={'display': 'none'}))
        
        toplevel_content = html.Div([dcc.Tabs(id={"type": "inner-tabs", "group": group_label}, value=first_inner_tab_value, children=inner_tabs_list), html.Div(children=inner_tab_content_list)])
        toplevel_content_containers.append(html.Div(id={"type": "toplevel-content", "group": group_label}, children=toplevel_content, style={'display': 'none'}))

    # --- Set the ROOT layout directly to the main application layout ---
    app.layout = html.Div([
        dcc.Store(id="ft-store-master", data=None),
        dcc.Store(id="ft-store-fin-map", data=FIN_MAP.to_dict("records")),
        make_firm_toolbar(FIN_MAP),
        dcc.Tabs(id="toplevel-tabs", value=first_toplevel_tab_value, children=toplevel_tabs),
        html.Div(id="toplevel-content-wrapper", children=toplevel_content_containers)
    ])

    # --- REGISTER ALL CALLBACKS ONCE AT STARTUP ---

    # -- Auth callbacks have been removed --

    # -- Main Data Loading Callback (now a standard callback) --
    @app.callback(
        Output("ft-store-master", "data"),
        Input("ft-store-run-trigger", "data"),
        State("ft-store-run-params", "data"),
        State("toplevel-tabs", "value"),
        State({"type": "inner-tabs", "group": ALL}, "value"),
        prevent_initial_call=True,
    )
    def _on_run(trigger, params, active_toplevel_tab, active_inner_tabs):
        if not trigger or not params: raise PreventUpdate
        
        active_inner_tab = next((v for v in active_inner_tabs if v is not None), None)
        visible_section_cfgs = []
        if active_toplevel_tab and active_inner_tab:
            for group in DEFAULTS["sections"]:
                if group["section_label"] == active_toplevel_tab:
                    for cfg in group["content"]:
                        tab_name = cfg["title"].split("::", 1)[0].strip()
                        current_inner_tab_id = f"tab-{active_toplevel_tab}-{tab_name}"
                        if current_inner_tab_id == active_inner_tab:
                            visible_section_cfgs.append(cfg)
        if not visible_section_cfgs: visible_section_cfgs = all_section_configs

        list_nos_to_load = lists_from_specs(visible_section_cfgs)
        print(f"Loading data for {len(list_nos_to_load)} lists required by the active tab...")
        
        df_master = load_or_build_master_for_market(financeCds=params.get("entireMarket", []), term=params["term"], startBaseMm=params["startBaseMm"], endBaseMm=params["endBaseMm"], listNo=list_nos_to_load, section_cfgs=all_section_configs, hierarchy_json_path=PATHS["hier_json"], cache_path=PATHS["cache_master_csv"])
        df_master["finance_cd"] = _canon_fin_cd_series(df_master["finance_cd"])
        df_master['base_month'] = df_master['base_month'].astype(str)
        
        print("Data loading complete!")
        return df_master.to_dict("records")

    # -- Tab Visibility Callbacks --
    @app.callback(Output({"type": "toplevel-content", "group": ALL}, "style"), Input("toplevel-tabs", "value"), State({"type": "toplevel-content", "group": ALL}, "id"))
    def switch_toplevel_tab_visibility(active_toplevel_tab, tab_ids):
        return [{'display': 'block' if tab_id["group"] == active_toplevel_tab else 'none'} for tab_id in tab_ids]

    @app.callback(Output({"type": "inner-content", "group": MATCH, "tab": ALL}, "style"), Input({"type": "inner-tabs", "group": MATCH}, "value"), State({"type": "inner-content", "group": MATCH, "tab": ALL}, "id"))
    def switch_inner_tab_visibility(active_inner_tab, tab_ids):
        return [{'display': 'block' if tab_id["tab"] == active_inner_tab else 'none'} for tab_id in tab_ids]

    # -- State Reset Callback --
    @app.callback(Output({"type": "level-path", "sec": ALL}, "data", allow_duplicate=True), Output({"type": "ps-level-path", "sec": ALL}, "data", allow_duplicate=True), Output({"type": "compared-firms", "sec": ALL}, "data", allow_duplicate=True), Output({"type": "ps-compared-firms", "sec": ALL}, "data", allow_duplicate=True), Input("toplevel-tabs", "value"), Input({"type": "inner-tabs", "group": ALL}, "value"), prevent_initial_call=True)
    def reset_section_state_on_navigate(toplevel_tab, inner_tabs_values):
        ctx = callback_context
        num_hier_sections = len(ctx.outputs_grouping[0])
        num_profit_sections = len(ctx.outputs_grouping[1])
        num_hier_compared = len(ctx.outputs_grouping[2])
        num_profit_compared = len(ctx.outputs_grouping[3])
        return ([[] for _ in range(num_hier_sections)], [[] for _ in range(num_profit_sections)], [[] for _ in range(num_hier_compared)], [[] for _ in range(num_profit_compared)])

    # -- Register All Section-Specific Callbacks --
    register_firm_toolbar_callbacks(app, FIN_MAP)
    for group in DEFAULTS["sections"]:
        group_id, configs = group["section_id"], group["content"]
        if group_id == "G":
            register_hier_section_callbacks(app, hier, NAMER, list_nos=auto_list_nos, colid=DEFAULTS.get("colid"), term=DEFAULTS.get("term"), section_cfgs=configs, hier_json_path=PATHS["hier_json"], cache_csv_path=PATHS["cache_master_csv"])
        elif group_id == "P":
            register_profit_section_callbacks(app, hier, NAMER, list_nos=auto_list_nos, colid=DEFAULTS.get("colid"), term=DEFAULTS.get("term"), section_cfgs=configs)

    return app

if __name__ == "__main__":
    app = create_app()
    app.run(debug=False, port=8055)