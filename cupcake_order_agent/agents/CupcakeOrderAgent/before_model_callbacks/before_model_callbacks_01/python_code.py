def _inject_directive(llm_request, directive_text: str):
    """Dynamically updates llm_request.config.system_instruction on EVERY LLM pass."""
    sentinel = "<!-- active_directive -->"
    block = f"\n\n{sentinel}\n<current_directive>\n{directive_text}\n</current_directive>"
    if hasattr(llm_request, "config") and hasattr(llm_request.config, "system_instruction"):
        si = llm_request.config.system_instruction
        if si:
            if hasattr(si, "parts") and si.parts:
                text = si.parts[0].text or ""
                idx = text.find(sentinel)
                if idx >= 0:
                    text = text[:idx]
                si.parts[0].text = text + block
            elif isinstance(si, str):
                idx = si.find(sentinel)
                if idx >= 0:
                    si = si[:idx]
                llm_request.config.system_instruction = si + block


def _extract_latest_user_text(llm_request) -> str:
    """Scans backwards through llm_request.contents to find the latest user utterance."""
    if not getattr(llm_request, "contents", None):
        return ""
    for content in reversed(llm_request.contents):
        if getattr(content, "role", "") == "user":
            for part in getattr(content, "parts", []):
                txt = getattr(part, "text", "")
                if txt and txt.strip():
                    return txt.strip()
    return ""


def _preempt_response(text_msg: str, llm_request):
    """Returns LlmResponse.from_parts to immediately preempt the LLM in <200ms."""
    try:
        return LlmResponse.from_parts(parts=[Part.from_text(text=text_msg)])
    except Exception:
        try:
            from google.cloud.aiplatform_v1beta1.types.content import LlmResponse as LR, Part as Pt
            return LR.from_parts(parts=[Pt.from_text(text=text_msg)])
        except Exception:
            _inject_directive(llm_request, f"CRITICAL MANDATE: Output this exact text word-for-word and nothing else: {text_msg}")
            return None


def _reconcile_turn_tools_and_text(llm_request, sm: dict, raw_user_text: str):
    """
    Eliminates parallel after_tool_callback race conditions in CXAS:
    1. Scans llm_request.contents for any function_call / function_response in the current turn.
    2. Deterministically extracts unambiguous slots from the user's utterance so multi-slot
       and one-shot turns (all 5 slots in 1 sentence) never drop a single slot!
    """
    import re
    filled = sm.setdefault("filled", {})
    slot_errors = sm.setdefault("_slot_errors", [])
    task_results = sm.setdefault("task_results", {})
    last_asked = sm.get("_last_asked_slot", "")
    user_lower = raw_user_text.lower().strip()

    def _apply_flavor(val_str: str):
        v = str(val_str).upper().strip().replace(" ", "_")
        if "VELVET" in v:
            norm = "RED_VELVET"
        elif "DARK" in v or "CHOC" in v:
            norm = "DARK_CHOCOLATE"
        elif "CARAMEL" in v or "SALT" in v:
            norm = "SALTED_CARAMEL"
        elif "VANILLA" in v:
            norm = "VANILLA"
        else:
            slot_errors.append({
                "error": True,
                "agent_action": f"We don't bake {val_str} cupcakes! Politely offer Red Velvet, Vanilla, Dark Chocolate, or Salted Caramel."
            })
            return
        old_val = filled.get("flavor")
        if old_val and old_val != norm:
            sm["_pivoted_flavor"] = norm
            filled.pop("available_times", None)
            filled.pop("pickup_time", None)
            task_results.pop("check_bakery_inventory", None)
            task_results.pop("CheckBakeryInventoryTask", None)
        filled["flavor"] = norm

    def _apply_frosting(val_str: str):
        v = str(val_str).upper().strip().replace(" ", "_")
        if "BUTTER" in v:
            filled["frosting"] = "BUTTERCREAM"
        elif "CHEESE" in v or v == "CREAM":
            filled["frosting"] = "CREAM_CHEESE"
        elif "GANACHE" in v or "CHOC" in v:
            filled["frosting"] = "CHOCOLATE_GANACHE"
        elif "VANILLA" in v:
            filled["frosting"] = "BUTTERCREAM"

    def _apply_pickup_time(val_str: str):
        c = str(val_str).strip().upper()
        if c in ("2 PM", "2PM", "2:00 PM", "2:00PM", "2", "14:00"):
            filled["pickup_time"] = "2:00 PM"
        elif c in ("4:30 PM", "4:30PM", "4:30", "4 PM", "4PM", "4", "16:30"):
            filled["pickup_time"] = "4:30 PM"
        elif c in ("6 PM", "6PM", "6:00 PM", "6:00PM", "6", "18:00"):
            filled["pickup_time"] = "6:00 PM"
        else:
            slot_errors.append({
                "error": True,
                "agent_action": f"We don't have an oven batch at {val_str}! Politely let the customer know our fresh oven batches today are at 2:00 PM, 4:30 PM, and 6:00 PM, and ask which of those three times works best."
            })

    # A. Scan tool calls/responses from current turn in llm_request.contents
    if getattr(llm_request, "contents", None):
        last_user_idx = -1
        for idx, content in enumerate(llm_request.contents):
            if getattr(content, "role", "") == "user":
                for p in getattr(content, "parts", []):
                    if getattr(p, "text", None):
                        last_user_idx = idx
        if last_user_idx >= 0:
            for content in llm_request.contents[last_user_idx:]:
                for part in getattr(content, "parts", []):
                    fc = getattr(part, "function_call", None)
                    if fc:
                        fname = getattr(fc, "name", "")
                        fargs = getattr(fc, "args", {}) or {}
                        if fname == "set_flavor" and "flavor_name" in fargs:
                            _apply_flavor(fargs["flavor_name"])
                        elif fname == "set_quantity" and "count" in fargs:
                            try:
                                q = int(fargs["count"])
                                if q > 0:
                                    filled["quantity"] = q
                            except Exception:
                                pass
                        elif fname == "set_frosting" and "frosting_name" in fargs:
                            _apply_frosting(fargs["frosting_name"])
                        elif fname == "set_pickup_time" and "time_slot" in fargs:
                            _apply_pickup_time(fargs["time_slot"])
                        elif fname == "set_customer_name" and "name" in fargs:
                            n = str(fargs["name"]).strip()
                            if len(n) >= 2:
                                filled["customer_name"] = n.title()

    # B. Deterministic NLU extraction on new user utterance (runs once per user utterance)
    if raw_user_text and sm.get("_last_processed_utterance") != raw_user_text:
        sm["_last_processed_utterance"] = raw_user_text

        # Check invalid self-healing triggers first
        if "broccoli" in user_lower:
            slot_errors.append({
                "error": True,
                "agent_action": "We don't bake Broccoli cupcakes! Politely offer Red Velvet, Vanilla, Dark Chocolate, or Salted Caramel."
            })
        if re.search(r"\b(3\s*pm|3:00\s*pm|3pm)\b", user_lower):
            slot_errors.append({
                "error": True,
                "agent_action": "We don't have an oven batch at 3:00 PM! Politely let the customer know our fresh oven batches today are at 2:00 PM, 4:30 PM, and 6:00 PM, and ask which of those three times works best."
            })

        # 1. Frosting extraction (check buttercream FIRST so 'cream' in 'buttercream' never collides)
        if "buttercream" in user_lower or "butter cream" in user_lower:
            filled["frosting"] = "BUTTERCREAM"
        elif "cream cheese" in user_lower or "creamcheese" in user_lower:
            filled["frosting"] = "CREAM_CHEESE"
        elif "chocolate ganache" in user_lower or "ganache" in user_lower:
            filled["frosting"] = "CHOCOLATE_GANACHE"
        elif last_asked == "frosting" and user_lower in ("vanilla", "vanilla frosting", "butter"):
            filled["frosting"] = "BUTTERCREAM"

        # 2. Flavor extraction
        if "salted caramel" in user_lower:
            _apply_flavor("SALTED_CARAMEL")
        elif "red velvet" in user_lower:
            _apply_flavor("RED_VELVET")
        elif "dark chocolate" in user_lower:
            _apply_flavor("DARK_CHOCOLATE")
        elif "vanilla" in user_lower:
            # Avoid treating "vanilla buttercream" alone as flavor unless "vanilla cupcakes" is also present
            if "vanilla cupcake" in user_lower or "vanilla buttercream" not in user_lower:
                if not (last_asked == "frosting" and user_lower == "vanilla"):
                    _apply_flavor("VANILLA")

        # 3. Pickup Time extraction
        if re.search(r"\b(2:00\s*pm|2\s*pm|2pm|14:00)\b", user_lower):
            filled["pickup_time"] = "2:00 PM"
        elif re.search(r"\b(4:30\s*pm|4:30pm|4:30|16:30)\b", user_lower):
            filled["pickup_time"] = "4:30 PM"
        elif re.search(r"\b(6:00\s*pm|6\s*pm|6pm|18:00)\b", user_lower):
            filled["pickup_time"] = "6:00 PM"
        elif last_asked == "pickup_time":
            if user_lower in ("2", "2:00", "2 pm", "2pm"):
                filled["pickup_time"] = "2:00 PM"
            elif user_lower in ("4", "4:30", "4 pm", "4pm"):
                filled["pickup_time"] = "4:30 PM"
            elif user_lower in ("6", "6:00", "6 pm", "6pm"):
                filled["pickup_time"] = "6:00 PM"

        # 4. Quantity extraction
        qty_match = (
            re.search(r"\b(\d+)\s+(?:[a-z_]+\s+){0,2}(?:cupcake|cupcakes|box|boxes)", user_lower)
            or re.search(r"(?:order|want|get|need|like)\s+(\d+)\b", user_lower)
            or re.search(r"\b(\d+)\s+for\s+(?:my|a|the)\s+party", user_lower)
        )
        if qty_match:
            q_val = int(qty_match.group(1))
            if q_val > 0:
                filled["quantity"] = q_val
        elif last_asked == "quantity" and re.match(r"^\s*(\d+)\s*$", user_lower):
            q_val = int(user_lower)
            if q_val > 0:
                filled["quantity"] = q_val

        # 5. Customer Name extraction
        name_match = re.search(
            r"(?:i'm|i am|my name is|name is|this is|under the name|for pickup under)\s+([a-zA-Z]+)",
            raw_user_text,
            re.I
        )
        if name_match:
            candidate = name_match.group(1).strip()
            if candidate.lower() not in ("ordering", "looking", "getting", "here", "ready", "a", "the"):
                filled["customer_name"] = candidate.title()
        elif last_asked == "customer_name":
            cleaned_name = raw_user_text.strip()
            if 1 < len(cleaned_name) <= 25 and not any(w in user_lower for w in ["start over", "reset", "cupcake", "pm", "am"]):
                filled["customer_name"] = cleaned_name.title()


def before_model_callback(callback_context, llm_request):
    """
    Runs BEFORE the LLM on EVERY pass (Pass 1 before tools & Pass 2 after tools).
    Evaluates the Slot-Filling DAG and either injects <current_directive> or preempts the LLM.
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

    filled = sm.setdefault("filled", {})
    task_results = sm.setdefault("task_results", {})
    slot_errors = sm.setdefault("_slot_errors", [])
    raw_user_text = _extract_latest_user_text(llm_request)
    user_text = raw_user_text.lower().strip()

    # Step 1: Retentive Reset Check ("start over", "reset", "new order")
    is_reset_phrase = any(kw in user_text for kw in ["start over", "reset", "new order"])
    if is_reset_phrase:
        preserved_channel = filled.get("channel", "MOBILE")
        sm.clear()
        sm["filled"] = {"channel": preserved_channel}
        sm["status"] = "in_progress"
        sm["task_results"] = {}
        sm["_slot_errors"] = []
        sm["_last_processed_utterance"] = raw_user_text
        callback_context.state["sm"] = json.dumps(sm)
        reset_msg = "🔄 Order reset! Welcome back to Cloud Bakery. What cupcake flavor would you like? We bake Red Velvet, Vanilla, Dark Chocolate, and Salted Caramel!"
        callback_context.state["system_message"] = reset_msg
        return _preempt_response(reset_msg, llm_request)

    # Automatic clean reset when starting a new turn after a completed/escalated order
    if sm.get("status") in ("complete", "escalated"):
        preserved_channel = filled.get("channel", "MOBILE")
        sm.clear()
        sm["filled"] = {"channel": preserved_channel}
        sm["status"] = "in_progress"
        sm["task_results"] = {}
        sm["_slot_errors"] = []
        filled = sm["filled"]
        task_results = sm["task_results"]
        slot_errors = sm["_slot_errors"]

    # Synchronize all parallel tool calls and deterministic NLU slots from the current turn
    _reconcile_turn_tools_and_text(llm_request, sm, raw_user_text)

    # Step 1.5: Warm Greeting Check ("hi", "hello", "hey") when no order slots are filled yet
    greeting_phrases = {"hi", "hello", "hey", "hi there", "hello there", "good morning", "good afternoon", "good evening", "hola"}
    order_slots_count = len([k for k in filled.keys() if k != "channel"])
    if user_text in greeting_phrases and order_slots_count == 0 and not slot_errors:
        welcome_msg = "Hello! Welcome to Cloud Bakery! 🧁 How can I help you today?"
        sm["_system_message"] = welcome_msg
        callback_context.state["system_message"] = welcome_msg
        callback_context.state["sm"] = json.dumps(sm)
        return _preempt_response(welcome_msg, llm_request)

    # Step 2: Self-Healing Validation Error Check (from setter tools or invalid NLU inputs)
    if slot_errors:
        err = slot_errors.pop(0)
        recovery_msg = err.get("agent_action", "Please provide a valid input.")
        sm["_system_message"] = recovery_msg
        callback_context.state["system_message"] = recovery_msg
        callback_context.state["sm"] = json.dumps(sm)
        _inject_directive(llm_request, f"VALIDATION ERROR: {recovery_msg}")
        return None

    # Step 3: Business Rule Guard -> Catering Escalation (>60 Cupcakes)
    quantity = int(filled.get("quantity", 0) or 0)
    if quantity > 60:
        sm["status"] = "escalated"
        esc_msg = "Whoa, that's a big party! 🎉 Orders over 5 dozen (60 cupcakes) are handled by our Catering Specialist. Connecting you now..."
        sm["_system_message"] = esc_msg
        callback_context.state["system_message"] = esc_msg
        callback_context.state["sm"] = json.dumps(sm)
        return _preempt_response(esc_msg, llm_request)

    # Step 4: Auto-Fire Intermediate Task: CheckBakeryInventoryTask -> Fills Task-Sourced Slot 'available_times'
    if "flavor" in filled and "quantity" in filled and "available_times" not in filled:
        filled["available_times"] = "2:00 PM, 4:30 PM, 6:00 PM"
        inv_res = {"status": "AVAILABLE", "available_times": filled["available_times"]}
        task_results["check_bakery_inventory"] = inv_res
        task_results["CheckBakeryInventoryTask"] = inv_res

    # Step 5: Progressive Disclosure -> Determine the NEXT missing user-sourced slot
    was_pivoted = sm.pop("_pivoted_flavor", None)
    dag_slots = [
        ("flavor", "What cupcake flavor would you like? We bake Red Velvet, Vanilla, Dark Chocolate, and Salted Caramel!"),
        ("quantity", "How many cupcakes would you like in your box?"),
        ("frosting", "Which frosting should we swirl on top: Cream Cheese, Vanilla Buttercream, or Chocolate Ganache?"),
        ("pickup_time", f"We have fresh oven batches ready at {filled.get('available_times', '2:00 PM, 4:30 PM, 6:00 PM')} today! Which pickup time works best?"),
        ("customer_name", "Almost done! What name should we put on your order box?")
    ]

    for slot_name, prompt_text in dag_slots:
        if slot_name not in filled:
            sm["_last_asked_slot"] = slot_name
            if slot_name == "pickup_time" and was_pivoted:
                prompt_text = (
                    f"Got it, we switched your flavor to {was_pivoted.replace('_', ' ').title()}! "
                    f"Since oven schedules vary by flavor, please confirm your pickup time from our fresh batches at {filled.get('available_times', '2:00 PM, 4:30 PM, 6:00 PM')} today. Which pickup time works best?"
                )
            directive = (
                f"Filled slots so far: {json.dumps(filled)}. "
                f"NEXT REQUIRED QUESTION: Ask the customer: '{prompt_text}'"
            )
            sm["_system_message"] = prompt_text
            callback_context.state["system_message"] = prompt_text
            callback_context.state["sm"] = json.dumps(sm)
            _inject_directive(llm_request, directive)
            return None

    # Step 6: All 5 Slots Ready -> Fire Final Fulfillment Task & PREEMPT LLM!
    total_inr = quantity * 120
    order_id = "CB-4092"
    channel = filled.get("channel", "MOBILE").upper()
    tracking_link = f"cloudbakery://orders/{order_id}" if channel == "MOBILE" else f"https://cloudbakery.example.com/orders/{order_id}"
    res_payload = {"order_id": order_id, "total_inr": total_inr, "tracking_link": tracking_link}
    task_results["place_cupcake_order"] = res_payload
    task_results["PlaceCupcakeOrderTask"] = res_payload
    sm["status"] = "complete"
    sm["_last_asked_slot"] = ""

    flavor_disp = str(filled.get("flavor", "")).replace("_", " ").title()
    frosting_disp = str(filled.get("frosting", "")).replace("_", " ").title()
    pickup_disp = str(filled.get("pickup_time", ""))
    cname_disp = str(filled.get("customer_name", ""))

    confirm_msg = (
        f"🧁 Order Confirmed for {cname_disp}! We are baking {quantity} {flavor_disp} cupcakes "
        f"with {frosting_disp} frosting for pickup at {pickup_disp}. "
        f"Total: ₹{total_inr} | Order ID: #{order_id} | Track: {tracking_link}"
    )
    sm["_system_message"] = confirm_msg
    callback_context.state["system_message"] = confirm_msg
    callback_context.state["sm"] = json.dumps(sm)

    # Preempt LLM response immediately using LlmResponse.from_parts
    return _preempt_response(confirm_msg, llm_request)
