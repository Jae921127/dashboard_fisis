# helpers_hover.py
def _extract_hover(hoverData):
    if not hoverData or "points" not in hoverData or not hoverData["points"]:
        return None, None, None
    pt = hoverData["points"][0]
    base_month = pt.get("x")
    node_key = None
    firm_cd = None # <-- NEW: Variable for the firm code
    cd = pt.get("customdata")
    if isinstance(cd, dict):
        node_key = cd.get("node_key")
        firm_cd = cd.get("firm_cd") # <-- NEW: Extract firm_cd
    # This block handles older list-based customdata for backward compatibility
    elif isinstance(cd, (list, tuple)):
        for item in cd:
            if isinstance(item, dict):
                if "node_key" in item: node_key = item["node_key"]
                if "firm_cd" in item: firm_cd = item["firm_cd"] # <-- NEW
            if isinstance(item, str) and (item.startswith("list:") or item.startswith("acc:")):
                node_key = item
    return node_key, base_month, firm_cd

def _hover_key(hoverData):
    if not hoverData:
        return None
    # _extract_hover returns (node_key, base_month, firm_cd). We only want the first item.
    return _extract_hover(hoverData)[0]

def _hover_month(hoverData):
    if not hoverData or "points" not in hoverData or not hoverData["points"]:
        return None
    return hoverData["points"][0].get("x")
