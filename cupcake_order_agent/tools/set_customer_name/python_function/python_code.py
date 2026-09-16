def set_customer_name(name: str) -> dict:
    """Record customer name for the pickup order box.

    Call immediately when the user provides their name.
    """
    cleaned = str(name).strip()
    if len(cleaned) < 2:
        return {
            "error": True,
            "error_code": "invalid_name",
            "agent_action": "Politely ask for the customer's name so we can label their cupcake box."
        }
    return {"stored": True, "slot": "customer_name", "value": cleaned.title()}
