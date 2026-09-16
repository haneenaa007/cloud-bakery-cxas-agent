def set_frosting(frosting_name: str) -> dict:
    """Record frosting style (CREAM_CHEESE, BUTTERCREAM, CHOCOLATE_GANACHE).

    Call immediately when the user mentions their preferred frosting.
    """
    valid = {"CREAM_CHEESE", "BUTTERCREAM", "CHOCOLATE_GANACHE"}
    val = str(frosting_name).upper().strip().replace(" ", "_")
    if "BUTTER" in val:
        val = "BUTTERCREAM"
    elif "CHEESE" in val or val == "CREAM":
        val = "CREAM_CHEESE"
    elif "CHOC" in val or "GANACHE" in val:
        val = "CHOCOLATE_GANACHE"
    elif "VANILLA" in val:
        val = "BUTTERCREAM"

    if val not in valid:
        return {
            "error": True,
            "error_code": "unsupported_frosting",
            "agent_action": (
                f"We don't offer {frosting_name} frosting. "
                "Ask the customer to choose Cream Cheese, Vanilla Buttercream, or Chocolate Ganache."
            )
        }
    return {"stored": True, "slot": "frosting", "value": val}
