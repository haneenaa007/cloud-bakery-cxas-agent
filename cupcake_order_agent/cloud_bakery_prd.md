# Product Requirements Document (PRD): Cloud Bakery Order Agent

**Project Name:** Cloud Bakery Conversational Ordering Assistant  
**Target Platform:** Google Cloud CX Agent Studio (CXAS) + `cxas-scrapi` SDK  
**Architecture Pattern:** Deterministic Slot-Filling DAG Framework (`slot-filling-implementation-skills.md`)  
**Version:** 1.0 (Technical Specification)

---

## 1. Executive Summary & Objective
**Cloud Bakery** requires a low-latency, zero-hallucination conversational AI agent to handle custom cupcake box orders across Mobile (`MOBILE`) and Web (`WEB`) channels. 

To eliminate common LLM failure modes—such as premature order placement, hallucinated oven pickup times, acceptance of unsupported flavors, or context amnesia during multi-turn conversations—this agent must be implemented using the **CXAS Deterministic Slot-Filling DAG Architecture**. All control flow, validation rules, task orchestration, and state transitions are governed deterministically in Python (`before_model_callback` and `after_tool_callback`), while the LLM is strictly scoped to natural language slot extraction and warm conversational phrasing.

---

## 2. Declarative Slot & DAG Specification

The agent collects **5 User-Sourced Slots** and derives **1 Task-Sourced Slot** (`available_times`) via an intermediate inventory check before executing terminal order fulfillment.

### 2.1. Slot Inventory & Dependencies (`DAG_CONFIG['slots']`)

| Slot Name | Source | Data Type / Enum | `requires` (Prerequisites) | Validation & Business Rules | Prompt / Progressive Disclosure |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **`flavor`** | `user` | Enum: `RED_VELVET`, `VANILLA`, `DARK_CHOCOLATE`, `SALTED_CARAMEL` | `[]` (Root Slot) | Must match supported bakery flavors. Rejects unsupported flavors (e.g. "Broccoli") with self-healing `agent_action`. **Pivot Rule:** Changing `flavor` purges `available_times` and `pickup_time`. | *"What cupcake flavor would you like? We bake Red Velvet, Vanilla, Dark Chocolate, and Salted Caramel!"* |
| **`quantity`** | `user` | Integer (`1` – `60`) | `["flavor"]` | Must be `>= 1`. If `quantity > 60` (over 5 dozen), immediately **preempt and escalate** to `Catering_Events_Specialist`. **Pivot Rule:** Changing `quantity` purges `available_times` and `pickup_time`. | *"How many cupcakes would you like in your box?"* |
| **`frosting`** | `user` | Enum: `CREAM_CHEESE`, `BUTTERCREAM`, `CHOCOLATE_GANACHE` | `["flavor", "quantity"]` | Must match supported frostings. Normalizes variations (e.g., "Chocolate" ➔ `CHOCOLATE_GANACHE`). | *"Which frosting should we swirl on top: Cream Cheese, Vanilla Buttercream, or Chocolate Ganache?"* |
| **`available_times`** | **`task`** | List of Strings | `["flavor", "quantity"]` | **Task-Sourced Slot:** Populated automatically by `CheckBakeryInventoryTask`. Never asked of the user. | `None` (Auto-derived by backend task) |
| **`pickup_time`** | `user` | String (e.g., `2:00 PM`, `4:30 PM`, `6:00 PM`) | `["flavor", "quantity", "frosting", "available_times"]` | Must be a valid time string containing `AM`/`PM` or `:`. Prompt dynamically injects `available_times`. | *"We have fresh oven batches ready at {available_times} today! Which pickup time works best?"* |
| **`customer_name`** | `user` | String (Min 2 chars) | `["flavor", "quantity", "frosting", "pickup_time"]` | Non-empty string (`len >= 2`). | *"Almost done! What name should we put on your order box?"* |

---

## 3. Backend Tasks & Fulfillment Specification (`DAG_CONFIG['tasks']`)

| Task Name | Raw Tool Function | Trigger Condition (`requires`) | Behavior & Output |
| :--- | :--- | :--- | :--- |
| **`CheckBakeryInventoryTask`** | `check_bakery_inventory` | `["flavor", "quantity"]` satisfied AND `available_times` not in `sm["filled"]` | Queries kitchen oven schedule for the requested flavor/quantity and writes `["2:00 PM", "4:30 PM", "6:00 PM"]` into `sm["filled"]["available_times"]`. |
| **`PlaceCupcakeOrderTask`** | `place_cupcake_order` | All 5 user slots (`flavor`, `quantity`, `frosting`, `pickup_time`, `customer_name`) satisfied | Calculates total price (`quantity * ₹120`), generates Order ID (`#CB-4092`), resolves channel-aware tracking link, marks `sm["status"] = "complete"`, and **preempts LLM generation** (`<200ms`). |

---

## 4. Mandatory Engineering Best Practices (Skills Alignment)

To ensure deterministic reliability, the implementation MUST adhere to the following 7 architectural rules from `slot-filling-implementation-skills.md`:

### 4.1. Two-Sentence Setter Docstring Rule (Surface 1)
- All setter tools (`set_flavor`, `set_quantity`, `set_frosting`, `set_pickup_time`, `set_customer_name`) must have docstrings strictly limited to **1–2 sentences** (Format specification + Trigger condition).
- **Rationale:** Verbose tool descriptions cause Gemini to hesitate when invoking multiple tools simultaneously (e.g., when a user provides flavor, quantity, and frosting in a single utterance).

### 4.2. Self-Healing Error Recovery (`agent_action`)
- When a user provides invalid input (e.g., *"I want 6 Broccoli cupcakes"* or *"0 cupcakes"*), the setter tool must return `{"error": True, "error_code": "...", "agent_action": "..."}`.
- `before_model_callback` intercepts `_slot_errors`, pops the recovery instruction, and injects it into `callback_context.state["system_message"]` so the LLM politely guides the user back on track without hallucinating menu items.

### 4.3. Mid-Flow Branch Pivot & Child-Slot Purging Rule
- Customers frequently change their mind mid-order (e.g., after selecting `flavor="VANILLA"`, `quantity=12`, and `pickup_time="2:00 PM"`, the user says *"Actually, change the flavor to Red Velvet"* or *"Make it 24 cupcakes"*).
- Because oven batch availability (`available_times`) depends on `flavor` and `quantity`, `after_tool_callback` must detect whenever `flavor` or `quantity` changes value and **explicitly purge downstream child slots** (`available_times`, `pickup_time`, and `CheckBakeryInventoryTask` in `task_results`) so the DAG cleanly re-evaluates oven inventory for the updated order.

### 4.4. Single-Turn Multi-Slot Extraction & Immediate Terminal Fulfillment
- If a user provides all required slots in Turn 1 (*"Hi, I'm Haneena, please book 12 Red Velvet cupcakes with Cream Cheese frosting for 4:30 PM"*), the engine must immediately run `CheckBakeryInventoryTask`, validate `pickup_time`, execute `PlaceCupcakeOrderTask`, and preempt the LLM with the final order confirmation in the same turn.

### 4.5. Callback Preemption (`LlmResponse.from_parts`)
- On **normal collection turns**, `before_model_callback` updates `callback_context.state["system_message"]` and returns `None` so the LLM speaks the question naturally.
- On **terminal fulfillment** (`PlaceCupcakeOrderTask`) or **business escalation** (`quantity > 60`), `before_model_callback` returns `LlmResponse.from_parts([Part.from_text(...)])` directly, bypassing the second LLM round-trip and delivering sub-200ms confirmation latency.

### 4.6. Dual Task-Results Keys Rule
- Every executed task output must be saved in `sm["task_results"]` under **both** the raw tool function name (`check_bakery_inventory`, `place_cupcake_order`) and the logical task configuration name (`CheckBakeryInventoryTask`, `PlaceCupcakeOrderTask`).

### 4.7. Channel-Aware Link Normalization (`customapp://` vs. HTTPS) & Retentive Reset
- **Channel-Aware Links:** Order confirmation messages must inspect `sm["filled"].get("channel")`:
  - If `channel == "MOBILE"`, output native deep link: `cloudbakery://orders/CB-4092`
  - If `channel == "WEB"`, output standard web URL: `https://cloudbakery.example.com/orders/CB-4092`
- **Retentive Reset (`reset_with_context`):** When a user says *"start over"*, *"reset"*, or *"new order"*, `before_model_callback` clears transactional slots in `sm["filled"]` while preserving session-level metadata (`channel`).

---

## 5. Acceptance Criteria & Automated Verification Suite

The implementation is verified against an automated unit test suite (`test_cupcake_agent.py`) covering **5 mandatory scenarios**:
1. **Scenario 1 (Multi-Turn Happy Path & Task-Sourced Slot Derivation):** Verifies progressive disclosure, automatic derivation of `available_times`, dual-key task results, channel-aware mobile deep link (`cloudbakery://orders/CB-4092`), and callback preemption on Turn 6.
2. **Scenario 2 (Self-Healing Validation Error):** Verifies `"Broccoli cupcakes"` triggers `agent_action` recovery in `system_message`.
3. **Scenario 3 (Catering Escalation Rule):** Verifies `quantity = 100` (`>60`) preempts the LLM and triggers `Part.from_agent_transfer(agent="Catering_Events_Specialist")`.
4. **Scenario 4 (Mid-Flow Branch Pivot Purging):** Verifies that changing `flavor` from `VANILLA` to `RED_VELVET` after `pickup_time` was already selected automatically purges stale `available_times` and `pickup_time` and re-runs inventory check.
5. **Scenario 5 (Retentive Reset):** Verifies `"start over"` clears order slots while preserving `channel = "MOBILE"`.
