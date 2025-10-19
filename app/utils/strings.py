def coerce_str(x):
    if x is None:
        return ""
    if isinstance(x, (float, int)):
        if isinstance(x, float) and x.is_integer():
            return str(int(x))
        return str(x)
    if isinstance(x, str):
        return x
    try:
        return str(x)
    except Exception:
        return ""