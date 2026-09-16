def after_tool_callback(tool, tool_input, callback_context, tool_response):
    """
    Runs immediately after any setter tool finishes:
    1. If previous order was completed/escalated, clears old state first so old slots never leak!
    2. If tool returned an error ('error': True), appends to sm['_slot_errors'].
    3. If tool succeeded ('stored': True), updates sm['filled'] and enforces Mid-Flow Branch Pivot Purging.
    """
    import json

    raw_sm = callback_context.state.get("sm", "{}")
    if isinstance(raw_sm, str):
        try:
            sm = json.loads(raw_sm) if raw_sm else {}
        except Exception:
            sm = {}
    elif isinstance(raw_sm, dict):
        sm = raw_sm
    else:
        sm = {}

    # CRITICAL FIX: Clear state if previous order was complete/escalated so old slots never resurrect!
    if sm.get("status") in ("complete", "escalated"):
        preserved_channel = sm.get("filled", {}).get("channel", "MOBILE")
        sm.clear()
        sm["filled"] = {"channel": preserved_channel}
        sm["status"] = "in_progress"
        sm["task_results"] = {}
        sm["_slot_errors"] = []

    filled = sm.setdefault("filled", {})
    task_results = sm.setdefault("task_results", {})
    slot_errors = sm.setdefault("_slot_errors", [])

    res = tool_response.get("result", tool_response) if isinstance(tool_response, dict) else {}
    if isinstance(res, dict):
        if res.get("error") and res.get("agent_action"):
            slot_errors.append(res)
        elif res.get("stored") and res.get("slot"):
            slot_name = res["slot"]
            new_val = res["value"]
            old_val = filled.get(slot_name)

            # Mid-Flow Branch Pivot Purging Rule:
            if old_val is not None and old_val != new_val and slot_name in ("flavor", "quantity"):
                if "pickup_time" in filled or sm.get("_last_asked_slot") == "pickup_time":
                    sm["_pivoted_flavor"] = new_val if slot_name == "flavor" else filled.get("flavor", "")
                filled.pop("available_times", None)
                filled.pop("pickup_time", None)
                task_results.pop("check_bakery_inventory", None)
                task_results.pop("CheckBakeryInventoryTask", None)

            filled[slot_name] = new_val

    callback_context.state["sm"] = json.dumps(sm)
    return None
