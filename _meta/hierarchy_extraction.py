# build_hierarchy_from_mapping.py
"""
Build per-list_no hierarchy from the mapping produced by statisticsInfoSearch-based extractor.

Input (auto-detected in CWD):
- fisis_list_account_column_map.csv  (preferred)
- fisis_list_account_column_map.xlsx (fallback; uses sheet 'flat' if present)

Required columns in mapping:
  list_no, list_nm, account_cd, account_nm, column_id, column_nm
(Values can be empty/NaN for some rows; script handles that.)

Outputs:
- fisis_hierarchy.json            (rich per-list_no hierarchy)
- fisis_hierarchy_edges.csv       (parent-child edges across all list_no)
- fisis_hierarchy_layers.csv      (layer membership per list_no)
"""

from __future__ import annotations
import argparse
import json
from pathlib import Path
from typing import Dict, List, Tuple, Optional

import pandas as pd


# ---------------------------- IO helpers ----------------------------

def _find_input_path(user_path: Optional[str]) -> Path:
    if user_path:
        p = Path(user_path)
        if not p.exists():
            raise FileNotFoundError(f"Input file not found: {p}")
        return p

    # Auto-detect in CWD
    csv_path = Path("_local/fisis_list_account_column_map.csv")
    xlsx_path = Path("_local/fisis_list_account_column_map.xlsx")
    if csv_path.exists():
        return csv_path
    if xlsx_path.exists():
        return xlsx_path
    # Fallback: any csv/xlsx in cwd that contains expected columns
    for p in Path(".").glob("*.csv"):
        return p
    for p in Path(".").glob("*.xlsx"):
        return p
    raise FileNotFoundError(
        "No mapping file found. Expected 'fisis_list_account_column_map.csv' or '.xlsx' in the working directory."
    )


def _read_mapping(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".csv":
        df = pd.read_csv(path, dtype=str, encoding="utf-8-sig")
    else:
        # Try 'flat' sheet, otherwise the first sheet
        try:
            df = pd.read_excel(path, sheet_name="flat", dtype=str)
        except Exception:
            df = pd.read_excel(path, dtype=str)
    # Normalize columns
    required = ["list_no", "list_nm", "account_cd", "account_nm", "column_id", "column_nm"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Input missing required columns: {missing}")

    # Coerce to string and strip
    for c in required:
        df[c] = df[c].astype(str).fillna("").str.strip()
        # Keep true empties as ""
        df.loc[df[c].isin(["nan", "NaN", "None"]), c] = ""

    # Ensure list_no is string, preserve leading zeros (already dtype=str)
    return df


# ---------------------------- Hierarchy core ----------------------------

def _unique_mapping(df: pd.DataFrame, key_col: str, val_col: str) -> Dict[str, str]:
    """
    Build a stable dict of key -> val using first occurrence.
    """
    out: Dict[str, str] = {}
    for k, v in df[[key_col, val_col]].itertuples(index=False):
        if k and (k not in out):
            out[k] = v
    return out


def _ordinal(n: int) -> str:
    # For labeling layers if needed (1->'1st', 2->'2nd', ...)
    return f"{n}{'tsnrhtdd'[(n//10%10!=1)*(n%10<4)*n%10::4]}"


def _build_hierarchy_for_list(group: pd.DataFrame) -> Dict:
    """
    Build hierarchy dict for a single (list_no, list_nm) group.
    """
    list_no = str(group["list_no"].iloc[0])
    list_nm = str(group["list_nm"].iloc[0])

    # 1) Distinct columns (column_id -> column_nm)
    col_map = _unique_mapping(
        group[group["column_id"].astype(str) != ""],
        "column_id", "column_nm"
    )

    # 2) Distinct accounts (account_cd -> account_nm)
    acct_map = _unique_mapping(
        group[group["account_cd"].astype(str) != ""],
        "account_cd", "account_nm"
    )

    # If no accounts present, return structure with columns only
    if not acct_map:
        return {
            "list_no": list_no,
            "list_nm": list_nm,
            "columns": col_map,      # dict column_id -> column_nm
            "accounts": {},          # dict account_cd -> account_nm
            "total_layers": 0,
            "lengths_top_to_bottom": [],
            "layers": [],
            "parent": {},
            "children": {},
            "top_layer_length": None,
            "bottom_layer_length": None
        }

    # 3) Distinct code lengths; shortest = top layer, longest = bottom
    codes = list(acct_map.keys())
    lengths = sorted({len(c) for c in codes if c})
    top_to_bottom = lengths[:]              # ascending (min -> max)
    bottom_to_top = lengths[::-1]           # descending (max -> min)

    # Group accounts by length
    by_len: Dict[int, List[str]] = {L: [] for L in lengths}
    for c in sorted(codes):  # stable
        by_len[len(c)].append(c)

    # 4) Parent-child via prefix to next-shorter length
    parent: Dict[str, Optional[str]] = {}
    children: Dict[str, List[str]] = {c: [] for c in codes}

    # Work from bottom to top: for each child length, find parent in immediate shorter length
    for idx, L in enumerate(bottom_to_top):
        # For the bottom-most length, idx = 0; for the top (shortest), this loop still runs, but will have no parent layer
        child_len = L
        child_codes = by_len.get(child_len, [])

        # parent layer length is the next element in bottom_to_top (i.e., shorter)
        if idx + 1 < len(bottom_to_top):
            par_len = bottom_to_top[idx + 1]
            parent_candidates = set(by_len.get(par_len, []))
        else:
            par_len = None
            parent_candidates = set()

        for c in child_codes:
            if par_len is None:
                parent[c] = None
            else:
                candidate = c[:par_len]  # prefix
                if candidate in parent_candidates:
                    parent[c] = candidate
                    children[candidate].append(c)
                else:
                    # No matching parent in immediate shorter layer
                    parent[c] = None

    # Build layer descriptors (top -> bottom)
    layers_desc = []
    for i, L in enumerate(top_to_bottom, start=1):
        layers_desc.append({
            "level_index": i,               # 1 = uppermost
            "ordinal": _ordinal(i),
            "length": L,                    # length value that defines this layer
            "codes": by_len.get(L, []),     # account_cd list at this layer (no names here)
            "codes_with_names": [
                {"account_cd": c, "account_nm": acct_map.get(c, "")}
                for c in by_len.get(L, [])
            ]
        })

    return {
        "list_no": list_no,
        "list_nm": list_nm,
        "columns": col_map,                 # dict column_id -> column_nm
        "accounts": acct_map,               # dict account_cd -> account_nm
        "total_layers": len(lengths),
        "lengths_top_to_bottom": top_to_bottom,
        "layers": layers_desc,              # ordered top->bottom
        "parent": parent,                   # child_cd -> parent_cd (or None)
        "children": {k: sorted(v) for k, v in children.items() if v},
        "top_layer_length": top_to_bottom[0] if top_to_bottom else None,
        "bottom_layer_length": top_to_bottom[-1] if top_to_bottom else None,
    }


def build_all_hierarchies(df: pd.DataFrame) -> Dict[str, Dict]:
    """
    Returns dict keyed by list_no, each value is a hierarchy dict from _build_hierarchy_for_list.
    """
    # Group by list_no + list_nm to keep the name bound correctly
    out: Dict[str, Dict] = {}
    for (ln, lm), grp in df.groupby(["list_no", "list_nm"], dropna=False, sort=False):
        h = _build_hierarchy_for_list(grp)
        out[str(ln)] = h
    return out


# ---------------------------- Export helpers ----------------------------

def _export_edges(hier_by_list: Dict[str, Dict], path: Path):
    """
    Export parent-child edges across all list_no for graphing / inspection.
    """
    rows = []
    for ln, H in hier_by_list.items():
        par = H.get("parent", {})
        for child, parent in par.items():
            rows.append({
                "list_no": ln,
                "list_nm": H.get("list_nm", ""),
                "child": child,
                "child_len": len(child) if child else None,
                "parent": parent if parent is not None else "",
                "parent_len": (len(parent) if parent else None)
            })
    pd.DataFrame(rows).to_csv(path, index=False, encoding="utf-8-sig")


def _export_layers(hier_by_list: Dict[str, Dict], path: Path):
    """
    Export layer membership (top -> bottom) per list_no.
    """
    rows = []
    for ln, H in hier_by_list.items():
        lm = H.get("list_nm", "")
        for layer in H.get("layers", []):
            rows.append({
                "list_no": ln,
                "list_nm": lm,
                "level_index": layer["level_index"],
                "ordinal": layer["ordinal"],
                "length": layer["length"],
                "account_cds": " ".join(layer["codes"]),
            })
    pd.DataFrame(rows).to_csv(path, index=False, encoding="utf-8-sig")


# ---------------------------- CLI ----------------------------

def main():
    ap = argparse.ArgumentParser(description="Build account-code hierarchy per list_no.")
    ap.add_argument("-i", "--input", help="Path to mapping CSV/XLSX (default: auto-detect)")
    ap.add_argument("-o", "--out_json", default="_local/fisis_hierarchy.json", help="Output JSON path")
    ap.add_argument("--edges_csv", default="_local/fisis_hierarchy_edges.csv", help="Edges CSV path")
    ap.add_argument("--layers_csv", default="_local/fisis_hierarchy_layers.csv", help="Layers CSV path")
    args = ap.parse_args()

    in_path = _find_input_path(args.input)
    df = _read_mapping(in_path)

    # Build hierarchies
    hier_by_list = build_all_hierarchies(df)

    # Save JSON (UTF-8)
    with open(args.out_json, "w", encoding="utf-8") as f:
        json.dump(hier_by_list, f, ensure_ascii=False, indent=2)
    print(f"[ok] Saved hierarchy JSON → {args.out_json}")

    # Save edges and layers
    _export_edges(hier_by_list, Path(args.edges_csv))
    print(f"[ok] Saved edges CSV → {args.edges_csv}")

    _export_layers(hier_by_list, Path(args.layers_csv))
    print(f"[ok] Saved layers CSV → {args.layers_csv}")

    # Quick console summary
    print(f"[summary] Lists processed: {len(hier_by_list)}")
    preview = list(hier_by_list.items())[:3]
    for ln, H in preview:
        print(f" - list_no={ln}  layers={H['total_layers']}  top_len={H['top_layer_length']}  bottom_len={H['bottom_layer_length']}")


if __name__ == "__main__":
    main()
