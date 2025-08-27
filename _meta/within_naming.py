# within_naming.py
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Dict, Tuple

import pandas as pd


def _coerce_str(s):
    if s is None:
        return ""
    s = str(s).strip()
    return "" if s in {"nan", "NaN", "None"} else s


@dataclass
class WithinNaming:
    df: pd.DataFrame
    _finance: Dict[str, str]
    _list: Dict[str, str]
    # For fast lookups: (list_no, account_cd, column_id) -> column_nm
    _col_map: Dict[Tuple[str, str, str], str]
    # Account name maps
    _acct_nm: Dict[Tuple[str, str], str]
    _acct_within_nm: Dict[Tuple[str, str], str]

    @classmethod
    def from_csv(cls, path: str | Path) -> "WithinNaming":
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"within_naming.csv not found at: {p}")

        # Expected columns (extra columns are okay)
        needed = {
            "finance_cd", "finance_nm",
            "list_no", "list_nm",
            "account_cd", "account_nm", "within_account_nm",
            "column_id", "column_nm",
        }

        df = pd.read_csv(p, dtype=str, encoding="utf-8")
        missing = [c for c in needed if c not in df.columns]
        if missing:
            raise ValueError(f"within_naming.csv missing required columns: {missing}")

        # Clean & standardize
        for c in df.columns:
            df[c] = df[c].map(_coerce_str)

        # Build maps
        finance = (
            df.loc[df["finance_cd"] != "", ["finance_cd", "finance_nm"]]
            .drop_duplicates(subset=["finance_cd"])
            .set_index("finance_cd")["finance_nm"]
            .to_dict()
        )

        list_map = (
            df.loc[df["list_no"] != "", ["list_no", "list_nm"]]
            .drop_duplicates(subset=["list_no"])
            .set_index("list_no")["list_nm"]
            .to_dict()
        )

        # account name maps (list_no, account_cd)
        acct_nm = (
            df.loc[(df["list_no"] != "") & (df["account_cd"] != ""),
                   ["list_no", "account_cd", "account_nm"]]
            .drop_duplicates(subset=["list_no", "account_cd"])
        )
        acct_nm = {(r.list_no, r.account_cd): r.account_nm for r in acct_nm.itertuples()}

        acct_within = (
            df.loc[(df["list_no"] != "") & (df["account_cd"] != ""),
                   ["list_no", "account_cd", "within_account_nm"]]
            .drop_duplicates(subset=["list_no", "account_cd"])
        )
        acct_within = {(r.list_no, r.account_cd): r.within_account_nm for r in acct_within.itertuples()}

        # column map — allow multiple rows but keep first occurrence
        col_rows = df.loc[
            (df["list_no"] != "") & (df["account_cd"] != "") & (df["column_id"] != ""),
            ["list_no", "account_cd", "column_id", "column_nm"],
        ]
        col_map: Dict[Tuple[str, str, str], str] = {}
        for r in col_rows.itertuples(index=False):
            key = (r.list_no, r.account_cd, r.column_id)
            if key not in col_map:  # keep first
                col_map[key] = r.column_nm

        return cls(
            df=df, _finance=finance, _list=list_map,
            _col_map=col_map, _acct_nm=acct_nm, _acct_within_nm=acct_within
        )

    # ---------- basic labelers ----------
    def finance_nm(self, finance_cd: str, include_id: bool = True) -> str:
        finance_cd = _coerce_str(finance_cd)
        nm = self._finance.get(finance_cd, "")
        return self._fmt(finance_cd, nm, include_id)

    def list_nm(self, list_no: str, include_id: bool = True) -> str:
        list_no = _coerce_str(list_no)
        nm = self._list.get(list_no, "")
        return self._fmt(list_no, nm, include_id)

    def account_nm(self, list_no: str, account_cd: str, *, descendent: bool = False,
                   include_id: bool = True) -> str:
        list_no, account_cd = _coerce_str(list_no), _coerce_str(account_cd)
        if descendent:
            nm = self._acct_within_nm.get((list_no, account_cd), "") or \
                 self._acct_nm.get((list_no, account_cd), "")
        else:
            nm = self._acct_nm.get((list_no, account_cd), "")
        return self._fmt(account_cd, nm, include_id)

    def column_nm(self, list_no: str, account_cd: Optional[str], column_id: str,
                  include_id: bool = True) -> str:
        """Find column name by (list_no, account_cd, column_id) with sensible fallbacks."""
        list_no = _coerce_str(list_no)
        account_cd = _coerce_str(account_cd) if account_cd is not None else ""
        column_id = _coerce_str(column_id)

        nm = ""
        # strict match first
        if account_cd:
            nm = self._col_map.get((list_no, account_cd, column_id), "")
        # fallbacks: any account under list_no
        if not nm:
            # try first match ignoring account_cd
            for (ln, acd, cid), v in self._col_map.items():
                if ln == list_no and cid == column_id:
                    nm = v
                    break
        # final fallback: search entire df by column_id only
        if not nm:
            rows = self.df.loc[self.df["column_id"] == column_id, "column_nm"]
            nm = rows.iloc[0] if len(rows) else ""

        return self._fmt(column_id, nm, include_id)

    # ---------- formatting ----------
    @staticmethod
    def _fmt(id_: str, nm: str, include_id: bool) -> str:
        if nm and include_id:
            return f"{id_} · {nm}"
        return nm or id_
