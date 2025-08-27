from __future__ import annotations
import argparse
import json
from pathlib import Path
from dataclasses import dataclass
from typing import Dict, Optional, Tuple, Union

import pandas as pd
import xml.etree.ElementTree as ET






# ---------- IO helpers ----------
def _read_hierarchy(path: str | Path) -> Dict[str, dict]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def _read_mapping(path: str | Path) -> pd.DataFrame:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Mapping file not found: {p}")
    if p.suffix.lower() == ".csv":
        df = pd.read_csv(p, dtype=str, encoding="utf-8-sig")
    else:
        try:
            df = pd.read_excel(p, sheet_name="flat", dtype=str)
        except Exception:
            df = pd.read_excel(p, dtype=str)

    need = ["list_no", "list_nm", "account_cd", "account_nm"]
    missing = [c for c in need if c not in df.columns]
    if missing:
        raise ValueError(f"Mapping missing required columns: {missing}")

    for c in need:
        df[c] = df[c].astype(str).fillna("").str.strip()
        df.loc[df[c].isin(["nan", "NaN", "None"]), c] = ""

    # keep ALL rows (no dedup) to detect raw one-to-many
    df = df[df["account_cd"] != ""].copy()
    return df[need].copy()


# ---------- Name trimming ----------
def _trim_name_by_parent(parent_nm: str, child_nm: str) -> str:
    parent_nm = (parent_nm or "").strip()
    child_nm  = (child_nm  or "").strip()
    if parent_nm and child_nm.startswith(parent_nm):
        child_nm = child_nm[len(parent_nm):]
    return child_nm.lstrip("_").lstrip()


# ---------- Core ----------
def build_within_otm_table(
    hierarchy_json_path: str = "_local/fisis_hierarchy.json",
    mapping_path: str = "_local/fisis_list_account_column_map.csv",
) -> pd.DataFrame:
    """
    Final columns:
      list_no | list_nm | account_cd | account_nm | within_account_nm | still_otm

    Rule:
      - For (list_no, account_cd) groups:
          size = count of rows in group
          uniq_within = number of distinct within_account_nm
          still_otm = 1 if (size > 1 and uniq_within > 1) else 0
      - Otherwise (no one-to-many to begin with), still_otm = 0
    """
    H = _read_hierarchy(hierarchy_json_path)
    M = _read_mapping(mapping_path)

    out_rows = []

    for (ln, lm), grp in M.groupby(["list_no", "list_nm"], sort=False):
        ln = str(ln); lm = str(lm)
        Hn = H.get(ln, {})
        accounts_map: Dict[str, str] = (Hn.get("accounts") or {})
        parent_map: Dict[str, Optional[str]] = (Hn.get("parent") or {})

        tmp = grp.copy()
        tmp["parent_cd"] = tmp["account_cd"].map(parent_map)
        tmp["parent_nm"] = tmp["parent_cd"].map(accounts_map).fillna("")
        tmp["within_account_nm"] = [
            _trim_name_by_parent(pn, cn)
            for pn, cn in zip(tmp["parent_nm"], tmp["account_nm"])
        ]

        # group metrics at (list_no, account_cd)
        g = (
            tmp.groupby(["list_no", "account_cd"])
               .agg(group_size=("within_account_nm", "size"),
                    uniq_within=("within_account_nm", pd.Series.nunique))
               .reset_index()
        )
        g["still_otm"] = ((g["group_size"] > 1) & (g["uniq_within"] > 1)).astype(int)
        tmp = tmp.merge(g[["list_no", "account_cd", "still_otm"]],
                        on=["list_no", "account_cd"], how="left")

        out_rows.append(
            tmp[["list_no","list_nm","account_cd","account_nm","within_account_nm","still_otm"]]
        )

    out = (pd.concat(out_rows, ignore_index=True)
           if out_rows else
           pd.DataFrame(columns=["list_no","list_nm","account_cd","account_nm","within_account_nm","still_otm"]))

    # Deduplicate final rows (keep unique combinations), but keep still_otm at (list_no, account_cd) level
    if not out.empty:
        out = (out
               .sort_values(["list_no","account_cd","within_account_nm","account_nm"], kind="stable")
               .drop_duplicates(subset=["list_no","account_cd","account_nm","within_account_nm"], keep="first")
               .reset_index(drop=True))
    return out


# ---------- CLI ----------
def main():
    ap = argparse.ArgumentParser(
        description="Inspect one-to-many from account_cd to within_account_nm per list_no, using binary rule."
    )
    ap.add_argument("-j","--hierarchy_json", default="_local/fisis_hierarchy.json",
                    help="Path to hierarchy JSON")
    ap.add_argument("-m","--mapping", default="_local/fisis_list_account_column_map.csv",
                    help="Path to account-column mapping CSV/XLSX")
    ap.add_argument("-o","--out_csv", default="_local/within_naming.csv",
                    help="Output CSV (flat)")
    ap.add_argument("-x","--out_xlsx", default="_local/within_naming.xlsx",
                    help="Output XLSX (MultiIndex)")
    args = ap.parse_args()

    df = build_within_otm_table(args.hierarchy_json, args.mapping)

    # Flat CSV
    df.to_csv(args.out_csv, index=False, encoding="utf-8-sig")
    print(f"[ok] saved {args.out_csv}")

    # MultiIndex XLSX: (list_no, list_nm, account_cd, account_nm) as index
    df_mi = (df.set_index(["list_no","list_nm","account_cd","account_nm"])
               .sort_index())

    with pd.ExcelWriter(args.out_xlsx, engine="xlsxwriter") as writer:
        df_mi.to_excel(writer, sheet_name="multiindex", index=True)
        wb = writer.book
        ws = writer.sheets["multiindex"]

        hdr = wb.add_format({"bold": True, "font_name": "Malgun Gothic", "font_size": 11})
        body = wb.add_format({"font_name": "Malgun Gothic", "font_size": 10})
        ws.set_row(0, None, hdr)

        # autosize columns
        tmp_reset = df_mi.reset_index()
        for j, col in enumerate(tmp_reset.columns):
            width = max(12, min(44, max(len(str(col)),
                                        *(len(str(x)) for x in tmp_reset[col].head(200))) + 2))
            ws.set_column(j, j, width, body)

        # freeze header + index levels (4 levels)
        ws.freeze_panes(1, 4)

    print(f"[ok] saved {args.out_xlsx} (multiindex sheet)")

# ---- merge the column map --- #
def _norm(s) -> str:
    if s is None:
        return ""
    s = str(s).strip()
    return "" if s in {"nan", "NaN", "None"} else s

def _finance_map_from_xml(xml_path: Union[str, Path]) -> Dict[str, str]:
    """Parse FISIS XML (finance_cd, finance_nm) → dict."""
    p = Path(xml_path)
    if not p.exists():
        raise FileNotFoundError(f"Finance XML not found: {p}")
    text = p.read_text(encoding="utf-8", errors="ignore")
    root = ET.fromstring(text)

    mapping: Dict[str, str] = {}
    for row in root.findall(".//row"):
        cd = _norm(row.findtext("finance_cd"))
        nm = _norm(row.findtext("finance_nm"))
        if cd:
            mapping[cd] = nm
    return mapping



@dataclass
class FISISNamer:
    # fast lookup maps
    finance: Dict[str, str]
    list_map: Dict[str, str]
    acct_nm: Dict[Tuple[str, str], str]           # (list_no, account_cd) -> account_nm
    acct_within_nm: Dict[Tuple[str, str], str]    # (list_no, account_cd) -> within_account_nm
    col_map: Dict[Tuple[str, str, str], str]      # (list_no, account_cd, column_id) -> column_nm

    @classmethod
    def from_csvs(
        cls,
        within_csv: Union[str, Path, pd.DataFrame],
        colmap_csv: Union[str, Path, pd.DataFrame],
        *,
        encoding: str = "utf-8",
        finance_xml: Union[str, Path, None] = None,
    ) -> "FISISNamer":
        # --- load ---
        wdf = within_csv if isinstance(within_csv, pd.DataFrame) else pd.read_csv(within_csv, dtype=str, encoding=encoding)
        cdf = colmap_csv if isinstance(colmap_csv, pd.DataFrame) else pd.read_csv(colmap_csv, dtype=str, encoding=encoding)

        # --- normalize ---
        for df in (wdf, cdf):
            for c in df.columns:
                df[c] = df[c].map(_norm)

        # --- finance / list maps (guarded: columns may be missing) ---
        finance: Dict[str, str] = {}
        if {"finance_cd", "finance_nm"}.issubset(wdf.columns):
            finance = (
                wdf.loc[wdf["finance_cd"] != "", ["finance_cd", "finance_nm"]]
                .drop_duplicates("finance_cd")
                .set_index("finance_cd")["finance_nm"]
                .to_dict()
            )

        list_map: Dict[str, str] = {}
        if {"list_no", "list_nm"}.issubset(wdf.columns):
            list_map = (
                wdf.loc[wdf["list_no"] != "", ["list_no", "list_nm"]]
                .drop_duplicates("list_no")
                .set_index("list_no")["list_nm"]
                .to_dict()
            )

        # --- account maps (guarded) ---
        acct_nm: Dict[Tuple[str, str], str] = {}
        acct_within_nm: Dict[Tuple[str, str], str] = {}
        if {"list_no", "account_cd", "account_nm"}.issubset(wdf.columns):
            acct_nm = {
                (r.list_no, r.account_cd): r.account_nm
                for r in wdf.loc[(wdf["list_no"] != "") & (wdf["account_cd"] != ""), ["list_no", "account_cd", "account_nm"]]
                    .drop_duplicates(["list_no", "account_cd"]).itertuples()
            }
        if {"list_no", "account_cd", "within_account_nm"}.issubset(wdf.columns):
            acct_within_nm = {
                (r.list_no, r.account_cd): r.within_account_nm
                for r in wdf.loc[(wdf["list_no"] != "") & (wdf["account_cd"] != ""), ["list_no", "account_cd", "within_account_nm"]]
                    .drop_duplicates(["list_no", "account_cd"]).itertuples()
            }

        # --- column map from fsis/fisis colmap CSV (required cols) ---
        required_cols = {"list_no", "account_cd", "column_id", "column_nm"}
        missing = required_cols - set(cdf.columns)
        if missing:
            raise ValueError(f"column-map CSV is missing columns: {sorted(missing)}")

        col_map: Dict[Tuple[str, str, str], str] = {}
        for r in cdf.loc[
            (cdf["list_no"] != "") & (cdf["account_cd"] != "") & (cdf["column_id"] != ""),
            ["list_no", "account_cd", "column_id", "column_nm"]
        ].itertuples(index=False):
            key = (r.list_no, r.account_cd, r.column_id)
            if key not in col_map:  # keep first occurrence
                col_map[key] = r.column_nm

        # --- optional finance XML merge (fill gaps only) ---
        if finance_xml:
            try:
                xml_map = _finance_map_from_xml(finance_xml)
                for k, v in xml_map.items():
                    if k not in finance or not finance[k]:
                        finance[k] = v
            except Exception as e:
                # Don't crash app if the XML is malformed; keep running without it.
                print(f"[FISISNamer] finance_xml parse warning: {e}")

        return cls(
            finance=finance,
            list_map=list_map,
            acct_nm=acct_nm,
            acct_within_nm=acct_within_nm,
            col_map=col_map,
        )


    # ---------------- label API ----------------
    def finance_label(self, finance_cd: str, include_id: bool = True) -> str:
        finance_cd = _norm(finance_cd)
        nm = self.finance.get(finance_cd, "")
        return self._fmt(finance_cd, nm, include_id)

    def list_label(self, list_no: str, include_id: bool = True) -> str:
        list_no = _norm(list_no)
        nm = self.list_map.get(list_no, "")
        return self._fmt(list_no, nm, include_id)

    def account_label(self, list_no: str, account_cd: str, *, descendent: bool, include_id: bool = True) -> str:
        list_no, account_cd = _norm(list_no), _norm(account_cd)
        nm = (self.acct_within_nm if descendent else self.acct_nm).get((list_no, account_cd), "")
        if not nm and descendent:  # fallback to normal name if 'within' missing
            nm = self.acct_nm.get((list_no, account_cd), "")
        return self._fmt(account_cd, nm, include_id)

    def column_label(self, list_no: str, account_cd: Optional[str], column_id: str, include_id: bool = True) -> str:
        list_no, account_cd, column_id = _norm(list_no), _norm(account_cd), _norm(column_id)

        nm = ""
        if account_cd:
            nm = self.col_map.get((list_no, account_cd, column_id), "")

        # sensible fallback: try any account under the list for same column_id
        if not nm:
            for (ln, _acd, cid), v in self.col_map.items():
                if ln == list_no and cid == column_id:
                    nm = v
                    break

        # last resort: just show column_id
        return self._fmt(column_id, nm, include_id)

    @staticmethod
    def _fmt(id_: str, nm: str, include_id: bool) -> str:
        if nm and include_id:
            return f"{id_} · {nm}"
        return nm or id_


if __name__ == "__main__":
    main()
