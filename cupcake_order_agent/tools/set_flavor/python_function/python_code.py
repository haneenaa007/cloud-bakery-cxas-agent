def set_flavor(flavor_name: str) -> dict:
    """Record cupcake flavor in uppercase enum format (RED_VELVET, VANILLA, DARK_CHOCOLATE, SALTED_CARAMEL).

    Call immediately when the user mentions a cupcake flavor.
    """
    valid = {"RED_VELVET", "VANILLA", "DARK_CHOCOLATE", "SALTED_CARAMEL"}
    val = str(flavor_name).upper().strip().replace(" ", "_")
    if "VELVET" in val:
        val = "RED_VELVET"
    elif "VANILLA" in val:
        val = "VANILLA"
    elif "CHOC" in val:
        val = "DARK_CHOCOLATE"
    elif "CARAMEL" in val or "SALT" in val:
        val = "SALTED_CARAMEL"

    if val not in valid:
        return {
            "error": True,
            "error_code": "unsupported_flavor",
            "agent_action": (
                f"We don't bake {flavor_name} cupcakes! "
                "Politely offer Red Velvet, Vanilla, Dark Chocolate, or Salted Caramel."
            )
        }
    return {"stored": True, "slot": "flavor", "value": val}
