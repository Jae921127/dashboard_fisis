# utils_bucketing.py
from __future__ import annotations
from typing import Sequence, Optional, Union
import pandas as pd


def bucket_small_components(
    df: pd.DataFrame,
    *,
    group_cols: Sequence[str],
    item_col: str,
    value_col: str,
    parent_totals: Optional[Union[pd.Series, pd.DataFrame]] = None,
    parent_value_col: str = "parent_val",
    threshold: float = 0.01,
    bucket_label: str = "기타 - 1% 미만",
    strict_lt: bool = True,
) -> pd.DataFrame:
    """
    Collapse small components into a single bucket per group based on share of parent total.

    Parameters
    ----------
    df : long-form DataFrame
        Must include columns: group_cols + [item_col, value_col]
        Example: ['base_month', 'child_id', 'value']
    group_cols : sequence of str
        Columns that define each parent group (e.g., ['base_month'] or ['base_month','parent_id']).
    item_col : str
        Column with the item/category identifier to potentially bucket (e.g., 'child_id').
    value_col : str
        Column with numeric values.
    parent_totals : Series or DataFrame, optional
        If provided, must supply totals per group to compute shares against.
        - Series indexed by group_cols → will be reset_index() and merged.
        - DataFrame with columns group_cols + [parent_value_col].
        If None, parent totals are computed as df.groupby(group_cols)[value_col].sum().
    parent_value_col : str
        Name of the column in parent_totals DataFrame that contains totals. Default 'parent_val'.
    threshold : float
        Components with share < threshold (or <= if strict_lt=False) are bucketed into `bucket_label`.
    bucket_label : str
        Label used for the bucketed “others”.
    strict_lt : bool
        If True → bucket if share < threshold; if False → bucket if share <= threshold.

    Returns
    -------
    DataFrame
        Aggregated: group_cols + [item_col, value_col], where small items are replaced by `bucket_label`
        and values re-summed per group.

    Notes
    -----
    - If a group's parent total is 0 or NaN, all shares are treated as 0 (thus all items will be bucketed).
    - This is intentionally minimal and graph-agnostic; handle ordering/labels in the caller.
    """
    if not isinstance(group_cols, (list, tuple)):
        raise TypeError("group_cols must be a list/tuple of column names.")

    work = df.copy()
    # Ensure required columns exist
    for c in [*group_cols, item_col, value_col]:
        if c not in work.columns:
            raise KeyError(f"Missing required column: {c}")

    # Coerce value to numeric (non-convertible → NaN → treated as 0)
    work[value_col] = pd.to_numeric(work[value_col], errors="coerce").fillna(0.0)

    # Prepare parent totals
    if parent_totals is None:
        totals = (
            work.groupby(list(group_cols), dropna=False)[value_col]
                .sum()
                .rename(parent_value_col)
                .reset_index()
        )
    else:
        if isinstance(parent_totals, pd.Series):
            totals = parent_totals.rename(parent_value_col).reset_index()
        elif isinstance(parent_totals, pd.DataFrame):
            if parent_value_col not in parent_totals.columns:
                raise KeyError(f"parent_totals is a DataFrame but missing '{parent_value_col}' column.")
            totals = parent_totals[list(group_cols) + [parent_value_col]].copy()
        else:
            raise TypeError("parent_totals must be a pandas Series or DataFrame.")

    # Merge totals into rows
    work = work.merge(totals, on=list(group_cols), how="left")
    work[parent_value_col] = work[parent_value_col].fillna(0.0)

    # Compute share; avoid division warnings by treating zero totals as zero share
    share = work[value_col] / work[parent_value_col].replace(0, pd.NA)
    work["_share"] = share.fillna(0.0)

    # Decide which to bucket
    if strict_lt:
        to_bucket = work["_share"] < threshold
    else:
        to_bucket = work["_share"] <= threshold

    # Apply bucket label
    work["_item_bkt"] = work[item_col].where(~to_bucket, other=bucket_label)

    # Re-aggregate
    out = (
        work.groupby([*group_cols, "_item_bkt"], dropna=False)[value_col]
            .sum()
            .reset_index()
            .rename(columns={"_item_bkt": item_col})
    )

    # Cleanup
    return out[[*group_cols, item_col, value_col]]


def bucket_by_share(
    df: pd.DataFrame,
    *,
    group_cols: Sequence[str],
    item_col: str,
    value_col: str,
    parent_series: Optional[pd.Series] = None,
    threshold: float = 0.01,
    bucket_label: str = "기타 - 1% 미만",
    strict_lt: bool = True,
) -> pd.DataFrame:
    """
    Convenience wrapper when you have a parent total as a Series indexed by group_cols.
    """
    parent_totals = None
    if parent_series is not None:
        parent_totals = parent_series.rename("parent_val")
    return bucket_small_components(
        df,
        group_cols=group_cols,
        item_col=item_col,
        value_col=value_col,
        parent_totals=parent_totals,
        parent_value_col="parent_val",
        threshold=threshold,
        bucket_label=bucket_label,
        strict_lt=strict_lt,
    )
