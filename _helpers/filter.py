import pandas as pd
from typing import Tuple


def _canon_fin_cd_series(s: pd.Series) -> pd.Series:
    # keep digits only, strip spaces, zero-pad to 7
    return (
        s.astype(str)
         .str.strip()
         .str.extract(r"(\d+)", expand=False)
         .fillna("")
         .str.zfill(7)
    )

def _canon_fin_cd_value(x: str) -> str:
    x = "" if x is None else str(x)
    x = "".join(ch for ch in x if ch.isdigit())  # digits only
    return x.zfill(7) if x else ""

def _filter_master_data_for_section(
    df_master: pd.DataFrame,
    section_params: dict,
    fallback_colid: str,
    fallback_term: str,
) -> Tuple[pd.DataFrame, str, str]:
    """
    Applies section-specific parameter overrides and filters the master dataframe.
    Returns the filtered dataframe, the final column id, and the final term.
    """
    section_params = section_params or {}
    final_colid = section_params.get("colid") or fallback_colid
    final_term = section_params.get("term") or fallback_term

    if df_master.empty:
        return pd.DataFrame(), final_colid, final_term

    all_months = sorted(df_master["base_month"].astype(str).unique())
    global_start = all_months[0] if all_months else "190001"
    global_end = all_months[-1] if all_months else "299912"

    # --- START OF FIX ---
    # Explicitly handle the "start" and "end" keywords
    min_d = section_params.get("min_d")
    max_d = section_params.get("max_d")

    final_start = global_start if min_d == "start" or not min_d else min_d
    final_end = global_end if max_d == "end" or not max_d else max_d
    # --- END OF FIX ---

    # Apply date range filter
    df_filtered = df_master[
        (df_master['base_month'] >= final_start) & (df_master['base_month'] <= final_end)
    ].copy()

    # Apply term filter
    if final_term == "Y":
        df_filtered = df_filtered[df_filtered["base_month"].str.endswith("12")].copy()
    elif final_term == "H":
        df_filtered = df_filtered[df_filtered["base_month"].str.endswith(("06", "12"))].copy()
    
    return df_filtered, final_colid, final_term