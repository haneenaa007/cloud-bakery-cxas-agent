# Migration Skills: Dialogflow CX/CXAS Non-Deterministic to Deterministic Slot-Filling Agent

This guide outlines the architectural design, migration patterns, and real-world lessons for migrating conversational slot-filling flows from Dialogflow CX (DFCX) or CXAS Non-Deterministic Agent to a deterministic Python-based CXAS agent.

---

## 1. Architectural Overview

The Slot-Filling Framework executes multi-step form collection using a deterministic State Machine (SM) driven by a compilation of rules and dependencies. Instead of relying on non-deterministic LLMs or Cloud NLU engines to parse state transitions, it executes sequential rules to collect parameters, trigger validators, invoke business services, and output structured link templates.

---

## 2. Dynamic Slot-Filling Lifecycle

A single conversational turn for a slot-filling agent involves a multi-pass execution loop to simulate state resolution, slot collection, validation, and fulfillment.

### Phase 1: Reset Check and Context Evaluation
Before any turn-specific processing starts, evaluate if the previous flow was completed or if a clean session is starting.
* **Context Recovery:** If the session status is `"complete"` or `"escalated"`, verify if user text contains intent keys to start a new transaction. If so, perform a retentive reset (`reset_with_context`), preserving relevant background user variables (`channel`) while clearing transactional slots.

### Phase 2: Mapping DFCX Pages & Form Parameters to Declarative DAG Schemas
Instead of relying on DFCX page state transitions, migrate form parameters into a declarative DAG configuration (`tools/dag_config.py`):
1. **Form Parameters -> `slots` Array:** Convert each DFCX page parameter into a slot definition specifying `name`, `allowed_values` (if categorical), `requires` (prerequisite slots that gate this parameter), `setter` (the thin validation tool name), and `prompt`.
2. **Transition Routes -> `requires` Dependencies:** Convert DFCX condition routes (e.g. `$page.params.service_category = "CATEGORY_A"`) into explicit slot prerequisites so downstream slots are only evaluated when parent conditions are satisfied.
3. **Webhooks -> `tasks` Array:** Map DFCX webhook fulfillments into DAG task definitions specifying `name`, `requires` (input slots needed before firing), and `action` (the fulfillment tool function).

```python
DAG_CONFIG = {
    "slots": [
        {
            "name": "service_category",
            "allowed_values": ["CATEGORY_A", "CATEGORY_B"],
            "requires": [],
            "setter": "set_service_category",
            "prompt": "Which service category would you like to select: Category A or Category B?"
        },
        {
            "name": "sub_option",
            "allowed_values": ["OPTION_1", "OPTION_2"],
            "requires": ["service_category"],
            "setter": "set_sub_option",
            "prompt": "Would you prefer Option 1 or Option 2?"
        }
    ],
    "tasks": [
        {
            "name": "DeliverFulfillment",
            "requires": ["service_category", "sub_option"],
            "action": "execute_fulfillment_tool"
        }
    ]
}
```

### Phase 3: Deterministic Evaluation & Preemption in `before_model_callback`
* **DAG Traversal:** On every turn, `before_model_callback` inspects `sm["filled"]` against the declarative DAG schema.
* **Task Firing & Preemption:** When all `requires` slots for a task are present in `sm["filled"]`, Python executes the fulfillment task, stores the output in `sm["task_results"]`, marks `sm["status"] = "complete"`, and immediately preempts LLM generation using `LlmResponse.from_parts()`.
* **Progressive Disclosure (`_next_question`):** If required slots are still missing, Python identifies the first unfilled slot whose prerequisites are met and writes its prompt to `sm["_system_message"]` for the LLM to relay naturally.

---

## 3. Thin Setter Tools Specification

Each user-collected slot is mapped to a thin Python setter tool. Setter tools validate inputs and return structured dict results (`{"stored": True, "value": ...}` or `{"error": True, "error_code": "..."}`).

> [!WARNING]
> **Keep docstrings short (1-2 sentences: format + trigger phrase only).** Verbose docstrings with business logic confuse the LLM and break multi-slot batching behavior!

```python
def set_service_category(service_category: str) -> dict:
    """Record service category (CATEGORY_A, CATEGORY_B).
    
    Call immediately when user mentions service category.
    """
    valid_types = ["CATEGORY_A", "CATEGORY_B"]
    val = service_category.upper().strip()
    if val not in valid_types:
        return {"error": True, "error_code": "invalid_type"}
    return {"stored": True, "value": val}
```

---

## 4. The 4 Control Surfaces in CXAS

### Surface 1: System Instruction (`<slot_filling_protocol>`)
Migrate legacy DFCX system prompts to the standardized CXAS slot-filling protocol. Always include a concrete multi-slot batching example:

```xml
<slot_filling_protocol>
You are operating in SLOT FILLING mode:

1. TOOL-DRIVEN CONVERSATION: Identify EVERY piece of information provided 
   and call ALL corresponding setter tools in the SAME turn.
2. PROGRESSIVE DISCLOSURE: Ask only ONE question at a time. Never preview 
   future steps.
3. RELAY SYSTEM MESSAGES: When _system_message is set in the directive, 
   incorporate it naturally.
</slot_filling_protocol>

<system_directive>
{{system_message}}
</system_directive>
```

### Surface 2: Docstrings (Format + Trigger Phrase Only)
Do not duplicate business logic or validation rules inside docstrings.

### Surface 3: `before_model_callback` (DAG Engine & Preemption)
Evaluates DAG state, determines `_next_question(sm)` -> `sm['_system_message']`, and preempts LLM generation (`LlmResponse.from_parts()`) when tasks fire.

### Surface 4: `after_model_callback` (Payload Stashing)
Stashes UI payloads in `sm['_pending_payloads']` and appends them to LLM responses on non-preempted turns.

---

## 5. Real-World Migration Challenges & Best Practices

When migrating legacy DFCX static payloads and non-deterministic flows into a deterministic CXAS agent, enforce the following real-world patterns to prevent common failure modes:

### 5.1. Mid-Flow Branch Pivot & Child-Slot Purging
Users frequently change their mind mid-conversation (e.g., selecting `Category A` -> `Option 1`, and when prompted for the next field, saying *"Actually, switch to Category B"*).
* **Challenge:** If setter tools only overwrite `service_category="CATEGORY_B"` without clearing downstream child slots, stale values (`sub_option`, `action_type`) remain in `sm['filled']` and corrupt the new branch.
* **Best Practice:** Whenever a root/gate branch slot changes value, explicitly purge all dependent downstream child slots from `sm['filled']` and `sm['pending']` so the DAG re-evaluates the new branch cleanly from the pivot point.

### 5.2. Single-Turn Multi-Slot Extraction & Immediate Terminal Fulfillment
When a user provides multiple slots in a single utterance (e.g., *"Schedule Category A with Option 1 for tomorrow"* -> extracts all required slots in Turn 1), all prerequisites for terminal fulfillment are satisfied immediately.
* **Challenge:** Waiting for a subsequent turn to evaluate terminal task readiness leaves the user with a generic fallback prompt (*"How can I assist you?"*).
* **Best Practice:** Always evaluate terminal branch readiness (`is_branch_ready_for_fulfillment(filled)`) immediately after slot extraction in the same turn, execute the terminal fulfillment tool, populate `sm['task_results']['DeliverFulfillment']`, and preempt LLM generation.

### 5.3. Conversational Verb Collision & Keyword Contamination
Common conversational verbs or phrasing in user questions often collide with domain slot values or category names, causing false-positive slot extraction.
* **Best Practice:** Pre-normalize ambiguous conversational phrases before running slot extraction and enforce strict word-boundary matching in setter extractors.

### 5.4. Primary Scenario Slicing (`scenarios[:1]`)
Migrated DFCX static payloads (`custom_payload["scenarios"]`) often contain multiple fallback scenarios in a single list (e.g. `status_open`, `status_closed`, `technical_error`).
* **Challenge:** Iterating over all items in `cp.get("scenarios", [])` concatenates primary, alternate, and error messages into one giant, confusing bot response.
* **Best Practice:** Always slice `cp.get("scenarios", [])[:1]` to evaluate and output only the active primary scenario.

### 5.5. Custom App Deep Link Normalization (`customapp://`)
Legacy DFCX fulfillment payloads frequently return custom mobile deep links (`customapp://action_a`, `customapp://action_b`) alongside standard web URLs depending on the `channel` parameter.
* **Best Practice:** Ensure channel-aware link resolution inspects `sm["filled"].get("channel")` so mobile channels receive native deep links while web channels receive standard HTTPS links.

### 5.6. Dual Task-Results Keys (`DeliverFulfillment`)
Migrated DFCX condition builders often check logical task completion names (`DeliverFulfillment`) rather than raw Python tool function names.
* **Best Practice:** Always write tool outputs to both keys in `sm['task_results']` (e.g., `sm['task_results'][tool_name] = result` and `sm['task_results']['DeliverFulfillment'] = result`) so downstream condition builders resolve seamlessly.

### 5.7. Retentive Reset Pattern (`reset_with_context`)
When a user requests a reset (*"start over"*, *"reset"*), wiping the entire `sm` dictionary loses critical session context (`channel`, `auth_token`).
* **Best Practice:** Clear transactional slots in `sm['filled']` while preserving session-scoped metadata (`channel`).

---

## 6. Key Takeaways Checklist for Developers

* ✅ **Declarative DAG Mapping:** Map DFCX form parameters to `slots`, condition routes to `requires` dependencies, and webhook calls to `tasks`.
* ✅ **Short Setter Docstrings:** Keep tool docstrings to 1–2 sentences (format + trigger phrase) to preserve multi-slot batching behavior.
* ✅ **Mid-Flow Branch Pivot Purging:** Purge downstream child slots whenever a parent/root branch slot changes value.
* ✅ **Immediate Terminal Fulfillment:** Evaluate terminal task readiness on the same turn immediately after multi-slot extraction.
* ✅ **Primary Scenario Slicing:** Render `scenarios[:1]` from DFCX custom payloads to avoid concatenated fallback messages.
* ✅ **Dual Task-Results Keys:** Store tool results under both the raw tool name and logical task config name (`DeliverFulfillment`).
