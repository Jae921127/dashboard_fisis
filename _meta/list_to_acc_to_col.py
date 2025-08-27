# fisis_list_to_account_to_column_map.py
import time
import re
import requests
import xml.etree.ElementTree as ET
import pandas as pd
import sys, os

# -------- Settings --------
API_KEY = "02b3ed82f4d6fe3bc6be393add09a0ed"

# financeCd is required by statisticsInfoSearch; use any valid code.
FINANCE_CD = "0010593"   # (한화생명 etc. - used only to satisfy API param)

# term / period (choose a short window; we only need schema, not values)
TERM = "Y"
START_BASE_MM = "202201"
END_BASE_MM   = "202401"

# Endpoints
STATS_LIST_URL = "https://fisis.fss.or.kr/openapi/statisticsListSearch.xml"
STATS_INFO_URL = "https://fisis.fss.or.kr/openapi/statisticsInfoSearch.xml"

# --- Optional: make console UTF-8 for pretty prints ---
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
os.environ.setdefault("PYTHONUTF8", "1")

# --------- Encoding helpers ----------
ENC_DECL_RE = re.compile(rb'^<\?xml[^>]*encoding=["\']([^"\']+)["\']', re.IGNORECASE)

def _extract_declared_encoding(xml_bytes: bytes) -> str | None:
    m = ENC_DECL_RE.search(xml_bytes)
    if not m:
        return None
    return m.group(1).decode('ascii', errors='ignore').lower()

def _to_utf8_xml_bytes(xml_bytes: bytes) -> bytes:
    enc = _extract_declared_encoding(xml_bytes)
    if enc is None or enc in ("utf-8", "utf8", "utf-16", "utf16"):
        return xml_bytes
    for codec in (enc, "euc-kr", "cp949", "ms949"):
        try:
            text = xml_bytes.decode(codec)
            text = re.sub(r'(?i)(<\?xml[^>]*encoding=["\'])[^"\']+(["\'])',
                          r'\1utf-8\2', text, count=1)
            return text.encode("utf-8")
        except Exception:
            continue
    text = xml_bytes.decode(enc, errors="replace")
    text = re.sub(r'(?i)(<\?xml[^>]*encoding=["\'])[^"\']+(["\'])',
                  r'\1utf-8\2', text, count=1)
    return text.encode("utf-8")

# --------- HTTP/XML helpers ----------
def _get_xml_root(url: str, params: dict, timeout=25) -> ET.Element:
    r = requests.get(url, params=params, timeout=timeout)
    r.raise_for_status()
    xml_utf8 = _to_utf8_xml_bytes(r.content)
    root = ET.fromstring(xml_utf8)

    # FISIS error envelope (if any)
    err_cd = root.findtext(".//err_cd")
    err_msg = root.findtext(".//err_msg")
    if err_cd and err_cd != "000":
        raise RuntimeError(f"API error {err_cd}: {err_msg}")
    return root

# --------- Step 1: get all (list_no, list_nm) from statisticsListSearch ---------
def fetch_stats_list_all(lrgDiv="H", sleep_sec=0.1, max_pages=200) -> pd.DataFrame:
    page = 1
    rows = []
    while page <= max_pages:
        params = {
            "lang": "kr",
            "auth": API_KEY,
            "lrgDiv": lrgDiv,
            "pageNo": page
        }
        root = _get_xml_root(STATS_LIST_URL, params=params)
        page_rows = root.findall(".//row")
        if not page_rows:
            break

        for row in page_rows:
            rows.append({
                "list_no": row.findtext("list_no"),
                "list_nm": row.findtext("list_nm"),
            })
        page += 1
        time.sleep(sleep_sec)

    if not rows:
        return pd.DataFrame(columns=["list_no", "list_nm"])

    df = pd.DataFrame(rows, columns=["list_no", "list_nm"])

    # Only dedup by list_no (keep first) — per requirement
    before = len(df)
    df = df.drop_duplicates(subset=["list_no"], keep="first")
    after = len(df)
    if before != after:
        print(f"[info] Dropped {before - after} duplicated list_no entries.")

    return df.sort_values(["list_no"], kind="stable").reset_index(drop=True)

# --------- Step 2: for each list_no, use statisticsInfoSearch to get accounts & columns ---------
def fetch_info_schema_and_accounts(list_no: str,
                                   finance_cd: str = FINANCE_CD,
                                   term: str = TERM,
                                   start_mm: str = START_BASE_MM,
                                   end_mm: str = END_BASE_MM,
                                   max_retries: int = 3,
                                   sleep_sec: float = 0.2):
    """
    Returns:
      columns: list[(column_id, column_nm)]
      accounts: list[(account_cd, account_nm)]
    We use one call and ignore row values; we only need schema (description) + distinct accounts.
    """
    params = {
        "lang": "kr",
        "auth": API_KEY,
        "financeCd": finance_cd,
        "listNo": list_no,
        "term": term,
        "startBaseMm": start_mm,
        "endBaseMm": end_mm
    }

    for attempt in range(1, max_retries + 1):
        try:
            root = _get_xml_root(STATS_INFO_URL, params=params)

            # 2.a Parse <description>/<column>
            columns = []
            for col_node in root.findall(".//description/column"):
                col_id = (col_node.findtext("column_id") or "").strip()
                col_nm = (col_node.findtext("column_nm") or "").strip()
                if col_id:
                    columns.append((col_id, col_nm))

            # 2.b Collect distinct (account_cd, account_nm) from <list>/<row>
            acct_set = set()
            for row in root.findall(".//list/row"):
                a_cd = (row.findtext("account_cd") or "").strip()
                a_nm = (row.findtext("account_nm") or "").strip()
                if a_cd:
                    acct_set.add((a_cd, a_nm))
            accounts = sorted(acct_set)

            time.sleep(sleep_sec)
            return columns, accounts
        except Exception as e:
            if attempt == max_retries:
                print(f"[ERROR] statisticsInfoSearch list_no={list_no}: {e}")
                return [], []
            time.sleep(0.8 * attempt)

# --------- Step 3/4: Build the 3-level mapping and save ---------
def main():
    # 1) Master (list_no, list_nm)
    master = fetch_stats_list_all(lrgDiv="H")
    if master.empty:
        print("[warn] No (list_no, list_nm) fetched.")
        return
    print(f"[ok] Statistics lists fetched: {len(master)}")

    # 2) For each list_no, pull schema & accounts, then form cartesian (account x column)
    out_rows = []
    for _, rec in master.iterrows():
        ln = str(rec["list_no"])
        lm = rec["list_nm"]
        columns, accounts = fetch_info_schema_and_accounts(ln)

        if not columns and not accounts:
            # Preserve the list even if there is no schema/accounts
            out_rows.append({
                "list_no": ln, "list_nm": lm,
                "account_cd": None, "account_nm": None,
                "column_id": None, "column_nm": None
            })
            continue

        if not accounts:
            # Schema exists but no accounts in the slice; still keep schema
            for col_id, col_nm in columns:
                out_rows.append({
                    "list_no": ln, "list_nm": lm,
                    "account_cd": None, "account_nm": None,
                    "column_id": col_id, "column_nm": col_nm
                })
            continue

        # One-to-many-to-many mapping:
        # (list_no,list_nm) → each (account_cd,account_nm) → each (column_id,column_nm)
        for a_cd, a_nm in accounts:
            for col_id, col_nm in columns:
                out_rows.append({
                    "list_no": ln, "list_nm": lm,
                    "account_cd": a_cd, "account_nm": a_nm,
                    "column_id": col_id, "column_nm": col_nm
                })

    df = pd.DataFrame(
        out_rows,
        columns=["list_no", "list_nm", "account_cd", "account_nm", "column_id", "column_nm"]
    )

    # Do NOT drop duplicates (other than list_no handled before) — per requirement
    # Natural MultiIndex form:
    df_mi = df.set_index(["list_no", "list_nm", "account_cd", "account_nm", "column_id", "column_nm"]).sort_index()

    # ---- Save outputs ----
    csv_path = "_local/fisis_list_account_column_map.csv"
    xlsx_path = "_local/fisis_list_account_column_map.xlsx"

    # CSV (UTF-8 BOM) for Excel compatibility
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    print(f"[ok] Saved CSV: {csv_path}")

    with pd.ExcelWriter(xlsx_path, engine="xlsxwriter") as writer:
        # Flat mapping
        df.to_excel(writer, index=False, sheet_name="flat")

        # MultiIndex view (index=True → levels as index columns)
        df_mi.to_excel(writer, sheet_name="multiindex")

        wb = writer.book
        base_font = "Malgun Gothic"  # or "NanumGothic"
        hdr_fmt = wb.add_format({"bold": True, "font_name": base_font, "font_size": 11})
        body_fmt = wb.add_format({"font_name": base_font, "font_size": 10})

        ws_flat = writer.sheets["flat"]
        ws_flat.set_column(0, df.shape[1]-1, 24, body_fmt)
        for j, name in enumerate(df.columns):
            ws_flat.write(0, j, name, hdr_fmt)

        ws_mi = writer.sheets["multiindex"]
        ws_mi.set_column(0, 12, 24, body_fmt)

    print(f"[ok] Saved XLSX: {xlsx_path} (flat + multiindex)")

if __name__ == "__main__":
    main()
