def set_quantity(count: int) -> dict:
    """Record total number of cupcakes ordered as an integer.

    Call immediately when the user mentions how many cupcakes or boxes they want.
    """
    try:
        qty = int(count)
    except Exception:
        qty = 0
    if qty <= 0:
        return {
            "error": True,
            "error_code": "invalid_count",
            "agent_action": "Ask the customer for a valid cupcake quantity (at least 1 cupcake)."
        }
    return {"stored": True, "slot": "quantity", "value": qty}
