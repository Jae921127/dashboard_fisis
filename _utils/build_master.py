# build_master.py  (lite / fragile version)

import os, json, requests, re
import xml.etree.ElementTree as ET
import pandas as pd
from typing import Iterable, Optional, Dict, List
from settings import DEFAULTS

API_KEY = DEFAULTS["api_key"]
STATS_INFO_URL = "https://fisis.fss.or.kr/openapi/statisticsInfoSearch.xml"

def _canon_fin_cd_series(s: pd.Series) -> pd.Series:
    return (s.astype(str).str.strip().str.extract(r"(\d+)", expand=False).fillna("").str.zfill(7))

def _get_required_codes_from_spec(section_cfgs: List[Dict]) -> set[tuple[str, str]]:
    """Parses section configs to find all unique (list_no, account_cd) pairs."""
    required_pairs = set()
    token_re = re.compile(r"\b(SH\d{3}):([A-Z0-9]+)\b")
    for cfg in section_cfgs:
        full_spec = cfg.get("spec", "") + " " + cfg.get("expr", "")
        matches = token_re.findall(full_spec)
        for list_no, account_cd in matches:
            required_pairs.add((list_no, account_cd))
    return required_pairs

def _generate_expected_months(start: str, end: str, term: str) -> set[str]:
    """Generates the set of YYYYMM strings expected for a given time range and term."""
    freq_map = {"Q": "QS-DEC", "H": "6MS", "Y": "AS-DEC"}
    if term not in freq_map: return set()
    try:
        dates = pd.to_datetime(pd.date_range(start=f"{start[:4]}-{start[4:]}", end=f"{end[:4]}-{end[4:]}", freq=freq_map[term]))
        if term == "Q": return {d.strftime('%Y%m') for d in (dates + pd.DateOffset(months=2))}
        if term == "H": return {d.strftime('%Y%m') for d in (dates + pd.DateOffset(months=5))}
        if term == "Y": return {d.strftime('%Y%m') for d in (dates + pd.DateOffset(months=11))}
    except Exception:
        return set()
    return set()




def _perform_sanity_check(df: pd.DataFrame, required_finance_cds: set, required_list_nos: set, required_months: set, term: str) -> bool:
    """Checks if the cached dataframe contains all required data points."""
    if df.empty: return False

    cached_finance_cds = set(_canon_fin_cd_series(df["finance_cd"]))
    cached_list_nos = set(df["list_no"])
    cached_months = set(df["base_month"].astype(str))

    if not required_finance_cds.issubset(cached_finance_cds):
        print(f"Cache check failed: Missing finance_cd(s): {required_finance_cds - cached_finance_cds}")
        return False

    if not required_list_nos.issubset(cached_list_nos):
        print(f"Cache check failed: Missing list_no(s): {required_list_nos - cached_list_nos}")
        return False


    if term == "Q":
        essential_endings = {"03", "06", "09", "12"}
    elif term == "H":
        essential_endings = {"06", "12"}
    elif term == "Y":
        essential_endings = {"12"}
    else:
        essential_endings = set() 

    if essential_endings:
        essential_months = {m for m in required_months if m[4:6] in essential_endings}
    else:

        essential_months = required_months

    if not essential_months.issubset(cached_months):
        print(f"Cache check failed: Missing essential base_month(s) for term '{term}': {sorted(essential_months - cached_months)}")
        return False

    print("Cache sanity check passed.")
    return True

def _get_required_terms_per_list(section_cfgs: List[Dict], global_term: str) -> Dict[str, str]:
    """
    Determines the required term ('Q', 'H', 'Y') for each list_no based on section settings.
    This version is refactored to handle hybrid sections.
    """
    terms_by_list = {}
    precedence = {"Q": 3, "H": 2, "Y": 1}
    token_re = re.compile(r"\b(SH\d{3})\b")

    for cfg in section_cfgs:
        num_sub = cfg.get("sub_sec", 1)

        specs = cfg.get("spec", [])
        if isinstance(specs, str): specs = [specs]
        
        exprs = cfg.get("expr", [])
        if isinstance(exprs, str): exprs = [exprs]

        terms = cfg.get("term", [])
        if isinstance(terms, str): terms = [terms]

        if len(terms) < num_sub:
            terms.extend([global_term] * (num_sub - len(terms)))


        for i in range(num_sub):
            term_for_section = terms[i]

            spec_item = specs[i] if i < len(specs) else ""
            expr_item = exprs[i] if i < len(exprs) else ""

            full_spec = spec_item + " " + expr_item
            list_nos_in_spec = token_re.findall(full_spec)

            for ln in set(list_nos_in_spec):
                if ln not in terms_by_list or precedence.get(term_for_section, 0) > precedence.get(terms_by_list.get(ln), 0):
                    terms_by_list[ln] = term_for_section

    return terms_by_list


def _get_xml_root(url: str, params: dict, timeout: int = 15) -> ET.Element:
    r = requests.get(url, params=params, timeout=timeout)
    r.raise_for_status()
    

    decoded_content = r.content.decode('euc-kr')
    
    return ET.fromstring(decoded_content)

def _as_list(x) -> List[str]:
    if x is None:
        return []
    if isinstance(x, (list, tuple, set)):
        return [str(v) for v in x]
    return [str(x)]

def _to_num(s):
    if s is None:
        return None
    s = str(s).strip()
    if s == "":
        return None
    try:
        return int(s)
    except Exception:
        try:
            return float(s)
        except Exception:
            return None


def build_master_dataframe(
    financeCd: str = "0010597",
    term: str = "Q",
    startBaseMm: str = "202209",
    endBaseMm: str = "202306",
    listNo: Optional[Iterable[str]] = None,
    hierarchy_json_path: str = "fisis_hierarchy.json",
    api_key: str = API_KEY,
) -> pd.DataFrame:
    """
    Fragile/light version:
    - assumes UTF-8/valid XML from API
    - no retries, no special encoding handling
    - no dtype normalization beyond what's naturally parsed
    """

    with open(hierarchy_json_path, "r", encoding="utf-8") as f:
        HIER: Dict[str, dict] = json.load(f)


    req_lists = _as_list(listNo)
    lists = sorted(HIER.keys()) if not req_lists else [ln for ln in req_lists if ln in HIER]

    out_rows = []

    for ln in lists:
        H = HIER.get(ln, {})
        list_nm = H.get("list_nm", "")
        acct_map: Dict[str, str] = H.get("accounts", {}) or {}
        col_map: Dict[str, str] = H.get("columns", {}) or {}

        account_cds = sorted([c for c in acct_map.keys() if c])
        column_ids = sorted([c for c in col_map.keys() if c])
        if not column_ids:
            continue

        params = {
            "lang": "kr",
            "auth": api_key,
            "financeCd": financeCd,
            "listNo": ln,
            "term": term,
            "startBaseMm": startBaseMm,
            "endBaseMm": endBaseMm,
        }
        print(f"Querying API for financeCd={financeCd}, listNo={ln}, term={term}...")
        root = _get_xml_root(STATS_INFO_URL, params, timeout=15)
        rows_found = root.findall(".//list/row")
        print(f" -> Found {len(rows_found)} rows.")

        for row in root.findall(".//list/row"):
            base_month = (row.findtext("base_month") or "").strip()
            row_fin_cd = (row.findtext("finance_cd") or "").strip()
            a_cd = (row.findtext("account_cd") or "").strip()

            if account_cds and a_cd and (a_cd not in account_cds):
                continue

            a_nm = acct_map.get(a_cd, (row.findtext("account_nm") or "").strip())

            for col_id in column_ids:
                raw_val = row.findtext(col_id)
                val = _to_num(raw_val)
                out_rows.append({
                    "list_no": ln,
                    "list_nm": list_nm,
                    "finance_cd": row_fin_cd or financeCd,
                    "term": term,
                    "base_month": base_month,
                    "account_cd": a_cd,
                    "account_nm": a_nm,
                    "column_id": col_id,                 
                    "column_nm": col_map.get(col_id, ""),
                    "value": val,
                })

    df = pd.DataFrame(out_rows, columns=[
        "list_no","list_nm","finance_cd","term","base_month",
        "account_cd","account_nm","column_id","column_nm","value"
    ])

    if not df.empty:

        df = df.sort_values(["list_no","account_cd","column_id","base_month"], kind="stable").reset_index(drop=True)
    return df

def build_master_for_codes(
    financeCds: Iterable[str],
    *,
    startBaseMm: str,
    endBaseMm: str,
    terms_by_list: Dict[str, str], 
    hierarchy_json_path: str,
    api_key: str = "ASK FOR API KEY IF NEEDED",
) -> pd.DataFrame:
    """
    Builds a master dataframe by making term-specific API calls for each list.
    """

    lists_by_term = {}
    for ln, term in terms_by_list.items():
        if term not in lists_by_term:
            lists_by_term[term] = []
        lists_by_term[term].append(ln)

    all_frames = []

    for term, list_nos in lists_by_term.items():
        print(f"Fetching {len(list_nos)} lists for term '{term}'...")
        frames_for_term = []
        for cd in (financeCds or []):
            df = build_master_dataframe(
                financeCd=str(cd),
                term=term,
                startBaseMm=startBaseMm,
                endBaseMm=endBaseMm,
                listNo=list_nos,
                hierarchy_json_path=hierarchy_json_path,
                api_key=api_key,
            )
            if not df.empty:
                frames_for_term.append(df)

        if frames_for_term:
            all_frames.append(pd.concat(frames_for_term, ignore_index=True))

    return pd.concat(all_frames, ignore_index=True) if all_frames else pd.DataFrame()


def load_or_build_master_for_market(
    financeCds: Iterable[str],
    *,
    term: str,
    startBaseMm: str,
    endBaseMm: str,
    listNo: list,
    section_cfgs: list,
    hierarchy_json_path: str,
    cache_path: str = "_local/master_df.csv",
    api_key: str = "02b3ed82f4d6fe3bc6be393add09a0ed",
) -> pd.DataFrame:
    """Loads data from cache if it's valid, otherwise builds from API and saves."""

    terms_by_list = _get_required_terms_per_list(section_cfgs, global_term=term)
    required_list_nos = set(terms_by_list.keys()).union(set(listNo))


    required_months = set()
    for t in set(terms_by_list.values()):
        required_months.update(_generate_expected_months(startBaseMm, endBaseMm, t))

    required_finance_cds = {str(cd) for cd in (financeCds or [])}


    if cache_path and os.path.exists(cache_path):
        try:
            df_cache = pd.read_csv(cache_path)

            if _perform_sanity_check(df_cache, required_finance_cds, required_list_nos, required_months, term=term):
                return df_cache
            else:
                print("Cache is stale or incomplete. Rebuilding...")
        except Exception as e:
            print(f"Could not read cache file. Rebuilding... Error: {e}")


    print("Building master dataframe from API...")
    if not financeCds:
        return pd.DataFrame()

    df_new = build_master_for_codes(
        financeCds,
        startBaseMm=startBaseMm,
        endBaseMm=endBaseMm,
        terms_by_list=terms_by_list, 
        hierarchy_json_path=hierarchy_json_path,
        api_key=api_key,
    )

    if cache_path and not df_new.empty:
        try:
            os.makedirs(os.path.dirname(cache_path), exist_ok=True)
            df_new.to_csv(cache_path, index=False, encoding="utf-8-sig")
            print(f"Successfully saved new cache to {cache_path}")
        except Exception as e:
            print(f"Error saving new cache file: {e}")

    return df_new


if __name__ == "__main__":
    df = build_master_dataframe(
        financeCd="0010597",
        term="Q",
        startBaseMm="202301",
        endBaseMm="202401",
        listNo=["SH150"],
        hierarchy_json_path="fisis_hierarchy.json",
    )
    print(df.head())
