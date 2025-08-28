from __future__ import annotations
from typing import Dict, List, Optional
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px

def _calculate_delta_series(value_series: pd.Series, term: str) -> Dict[str, pd.Series]:
    """Calculates period-over-period, 1Y, and 2Y percentage changes based on the term."""
    if value_series.empty:
        return {"prev": pd.Series(dtype='float64'), "1y": pd.Series(dtype='float64'), "2y": pd.Series(dtype='float64')}

    df = value_series.sort_index()
    
    periods_1y, periods_2y = 4, 8
    if term == "Y":
        periods_1y, periods_2y = 1, 2
    elif term == "H":
        periods_1y, periods_2y = 2, 4

    delta_prev = df.pct_change(periods=1) * 100
    delta_1y = df.pct_change(periods=periods_1y) * 100
    delta_2y = df.pct_change(periods=periods_2y) * 100

    return {
        "prev": delta_prev.fillna(0),
        "1y": delta_1y.fillna(0),
        "2y": delta_2y.fillna(0),
    }

def make_delta_plot(
    data_by_entity: Dict[str, pd.DataFrame],
    selected_firm_name: str,
    term: str,
    view_selection: str = 'all', 
) -> go.Figure:
    """Creates the % change line chart."""
    fig = go.Figure()
    
    styles = {
        "prev": {"dash": "solid", "name": "vs Prev"},
        "1y": {"dash": "dash", "name": "vs 1Y"},
        "2y": {"dash": "dot", "name": "vs 2Y"},
    }
    
    colors = ["#1f77b4", "#7f7f7f", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd"]
    color_idx = 0

    for entity_name, df_values in data_by_entity.items():
        if df_values.empty:
            continue
            
        deltas = _calculate_delta_series(df_values, term)
        color = colors[color_idx % len(colors)]
        color_idx += 1

        for delta_type, series in deltas.items():
            if view_selection != 'all' and delta_type != view_selection:
                continue


            is_primary_entity = entity_name in [selected_firm_name, "Market"]
            
            fig.add_trace(go.Scatter(
                x=series.index,
                y=series.values,
                name=f"{entity_name} {styles[delta_type]['name']}",
                mode='lines+markers+text' if is_primary_entity else 'lines',
                text=[f"{y:.1f}" for y in series.values] if is_primary_entity else None,
                textposition="top center",
                textfont=dict(size=8, color=color),
                marker=dict(size=5, color=color),
                line=dict(dash=styles[delta_type]['dash'], color=color),
                hovertemplate="%{y:.2f}%<extra></extra>"
            ))
            
    fig.update_layout(
        title_text="값 증감률 vs 이전 값", font=dict(size=12),
        margin=dict(l=20, r=20, t=40, b=20),
        yaxis_title="증감률 (%)",
        yaxis_ticksuffix="%",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        hovermode="x unified"
    )
    return fig
