def set_pickup_time(time_slot: str) -> dict:
    """Record requested pickup time slot from available oven batches ('2:00 PM', '4:30 PM', '6:00 PM').

    Call immediately when the user selects or states a pickup time.
    """
    cleaned = str(time_slot).strip().upper()
    if cleaned in ("2 PM", "2PM", "2:00 PM", "2:00PM", "2", "14:00"):
        return {"stored": True, "slot": "pickup_time", "value": "2:00 PM"}
    elif cleaned in ("4:30 PM", "4:30PM", "4:30", "4 PM", "4PM", "16:30"):
        return {"stored": True, "slot": "pickup_time", "value": "4:30 PM"}
    elif cleaned in ("6 PM", "6PM", "6:00 PM", "6:00PM", "6", "18:00"):
        return {"stored": True, "slot": "pickup_time", "value": "6:00 PM"}

    return {
        "error": True,
        "error_code": "unavailable_batch_time",
        "agent_action": (
            f"We don't have an oven batch at {time_slot}! "
            "Politely let the customer know our fresh oven batches today are at 2:00 PM, 4:30 PM, and 6:00 PM, "
            "and ask which of those three times works best."
        )
    }
