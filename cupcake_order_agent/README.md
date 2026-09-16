# 🧁 Cloud Bakery: Deterministic Slot-Filling Agent on Google Cloud CXAS

Welcome to the **Cloud Bakery** example agent for the Medium article:  
**"Slot-Filling Framework: Guide to Building Deterministic Agents on Google Cloud CXAS"**

This package contains the complete **Cloud Bakery** agent in the exact **CX Agent Studio (CXAS)** export format (`app.json`, `agents/`, `tools/`, `pythonEnvFiles/`), ready to import directly into Google Cloud CX Agent Studio.

---

## 📂 Package Structure

```text
├── cupcake_order_agent/                       # 🧁 Cloud Bakery CXAS Agent Package
│   ├── README.md                              # Architecture guide, import steps & interactive test cases
│   ├── cloud_bakery_prd.md                    # Product Requirements Document (PRD)
│   ├── app.json                               # CXAS Application configuration
│   ├── pythonEnvFiles/
│   │   └── pythonEnvFiles.json                # Python environment dependencies
│   ├── agents/
│   │   └── CupcakeOrderAgent/                 # Root Agent (Instruction + Deterministic Callbacks)
│   │       ├── CupcakeOrderAgent.json
│   │       ├── instruction.txt
│   │       ├── before_model_callbacks/
│   │       │   └── before_model_callbacks_01/python_code.py
│   │       └── after_tool_callbacks/
│   │           └── after_tool_callbacks_01/python_code.py
│   └── tools/                                 # Thin Setter & Execution Tools
│       ├── set_flavor/
│       ├── set_quantity/
│       ├── set_frosting/
│       ├── set_pickup_time/
│       ├── set_customer_name/
│       ├── check_bakery_inventory/
│       └── place_cupcake_order/
│
└── slot_filling_resources/                    # 📚 Slot-Filling Skills
    ├── slot-filling-implementation-skills.md  # Implementation Best Practices & Developer Guide
    └── slot-filling-migration-skills.md       # Legacy-to-CXAS Migration Playbook
```

---

## 🚀 Quick Start

1. **Import into Google Cloud CX Agent Studio (CXAS):**
   - Compress the contents of this folder (`app.json`, `agents/`, `tools/`, `pythonEnvFiles/`) into a `.zip` archive.
   - Open the **[Google Cloud CX Agent Studio Console](https://ces.cloud.google.com/)**, click **Import App**, upload the `.zip` file, and launch the **Preview Agent** simulator.

2. **Read the Implementation & Migration Skill Documents:**
   These skill documents guide you through implementing and migrating slot-filling agents from CXAS generative agents or Dialogflow CX (DFCX) agents to deterministic agents. You can use them alongside AI pair-programming tools like Antigravity or GitHub Copilot to build your own deterministic slot-filling agents:
   - **[`slot-filling-implementation-skills.md`](../slot_filling_resources/slot-filling-implementation-skills.md)** — Complete implementation patterns, callback architecture (`before_model_callback` & `after_tool_callback`), thin setter docstrings, and state machine best practices.
   - **[`slot-filling-migration-skills.md`](../slot_filling_resources/slot-filling-migration-skills.md)** — Step-by-step migration guide for converting legacy conversational flows into deterministic CXAS slot-filling DAGs.

3. **Try the Custom Slot-Filling UI Visualizer:**
   Want to visualize live slot extraction, DAG state transitions, and callback execution in real time? Explore the companion **[CXAS Slot-Filling UI (`cxas-slot-filling-ui`)](https://github.com/haneenaa007/cxas-slot-filling-ui)**.

---

## 🧪 3 Simple Test Cases to Try in CXAS Simulator

Once imported into Google Cloud CX Agent Studio, open **Preview Agent** and copy-paste these 3 test cases:

### Test Case 1: Step-by-Step Conversational Order
Tests natural multi-turn slot collection (`1` question at a time) and automatic backend batch lookup (`available_times`).
- **You:** `hi`
  - **Agent (`<100ms` Preempted):** `Hello! Welcome to Cloud Bakery! 🧁 How can I help you today?`
- **You:** `i want to order cupcakes`
  - **Agent:** `What cupcake flavor would you like? We bake Red Velvet, Vanilla, Dark Chocolate, and Salted Caramel!`
- **You:** `vanilla`
  - **Agent:** `How many cupcakes would you like in your box?`
- **You:** `24`
  - **Agent:** `Which frosting should we swirl on top: Cream Cheese, Vanilla Buttercream, or Chocolate Ganache?`
- **You:** `buttercream`
  - **Agent:** `We have fresh oven batches ready at 2:00 PM, 4:30 PM, 6:00 PM today! Which pickup time works best?`
- **You:** `4:30 pm`
  - **Agent:** `Almost done! What name should we put on your order box?`
- **You:** `Haneena`
  - **Agent (`<200ms` Preempted):** `🧁 Order Confirmed for Haneena! We are baking 24 Vanilla cupcakes with Buttercream frosting for pickup at 4:30 PM. Total: ₹2880 | Order ID: #CB-4092`

---

### Test Case 2: One-Shot Order (All 5 Slots in 1 Sentence!)
Tests single-turn extraction of all 5 slots and immediate `<200ms` callback confirmation without redundant follow-up questions.
- **You:** `Hi! I'm Haneena, I want 12 Red Velvet cupcakes with Cream Cheese frosting for pickup at 4:30 PM`
- **Agent (Immediate Turn 1 Confirmation):**
  > `🧁 Order Confirmed for Haneena! We are baking 12 Red Velvet cupcakes with Cream Cheese frosting for pickup at 4:30 PM. Total: ₹1440 | Order ID: #CB-4092`

---

### Test Case 3: Self-Healing Validation & Catering Guardrail
Tests rejecting an invalid menu item (`Broccoli`) while retaining valid slots (`quantity=6`), as well as enforcing deterministic business rules (`>60` cupcakes -> Catering Specialist escalation).
- **You:** `I want 6 Broccoli cupcakes please`
  - **Agent (Self-Healing Menu Check):** `I am so sorry, but we don't bake Broccoli cupcakes. We offer Red Velvet, Vanilla, Dark Chocolate, or Salted Caramel. Which of these would you prefer?`
- **You:** `I need 100 Vanilla cupcakes for a corporate event`
  - **Agent (`<200ms` Preempted Catering Escalation):** `Whoa, that's a big party! 🎉 Orders over 5 dozen (60 cupcakes) are handled by our Catering Specialist. Connecting you now...`
