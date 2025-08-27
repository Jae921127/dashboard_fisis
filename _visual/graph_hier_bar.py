# graph_hier_bar.py
from __future__ import annotations
import re, json
from typing import Dict, List, Optional, Tuple
from pathlib import Path
from plotly.colors import qualitative


import pandas as pd
import plotly.graph_objects as go

BAR_HEIGHT = 300
DONUT_HEIGHT = 300
RESCALE_CHOICES = [(1_000_000_000_000, "조"), (1_000_000_000, "십억"), (1_000_000, "백만"), (1_000, "천")]
TITLE_FS = 12
AXIS_TITLE_FS = 11
LEGEND_FS = 8
TICK_FS = 8
ANNOT_FS = 12




# ---------- small utils ----------
def natural_key(s: str):
    return [int(t) if t.isdigit() else t for t in re.split(r'(\d+)', str(s))]

def ensure_numeric(v):
    try:
        return float(v)
    except Exception:
        return 0.0

def months_sorted(df: pd.DataFrame) -> List[str]:
    return sorted({str(x) for x in df["base_month"].unique()})



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

def apply_min_share_matrix(y_by_node: Dict[str, List[float]], min_share: float = 0.01) -> Dict[str, List[float]]:
    """
    Enforce that, for each month and for each side (pos/neg) separately,
    any nonzero component has at least min_share of that side’s absolute sum.
    Totals are preserved by proportionally shrinking the others.
    """
    if not y_by_node:
        return {}
    months_len = len(next(iter(y_by_node.values())))
    out = {k: [0.0]*months_len for k in y_by_node}

    nodes = list(y_by_node.keys())
    for i in range(months_len):
        col = {n: ensure_numeric(y_by_node[n][i]) for n in nodes}
        for sign in (+1, -1):
            group = {n: v for n, v in col.items() if (v > 0 if sign > 0 else v < 0)}
            if not group:
                continue
            sum_abs = sum(abs(v) for v in group.values())
            if sum_abs == 0:
                continue

            # Cap min_share so it's feasible: t * k <= 1
            k = len(group)
            t = min_share if min_share * k <= 1.0 else (1.0 / k)

            # Required abs after threshold
            req_abs = {n: max(abs(v), t * sum_abs) for n, v in group.items()}
            total_req = sum(req_abs.values())

            # If total grows, scale all back to fit exactly
            scale_back = sum_abs / total_req if total_req > 0 else 1.0

            for n, v in group.items():
                adj_abs = req_abs[n] * scale_back
                out[n][i] = adj_abs if sign > 0 else -adj_abs

        # zero-valued nodes remain zero for this month
    return out

def load_hierarchy(hier_json_path: str | Path = "_local/fisis_hierarchy.json") -> Dict[str, dict]:
    with open(hier_json_path, "r", encoding="utf-8") as f:
        return json.load(f)

def list_label(hier_by_list: Dict[str, dict], list_no: str) -> str:
    nm = (hier_by_list.get(list_no) or {}).get("list_nm", "")
    return f"{list_no} · {nm}" if nm else list_no

def parse_custom_nodes(spec: str, hier: dict) -> List[str]:
    """
    Parses the spec string with context-aware logic:
    - "SH001 + SH002" -> ['list:SH001', 'list:SH002'] (shows list totals)
    - "SH022"         -> ['acc:SH022:A', 'acc:SH022:B', ...] (expands a single list)
    - "SH001:A + ..." -> ['acc:SH001:A', ...] (standard custom spec)
    """
    if not spec:
        return []

    parts = [p.strip() for p in re.split(r"\s*\+\s*", spec.strip()) if p.strip()]
    if not parts:
        return []

    # Determine the type of spec before processing
    is_multi_list_spec = len(parts) > 1 and all(":" not in p for p in parts)
    is_single_list_spec = len(parts) == 1 and ":" not in parts[0]

    out = []
    if is_multi_list_spec:
        # Case 1: "SH001 + SH002". Create list-level nodes for a high-level view.
        for list_no in parts:
            out.append(f"list:{list_no}")

    elif is_single_list_spec:
        # Case 2: "SH022". Expand to its top-level accounts for an immediate breakdown.
        list_no = parts[0]
        if list_no in hier:
            top_accounts = get_top_level_accounts(hier[list_no])
            for acd in top_accounts:
                out.append(f"acc:{list_no}:{acd}")

    else:
        # Case 3: Any spec containing at least one account ID (e.g., "SH001:A + SH004:A2").
        # Treat it as a standard custom chart of individual accounts.
        for p in parts:
            if ":" in p:
                lst, acd = p.split(":", 1)
                out.append(f"acc:{lst.strip()}:{acd.strip()}")
            else:
                # If a bare list is mixed with accounts, treat it as a list total.
                out.append(f"list:{p}")

    return out


# ---------- hierarchy helpers ----------
def get_top_level_accounts(H: dict) -> List[str]:
    layers = H.get("layers", [])
    if not layers:
        return []
    top = layers[0]
    return sorted(top.get("codes", []), key=natural_key)

def get_children(H: dict, parent_cd: Optional[str]) -> List[str]:
    if not parent_cd:
        return []
    kids = H.get("children", {}).get(parent_cd, [])
    return sorted(kids, key=natural_key)


# ---------- values ----------
def values_for_accounts(df_master: pd.DataFrame, account_cds: List[str], colid: str) -> pd.DataFrame:
    m = df_master[(df_master["column_id"] == colid) & (df_master["account_cd"].isin(account_cds))].copy()
    if m.empty:
        return pd.DataFrame({"base_month": [], "account_cd": [], "value": []})
    m["base_month"] = m["base_month"].astype(str)
    m["value"] = m["value"].map(ensure_numeric)
    return m.groupby(["base_month", "account_cd"], as_index=False)["value"].sum()

def parent_series_for_list(df_master: pd.DataFrame, Hn: dict, colid: str) -> pd.Series:
    """Total series for a list across months as sum of its top accounts."""
    # This is the fix: filter the incoming dataframe by the specific list_no
    list_no = Hn["list_no"]
    df_scoped_to_list = df_master[df_master["list_no"] == list_no]

    # Use the full month range for a consistent axis, but the scoped data for calculation
    months = months_sorted(df_master)
    tops = get_top_level_accounts(Hn)
    vals = values_for_accounts(df_scoped_to_list, tops, colid)

    if vals.empty:
        return pd.Series(0.0, index=pd.Index(months, name="base_month"))

    # Get the sum from the scoped data and reindex against the full month list
    ser = vals.groupby("base_month")["value"].sum()
    return ser.reindex(months).fillna(0.0)


def node_parent_values(
    df_master: pd.DataFrame,
    hier_by_list: Dict[str, dict],
    list_nos: List[str],
    colid: str,
    level_path: List[str],
    custom_nodes: Optional[List[str]] = None,
    mode: Optional[str] = None,
) -> Tuple[str, List[str], pd.DataFrame]:
    months = months_sorted(df_master)

    # 0) Custom Nodes 
    if custom_nodes and len(level_path) == 0:
        nodes = custom_nodes[:]
        rows = []
        for key in nodes:
            if key.startswith("acc:"):
                _, listno, acd = key.split(":")
                scope = df_master[df_master["list_no"] == listno]

                # ⇩⇩ CURRENT-LEVEL VALUE ONLY (no child sums) ⇩⇩
                vals = values_for_accounts(scope, [acd], colid)

                # print(f"--- Debugging vals for node: {key} ---")
                # print(vals.to_string())
                # print("--------------------------------------")

                ser = (vals.groupby("base_month")["value"].sum()
                       .reindex(months).fillna(0.0)) if not vals.empty else pd.Series(0.0, index=pd.Index(months, name="base_month"))
                rows.append(pd.DataFrame({"base_month": months, "node_id": key, "value": ser.values}))
            elif key.startswith("list:"):
                # Allow 'list:SH150' too, sum its top accounts
                listno = key.split(":")[1]
                ser = parent_series_for_list(df_master, hier_by_list[listno], colid)
                rows.append(pd.DataFrame({"base_month": months, "node_id": key, "value": ser.values}))
        parent_vals = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame(columns=["base_month","node_id","value"])
        return "__CUSTOM__", nodes, parent_vals

    # 1) Multi-list root
    if len(list_nos) > 1 and len(level_path) == 0:
        rows = []
        for ln in list_nos:
            ser = parent_series_for_list(df_master, hier_by_list[ln], colid)
            rows.append(pd.DataFrame({"base_month": months, "node_id": ln, "value": ser.values}))
        parent_vals = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame(columns=["base_month","node_id","value"])
        return "__MULTI__", list_nos[:], parent_vals

    # 2) Single-list root (no path set yet)
    if len(level_path) == 0 and len(list_nos) == 1:
        active = list_nos[0]
        nodes = get_top_level_accounts(hier_by_list[active])
        parent_vals = _sum_over_nodes_in_list(df_master, hier_by_list, active, nodes, colid)
        return active, nodes, parent_vals

    # 3) We have a path; figure out the active list
    head = level_path[0]
    if head.startswith("list:"):
        active = head.split(":")[1]
    elif head.startswith("acc:"):
        _, active, _ = head.split(":", 2)   # path can start with an account in single-list mode
    else:
        active = list_nos[0]

    # 4) Single-element path
    if len(level_path) == 1:
        last = level_path[0]
        if last.startswith("acc:"):
            # *** FIX: treat ["acc:LIST:ACD"] as "children of ACD"
            _, listno, acd = last.split(":", 2)
            nodes = get_children(hier_by_list[listno], acd)
            parent_vals = _sum_over_nodes_in_list(df_master, hier_by_list, listno, nodes, colid)
            return listno, nodes, parent_vals
        else:
            # ["list:LIST"] → list root (top accounts)
            nodes = get_top_level_accounts(hier_by_list[active])
            parent_vals = _sum_over_nodes_in_list(df_master, hier_by_list, active, nodes, colid)
            return active, nodes, parent_vals

    # 5) Deeper paths → children of the last account
    last = level_path[-1]
    if last.startswith("acc:"):
        _, listno, acd = last.split(":", 2)
        nodes = get_children(hier_by_list[listno], acd)
        parent_vals = _sum_over_nodes_in_list(df_master, hier_by_list, listno, nodes, colid)
        return listno, nodes, parent_vals
    
    if level_path:
        active_list_no = list_nos[0] # Assume a single list context for deep paths
        parent_acd = level_path[-1]  # This is either specific ('acc:...') or generic ('A')

        # If the path is from side-by-side mode, it's generic (e.g., 'A')
        # If it's from another mode, it's specific (e.g., 'acc:SH001:A')
        if mode != 'side-by-side':
            try: # Parse the specific path to get the correct parent account
                _, active_list_no, parent_acd = parent_acd.split(":", 2)
            except ValueError:
                pass # Fallback if path is malformed
        nodes = get_children(hier_by_list.get(active_list_no, {}), parent_acd)
        parent_vals = _sum_over_nodes_in_list(df_master, hier_by_list, active_list_no, nodes, colid)
        return active_list_no, nodes, parent_vals

    # 6) Fallback to list root
    nodes = get_top_level_accounts(hier_by_list[active])
    parent_vals = _sum_over_nodes_in_list(df_master, hier_by_list, active, nodes, colid)
    return active, nodes, parent_vals


def _sum_over_nodes_in_list(
        df_master: pd.DataFrame,
        hier_by_list: Dict[str, dict],
        list_no: str,
        node_ids: List[str],
        colid: str
    ) -> pd.DataFrame:
    """
    CURRENT-LEVEL STACKING:
    For each node (account_cd) in node_ids, use that node's own series only
    (no summing of children). If a node has no own rows for the given colid,
    it contributes zeros.
    """
    months = months_sorted(df_master)
    scope = df_master[df_master["list_no"] == list_no]
    rows = []

    for nid in node_ids:
        own = values_for_accounts(scope, [nid], colid)
        if not own.empty:
            ser = own.groupby("base_month")["value"].sum().reindex(months).fillna(0.0)
        else:
            ser = pd.Series(0.0, index=pd.Index(months, name="base_month"))
        rows.append(pd.DataFrame({"base_month": months, "node_id": nid, "value": ser.values}))

    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame(columns=["base_month","node_id","value"])



def make_hier_stacked_figure(
    hier_by_list: Dict[str, dict],
    df_master: pd.DataFrame,
    list_nos: List[str],
    colid: str,
    level_path: List[str],
    namer=None,
    custom_nodes: Optional[List[str]] = None,
    firms_to_plot: Optional[Dict[str, dict]] = None,
    ) -> go.Figure:
    
    firms_to_plot = firms_to_plot or {}
    months = months_sorted(df_master)
    all_traces = []
    all_values_for_scaling = []

    # 1. Determine the full set of nodes (accounts) from a representative firm to create a consistent color map.
    first_firm_cd = next(iter(firms_to_plot), None)
    color_map = {}
    if first_firm_cd:
        first_firm_df = df_master[df_master["finance_cd"] == first_firm_cd]
        _, nodes_for_color, _ = node_parent_values(first_firm_df, hier_by_list, list_nos, colid, level_path, custom_nodes=custom_nodes)
        
        for i, node_id in enumerate(nodes_for_color):
            color_map[node_id] = qualitative.Plotly[i % len(qualitative.Plotly)]

    # 2. Loop through each firm to generate its set of stacked traces with a unique offset
    for i, (firm_cd, style_info) in enumerate(firms_to_plot.items()):
        pattern = style_info.get("pattern", "")
        firm_df = df_master[df_master["finance_cd"] == firm_cd]
        if firm_df.empty: continue

        parent_listno, nodes, parent_vals = node_parent_values(firm_df, hier_by_list, list_nos, colid, level_path, custom_nodes=custom_nodes)
        if parent_vals.empty: continue

        yv = {nid: ser.tolist() for nid, ser in [(nid, (parent_vals[parent_vals["node_id"] == nid].set_index("base_month")["value"].reindex(months).fillna(0.0))) for nid in nodes]}
        all_values_for_scaling.extend([val for subl in yv.values() for val in subl])
        yv_vis = apply_min_share_matrix(yv, min_share=0.02)
        firm_name = namer.finance_label(firm_cd, include_id=False) if namer else firm_cd

        # This inner function generates traces for a single firm's stack
        def generate_traces_for_firm(p_listno, node_list, y_values):
            firm_traces = []
            title = f"{firm_name}{' ('+pattern+')' if pattern else ''}"
            
            for n_id in node_list:
                # Determine the correct node key for hover and the trace name
                node_key_for_hover = n_id
                if p_listno not in ("__MULTI__", "__CUSTOM__"):
                    trace_name = namer.account_label(p_listno, n_id, descendent=False, include_id=False)
                    node_key_for_hover = f"acc:{p_listno}:{n_id}"
                else:
                    if n_id.startswith("acc:"): _, lst, acd = n_id.split(":"); trace_name = namer.account_label(lst, acd, descendent=False, include_id=False)
                    else: lst = n_id.split(":")[1]; trace_name = namer.list_label(lst, include_id=False)
                
                firm_traces.append(go.Bar(
                    name=trace_name,
                    x=months, 
                    y=y_values.get(n_id, []),
                    offsetgroup=str(i), # Assign all traces for this firm to the same offset group
                    marker=dict(pattern=dict(shape=pattern), color=color_map.get(n_id)),
                    legendgroup=title,
                    legendgrouptitle_text=title,
                    customdata=[{"node_key": node_key_for_hover, "firm_cd": firm_cd}] * len(months),
                    hovertemplate="<extra></extra>"
                ))
            return firm_traces
        
        all_traces.extend(generate_traces_for_firm(parent_listno, nodes, yv_vis))

    # 3. Rescale all traces now that the global scale is known
    scale, unit_lab = select_rescaler_from_values(all_values_for_scaling)
    for trace in all_traces:
        trace.y = [y / scale if y is not None else None for y in trace.y]

    # 4. Correctly scoped Y-axis title logic
    section_list_nos = set()
    if first_firm_cd:
        _, final_nodes, _ = node_parent_values(df_master[df_master["finance_cd"] == first_firm_cd], hier_by_list, list_nos, colid, level_path, custom_nodes=custom_nodes)
        final_parent_listno = "__CUSTOM__" # Default for spec-driven charts
        if level_path: 
            last_path = level_path[-1]
            if ":" in last_path: final_parent_listno = last_path.split(":")[1]
            else: final_parent_listno = list_nos[0] if list_nos else ""
        elif len(list_nos) == 1 and not custom_nodes: 
            final_parent_listno = list_nos[0]

        if final_parent_listno in ("__MULTI__", "__CUSTOM__"):
            for nid in final_nodes:
                try: section_list_nos.add(nid.split(":")[1])
                except IndexError: section_list_nos.add(nid)
        else:
            section_list_nos.add(final_parent_listno)

    df_section_specific = df_master[df_master["list_no"].isin(section_list_nos)]
    y_label = colid
    if not df_section_specific.empty:
        col_nm_series = df_section_specific[df_section_specific["column_id"] == colid]["column_nm"]
        if not col_nm_series.empty: y_label = ", ".join(col_nm_series.unique())
    if unit_lab: y_label = f"{y_label} ({unit_lab})"
            
    # 5. Create the final figure
    fig = go.Figure(all_traces)
    fig.update_layout(
        barmode="relative", # Use "relative" (stacking) in combination with offsetgroup
        legend=dict(tracegroupgap=20, orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0.0, font=dict(size=LEGEND_FS)),
        margin=dict(l=10, r=10, t=40, b=40),
        xaxis=dict(title=dict(font=dict(size=AXIS_TITLE_FS)), tickfont=dict(size=TICK_FS), showgrid=False),
        yaxis=dict(title=dict(text=y_label, font=dict(size=AXIS_TITLE_FS)), tickfont=dict(size=TICK_FS), zeroline=True, zerolinewidth=1),
        hovermode="closest",
    )
    return fig

# ---------- hover helpers (for side panel) ----------
def hover_summary_other_nodes(
    hier_by_list: Dict[str, dict],
    parent_listno: str,
    nodes: List[str],
    parent_vals: pd.DataFrame,
    base_month: str,
    hovered_node_key: str,
    namer=None, 
) -> List[Tuple[str, float]]:
    """
    Returns [(label, value), ...] at base_month for all nodes EXCEPT hovered.
    Handles either multi-list (hover key 'list:...') or inside-list (usually 'acc:list:acd').
    If the hovered key doesn't match the expected pattern for the current level, no exclusion.
    """
    # CUSTOM ROOT: nodes are 'acc:LIST:ACD' or 'list:LIST'
    if parent_listno == "__CUSTOM__":
        hovered_id = hovered_node_key if (hovered_node_key.startswith("acc:") or hovered_node_key.startswith("list:")) else None
        items = []
        for nid in nodes:
            if hovered_id and nid == hovered_id:
                continue
            val = (parent_vals[(parent_vals["node_id"] == nid) & (parent_vals["base_month"] == base_month)]["value"].sum())
            if nid.startswith("acc:"):
                _, lst, acd = nid.split(":")
                lbl = namer.account_label(lst, acd, descendent=False, include_id=True) if namer else f"{lst}:{acd}"
            else:
                lst = nid.split(":")[1]
                lbl = namer.list_label(lst, include_id=True) if namer else list_label(hier_by_list, lst)
            items.append((lbl, float(val)))
        items.sort(key=lambda x: natural_key(x[0]))
        return items

    # MULTI-LIST ROOT: nodes are list_nos; hovered is like 'list:SH001'
    if parent_listno == "__MULTI__":
        hovered_id = hovered_node_key.split(":")[1] if hovered_node_key.startswith("list:") else None
        items = []
        for ln in nodes:
            if hovered_id and ln == hovered_id:
                continue
            val = (parent_vals[(parent_vals["node_id"] == ln) & (parent_vals["base_month"] == base_month)]["value"]
                   .sum())
            items.append((namer.list_label(ln, True) if namer else list_label(hier_by_list, ln), float(val)))
        items.sort(key=lambda x: natural_key(x[0]))
        return items

    # INSIDE A LIST: nodes are account_cds; hovered is ideally 'acc:list:acd'
    hovered_acd = None
    if hovered_node_key.startswith("acc:"):
        try:
            _, _, hovered_acd = hovered_node_key.split(":")
        except ValueError:
            hovered_acd = None

    items = []
    for nid in nodes:
        if hovered_acd and nid == hovered_acd:
            continue
        val = (parent_vals[(parent_vals["node_id"] == nid) & (parent_vals["base_month"] == base_month)]["value"]
               .sum())
        lbl = namer.account_label(parent_listno, nid, descendent=False, include_id=True) if namer else nid
        items.append((lbl, float(val)))

    items.sort(key=lambda x: natural_key(x[0]))
    return items


def donut_for_hovered_node(
    hier_by_list: Dict[str, dict],
    df_master: pd.DataFrame,
    colid: str,
    hovered_node_key: str,
    base_month: str,
    namer=None,
) -> Tuple[go.Figure, float, str, int]:
    safe_month = str(base_month) if base_month is not None else ""
    num_legend_items = 0

    # LIST NODE BRANCH (This branch remains unchanged as the total of a list IS the sum of its children)
    if hovered_node_key.startswith("list:"):
        list_no = hovered_node_key.split(":")[1]
        Hn = hier_by_list[list_no]
        kids = get_top_level_accounts(Hn)
        scope = df_master[df_master["list_no"] == list_no]
        vals = values_for_accounts(scope, kids, colid)
        total = (vals.groupby("base_month")["value"].sum().get(safe_month, 0.0)) if not vals.empty else 0.0

        if vals.empty or vals[vals["base_month"] == safe_month].empty:
            labels, values = ["하위 없음"], [1]
        else:
            agg = vals[vals["base_month"] == safe_month].groupby("account_cd")["value"].sum()
            ids = list(agg.index)
            labels_unsorted = [namer.account_label(list_no, cid, descendent=True, include_id=False) if namer else cid for cid in ids]
            order = sorted(range(len(ids)), key=lambda k: natural_key(labels_unsorted[k]))
            labels = [labels_unsorted[k] for k in order]
            values = [float(agg.loc[cid]) for cid in ids]

        neg_mask = [(v is not None and ensure_numeric(v) < 0) for v in values]
        pull = [0.06 if isneg else 0.0 for isneg in neg_mask]
        labels = [(lbl + " (−)") if isneg else lbl for lbl, isneg in zip(labels, neg_mask)]
        num_legend_items = len(labels)
        scale_d, unit_d = select_rescaler_from_values(values)
        metric_lbl = (namer.column_label(list_no, None, colid, include_id=False) if namer else colid)
        
        fig = go.Figure(go.Pie(
            labels=labels, values=[abs(v) for v in values], hole=0,
            sort=False, pull=pull, marker=dict(line=dict(color="#666", width=1)),
        ))
        if unit_d:
            metric_lbl = f"{metric_lbl}({unit_d})"

        title_text = f"{(namer.list_label(list_no, False))} — {safe_month} — {metric_lbl}"
        fig.update_layout(
            autosize=False, height=DONUT_HEIGHT, showlegend=True, font=dict(size=TITLE_FS),
            title=dict(text=title_text, font=dict(size=TITLE_FS)),
            legend=dict(font=dict(size=LEGEND_FS)),
            margin=dict(l=10, r=10, t=40, b=10),
        )
        return fig, scale_d, unit_d, num_legend_items

    # ACCOUNT NODE BRANCH
    _, list_no, acd = hovered_node_key.split(":")
    Hn = hier_by_list[list_no]
    kids = get_children(Hn, acd)
    scope = df_master[df_master["list_no"] == list_no]

    if kids: # The hovered account has children
        # --- START OF FIX ---
        # 1. Get the hovered account's OWN value for the center display
        own_vals = values_for_accounts(scope, [acd], colid)
        total = (own_vals.groupby("base_month")["value"].sum().get(safe_month, 0.0)) if not own_vals.empty else 0.0
        
        # 2. Get the CHILDREN'S values for the donut slices (this part is unchanged)
        vals = values_for_accounts(scope, kids, colid)
        # --- END OF FIX ---

        if vals.empty or vals[vals["base_month"] == safe_month].empty:
            labels, values = ["하위 없음"], [1]
        else:
            agg = vals[vals["base_month"] == safe_month].groupby("account_cd")["value"].sum()
            ids = list(agg.index)
            labels_unsorted = [namer.account_label(list_no, cid, descendent=True, include_id=False) if namer else cid for cid in ids]
            order = sorted(range(len(ids)), key=lambda k: natural_key(labels_unsorted[k]))
            labels = [labels_unsorted[k] for k in order]
            values = [float(agg.loc[cid]) for cid in ids]
    else: # The hovered account has NO children (leaf node)
        # This branch is already correct, as it uses the node's own value for the total
        own = values_for_accounts(scope, [acd], colid)
        total = (own.groupby("base_month")["value"].sum().get(safe_month, 0.0)) if not own.empty else 0.0
        labels, values = ["(하위계정없음)"], [1 if total == 0 else total]
    
    # Common logic for formatting and creating the final figure
    neg_mask = [(v is not None and ensure_numeric(v) < 0) for v in values]
    pull = [0.06 if isneg else 0.0 for isneg in neg_mask]
    labels = [(lbl + " (−)") if isneg else lbl for lbl, isneg in zip(labels, neg_mask)]
    scale_d, unit_d = select_rescaler_from_values(values + [total]) # Include total in scaling
    scaled_total = ensure_numeric(total) / (scale_d or 1.0)
    num_legend_items = len(labels)

    fig = go.Figure(go.Pie(
        labels=labels, values=[abs(v) for v in values], hole=0.6, sort=False, pull=pull,
        marker=dict(line=dict(color="#666", width=1)),
    ))

    title_text = f"{namer.account_label(list_no, acd, descendent=False, include_id=False)} — {safe_month}"
    
    fig.update_layout(
        autosize=False, height=DONUT_HEIGHT, showlegend=True, title=dict(text=title_text),
        annotations=[dict(text=(f"{scaled_total:,.1f}" + (f" ({unit_d})" if unit_d else "")), x=0.5, y=0.5, font=dict(size=12), showarrow=False)],
        margin=dict(l=10, r=10, t=40, b=10),
    )
    return fig, scale_d, unit_d, num_legend_items
