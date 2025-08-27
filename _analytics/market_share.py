from __future__ import annotations
from typing import Iterable, Dict, List, Optional, Tuple
import math
import pandas as pd

# reuse your existing helpers so the "current level" is identical to the chart
from _visual.graph_hier_bar import node_parent_values, months_sorted 


def _sum_level_by_month(
    df: pd.DataFrame,
    hier_by_list: dict,
    list_nos: Iterable[str],
    colid: str,
    level_path: List[str],
    custom_nodes: Optional[dict] = None,
) -> pd.Series:
    """
    Sum ABS(values) across the current level (defined by level_path) for each base_month.
    Returns a Series indexed by base_month (str -> float).
    """
    parent_listno, nodes, parent_vals = node_parent_values(
        df_master=df,
        hier_by_list=hier_by_list,
        list_nos=list_nos,
        colid=colid,
        level_path=(level_path or []),
        custom_nodes=custom_nodes,
    )
    if parent_vals is None or len(parent_vals) == 0:
        return pd.Series(dtype=float)

    # parent_vals has rows per node_id per month; sum across nodes for each month
    s = (
        parent_vals
        .groupby("base_month")["value"]
        .apply(lambda x: float(pd.Series(x).abs().sum()))
        .astype(float)
        .sort_index(key=lambda idx: [int(m) for m in idx])  # chronological by YYYYMM
    )
    return s


def _share_series(numer: pd.Series, denom: pd.Series) -> pd.Series:
    """
    Return percentage share = numer/denom*100 (float), aligned on base_month, NaN-safe.
    """
    df = pd.concat({"n": numer, "d": denom}, axis=1)
    def _safe(row):
        n, d = row["n"], row["d"]
        if d is None or (isinstance(d, float) and math.isnan(d)) or d == 0:
            return float("nan")
        return float(n) / float(d) * 100.0
    out = df.apply(_safe, axis=1)
    return out


def _delta_pp(cur: Optional[float], prev: Optional[float]) -> Optional[float]:
    """
    Return delta in percentage points (cur - prev). Keep as float; caller rounds to 2dp.
    """
    if cur is None or prev is None:
        return None
    if any(isinstance(x, float) and math.isnan(x) for x in (cur, prev)):
        return None
    return float(cur) - float(prev)


def _metrics_from_share(share: pd.Series) -> pd.DataFrame:
    """
    Given a share% Series indexed by YYYYMM strings, compute deltas vs:
      - preceding period in the sorted index
      - 1-year before (YYYYMM - 100)
      - 2-year before (YYYYMM - 200)
    Returns a DataFrame with: base_month, share_pct, d_prev_pp, d_1y_pp, d_2y_pp (rounded to 2dp).
    """
    months = list(share.index)
    months_sorted_idx = sorted(months, key=int)
    share = share.reindex(months_sorted_idx)

    data = []
    lookup = share.to_dict()
    for i, m in enumerate(months_sorted_idx):
        cur = lookup.get(m, float("nan"))
        # preceding in the series order (not calendar delta)
        prev = lookup.get(months_sorted_idx[i-1]) if i > 0 else None
        # calendar deltas by YYYYMM arithmetic
        m_int = int(m)
        m_1y = str(m_int - 100)
        m_2y = str(m_int - 200)
        y1 = lookup.get(m_1y)
        y2 = lookup.get(m_2y)

        # --- START OF FIX ---
        # First, calculate the raw deltas, which may be None
        delta_prev_raw = _delta_pp(cur, prev)
        delta_1y_raw = _delta_pp(cur, y1)
        delta_2y_raw = _delta_pp(cur, y2)

        row = dict(
            base_month=m,
            share_pct=round(cur, 2) if not (isinstance(cur, float) and math.isnan(cur)) else None,
            # Second, round the deltas only if they are not None
            d_prev_pp=round(delta_prev_raw, 2) if delta_prev_raw is not None else None,
            d_1y_pp=round(delta_1y_raw, 2) if delta_1y_raw is not None else None,
            d_2y_pp=round(delta_2y_raw, 2) if delta_2y_raw is not None else None,
        )
        # --- END OF FIX ---
        data.append(row)
    return pd.DataFrame(data, columns=["base_month", "share_pct", "d_prev_pp", "d_1y_pp", "d_2y_pp"])


def compute_full_market_share_data(
    df_all: pd.DataFrame,
    *,
    hier_by_list: dict,
    list_nos: Iterable[str],
    colid: str,
    level_path: List[str],
    entire_market_cds: Iterable[str],
    groups: Dict[str, List[str]],
    custom_nodes: Optional[dict] = None,
) -> Dict[str, pd.DataFrame]:
    """
    Computes detailed market share metrics for all firms, and aggregate/average
    metrics for all defined groups.
    """
    market_mask = df_all["finance_cd"].isin(list(entire_market_cds or []))
    df_market = df_all.loc[market_mask].copy()

    s_market = _sum_level_by_month(
        df_market, hier_by_list, list_nos, colid, level_path, custom_nodes=custom_nodes
    )

    # --- Per-Firm Calculations ---
    all_firm_stats = []
    market_cds_sorted = sorted(list(entire_market_cds or []))
    
    for cd in market_cds_sorted:
        df_firm = df_market.loc[df_market["finance_cd"] == cd]
        s_firm = _sum_level_by_month(
            df_firm, hier_by_list, list_nos, colid, level_path, custom_nodes=custom_nodes
        )
        share_firm = _share_series(s_firm, s_market)
        metrics_df = _metrics_from_share(share_firm)
        metrics_df["finance_cd"] = cd
        all_firm_stats.append(metrics_df)

    if not all_firm_stats:
        return {"per_firm": pd.DataFrame(), "groups": {}}

    df_per_firm = pd.concat(all_firm_stats, ignore_index=True)
    df_per_firm["rank"] = df_per_firm.groupby("base_month")["share_pct"].rank(method="min", ascending=False)
    df_per_firm_sorted = df_per_firm.sort_values(["finance_cd", "base_month"])
    df_per_firm_sorted["prev_rank"] = df_per_firm_sorted.groupby("finance_cd")["rank"].shift(1)
    df_per_firm_sorted["rank_change"] = (df_per_firm_sorted["prev_rank"] - df_per_firm_sorted["rank"]).fillna(0)

    # --- Group-Level Calculations ---
    group_results = {}
    groups = groups or {}
    for gname, cds in groups.items():
        if not cds: continue
        
        df_group_firms = df_per_firm_sorted[df_per_firm_sorted["finance_cd"].isin(cds)]
        if df_group_firms.empty: continue

        # Aggregate (Sum)
        share_group_agg = df_group_firms.groupby("base_month")["share_pct"].sum()
        agg_metrics = _metrics_from_share(share_group_agg)
        
        # Average (Mean)
        share_group_avg = df_group_firms.groupby("base_month")["share_pct"].mean()
        avg_metrics = _metrics_from_share(share_group_avg)
        
        group_results[gname] = {"agg": agg_metrics, "avg": avg_metrics}

    return {"per_firm": df_per_firm_sorted, "groups": group_results}