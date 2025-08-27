# config.py
from pathlib import Path
from _utils.utils import resource_path

ROOT = Path(__file__).resolve().parents[0]
LOCAL = ROOT / "_local"

LOCAL.mkdir(exist_ok=True)

DEFAULTS = {
    "api_key": "02b3ed82f4d6fe3bc6be393add09a0ed",
    "list_nos": ["SH150", "SH151"],
    "target_finance_cd": "0010607",
    "term": "Q",
    "startBaseMm": "202001",
    "endBaseMm": "202312",
    "colid": "a",
    "sections": [
        {
            "section_id" : "G",
            "section_label": "성장성", # This is for Growth Potential Analysis
            "content": [
                {"sec": "G1", "title": "재무:: 자산 vs 부채/자본", "sub_sec":2, "spec": ["SH003:A + SH004:A1 + SH004:A2","SH150:A + SH151:A + SH151:F"], "expr": ["SH003:A/SH004:A2","SH150:A/SH151:F"],"expr_nm":["자산/자본","자산/자본"],"date":[["start","202212"],["202301","end"]],"colid":["a","b"]},
                {"sec": "G2", "title": "상품:: 보험료 수입 vs 지급보험금", "sub_sec":2, "spec": ["SH018 + SH019","SH166 + SH167"],"expr":["SH018/SH019","SH166/SH167"],"expr_nm":["수입/지출","수입/지출"],"date":[["start","202212"],["202301","end"]],"colid":["a","b", "c","d"]},
                {"sec": "G3", "title": "상품:: 보유 vs 신계약", "sub_sec":2, "spec": ["SH016 + SH017","SH160 + SH161"], "expr": ["SH017/SH016","SH161/SH160"], "expr_nm": ["보유계약/신계약","보유계약/신계약"], "date": [["start","202212"],["202301","end"]], "colid":["a","b"]},
                {"sec": "G4", "title": "상품:: 계약유지율", "sub_sec": 1, "spec": ["SH025"], "date": [["start","end"]], "expr": ["SH025:B/SH025:A"], "expr_nm": ["25회차/13회차"], "colid":[ "a"], "term":"H"},
                {"sec": "G5", "title": "조직:: 임직원/설계사 + 점포/대리점", "sub_sec": 1, "spec": ["SH001 + SH002"], "expr": ["SH001:B/SH001:A"], "expr_nm": ["설계사/임직원"], "date": [["start","end"]], "colid":["a"]},
                {"sec": "G6", "title": "조직:: 신규/정착설계사", "sub_sec": 1, "spec": ["SH022:A + SH022:B"], "expr": ["SH022:B/SH022:A"], "expr_nm": ["정착/신규인원"], "colid":["a"], "date": [["start","end"]], "term":"Y"},
            ]
        },
        {
          "section_id" : "P",
          "section_label": "수익성",
          "content": [
              {"sec": "P1", "title": "계약분류:: 수입 vs 지급금", "sub_sec":2, "spec": ["SH018 + SH019", "SH166 + SH167"], "expr" : ["SH018/SH019", "SH166/SH167"], "expr_nm": ["보험료 수입/지출","보험료 수입/지출"], "date":[["start", "202212"],["202301","end"]], "colid":["a", "b", "c", "d"], "mode": "side-by-side"},
              {"sec": "P2", "title": "계약분류:: 신계약 vs 보유계약", "sub_sec":2 , "spec": ["SH016 + SH017", "SH160 + SH161"], "expr" : ["SH017/SH016", "SH161/SH160"], "expr_nm": ["보유계약/신계약","보유계약/신계약"], "date":[["start", "202212"],["202301","end"]],"colid":["a","b"], "mode": "side-by-side"},
              {"sec": "P3", "title": "계약방법:: 모집방법", "spec": ["SH029"], "colid":["a","b"], "mode": "account_horizontal"},
              {"sec": "P4", "title": "계약방법:: 납입방법", "spec": ["SH028"], "colid":["a","b"], "mode": "account_horizontal"},
            ]
        },
        {
          "section_id" : "S",
          "section_label": "건전성",
          "content": [
              {"sec": "S1", "title": "건전성:: 자본적정성", "sub_sec":1, "spec": ["SH021"], "date":[["start", "end"]], "colid":["a"], "mode": "elemental_line"},
            ]
        },
    ],
}

PATHS = {
    "hier_json":               resource_path("_local/fisis_hierarchy.json"),
    "finance_map_csv":         resource_path("_local/finance_cd_to_nm_map.csv"), 
    "within_naming_csv":       resource_path("_local/within_naming.csv"),
    "list_acc_col_map_csv":    resource_path("_local/fisis_list_account_column_map.csv"),
    "finance_xml":             resource_path("_local/finance_cd_import_temp.txt"),
    "terms_map_csv":           resource_path("_local/fisis_list_terms_map.csv"),
    "cache_master_csv":        resource_path("_local/master_df.csv")
}



# theme.py
INDEX_STRING = """<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Public Insight & Knowledge Analytics for Corporate Holdings and Utilisation</title>
  <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:FILL@0..1" />
<style>
    html, body {
      margin: 0;
      padding: 0;
      font-family: system-ui, sans-serif;
    }
    .layout { padding: 8px; }
    .panel { border:1px solid #666; border-radius:10px; padding:8px; }

    /* --- Component & Text Styles --- */
    .icon { font-family: 'Material Symbols Outlined'; font-variation-settings: 'FILL' 0; font-size:18px; }
    .toolbar-row { display:flex; gap:15px; align-items:center; flex-wrap:wrap; }
    .toolbar-group { display:inline-flex; align-items:center; gap:6px; font-size:11px; }
    .toolbar-group .Select-control { min-width: 200px; }
    .toolbar-group label { font-weight: 600; }
    .btn { display:inline-flex; align-items:center; gap:4px; padding:4px 8px; border:1px solid #ddd; border-radius:8px; cursor:pointer; background:#fff; font-size: 11px; }
    .title { margin:0 0 6px 0; color:#444; font-weight:600; font-size: 13px; }
    .kv { display:flex; justify-content:space-between; padding:2px 0; font-size: 11px; }
    .mono { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
    .js-plotly-plot .main-svg text { font-size: 10px !important; }
    .js-plotly-plot .legend text { font-size: 9px !important; }
    .share-table { width: 100%; margin-top: 15px; border-collapse: collapse; font-size: 10px; white-space: nowrap; }
    .share-table th, .share-table td { border: 1px solid #ddd; padding: 4px 6px; text-align: right; }
    .share-table th { background-color: #f8f8f8; text-align: center; font-weight: bold;}
    .share-table td:first-child { text-align: left; font-weight: bold; }
    .loading-overlay {
        position: fixed; /* Cover the entire screen */
        width: 100vw;
        height: 100vh;
        top: 0;
        left: 0;
        background-color: rgba(128, 128, 128, 0.5); /* Greyed out with 50% transparency */
        z-index: 1000; /* Appear on top of everything */
        display: flex;
        justify-content: center;
        align-items: center;
        flex-direction: column;
    }
    .loading-text {
        color: white;
        font-size: 24px;
        font-weight: bold;
    }
</style>
</head>
<body>
  {%app_entry%}
  <footer>{%config%}{%scripts%}{%renderer%}</footer>
</body>
</html>"""
