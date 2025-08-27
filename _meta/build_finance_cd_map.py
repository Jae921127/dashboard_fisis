# build_finance_cd_map.py
"""
Extract finance_cd | finance_nm | finance_group from an FISIS finance list TXT (XML) and
save to finanace_cd_to_nm_map.csv.

Usage:
  python build_finance_cd_map.py /path/to/finance_cd_import_temp.txt
"""

import sys
import os
from xml.etree import ElementTree as ET
import pandas as pd


def _middle_segment(path: str) -> str:
    """
    Return the middle segment of a slash-separated path.
    Example: '생명보험/국내생보사/교보생명보험주식회사' -> '국내생보사'
    """
    if not path:
        return ""
    parts = [p.strip() for p in str(path).split("/") if p is not None]
    if len(parts) >= 3:
        return parts[1]
    # Fallbacks for shorter paths
    if len(parts) == 2:
        return parts[1]
    return ""


def extract_finance_cd_map(input_txt: str) -> pd.DataFrame:
    """
    Parse the XML-like TXT and return a DataFrame with:
    finance_cd | finance_nm | finance_group
    """
    # ET.parse will honor the XML's declared encoding (e.g., euc-kr)
    tree = ET.parse(input_txt)
    root = tree.getroot()

    rows = []
    # Expected structure: result/list/row with children finance_cd, finance_nm, finance_path
    for row in root.findall(".//row"):
        fin_cd = (row.findtext("finance_cd") or "").strip()
        fin_nm = (row.findtext("finance_nm") or "").strip()
        fin_path = (row.findtext("finance_path") or "").strip()
        fin_group = _middle_segment(fin_path)
        # Keep finance_cd as string to preserve leading zeros
        rows.append(
            {"finance_cd": fin_cd, "finance_nm": fin_nm, "finance_group": fin_group}
        )

    df = pd.DataFrame(rows, columns=["finance_cd", "finance_nm", "finance_group"])
    # Drop exact duplicates just in case
    df = df.drop_duplicates(subset=["finance_cd", "finance_nm", "finance_group"]).reset_index(drop=True)
    return df


def main():
    if len(sys.argv) < 2:
        print("Usage: python build_finance_cd_map.py /path/to/finance_cd_import_temp.txt")
        sys.exit(1)

    input_txt = sys.argv[1]
    out_csv = os.path.join("_local", "finanace_cd_to_nm_map.csv") 

    df = extract_finance_cd_map(input_txt)

    # Save CSV in UTF-8 with BOM for Excel-friendliness on Windows
    df.to_csv(out_csv, index=False, encoding="utf-8-sig")

    print(f"Saved {len(df):,} rows to {os.path.abspath(out_csv)}")


if __name__ == "__main__":
    main()
