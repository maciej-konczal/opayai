# Unified OPayAI MCP tool contract

```text
draft_intent({description})
search_offers({query?, category?, max_price?, intent_id?})
suggest_offers({intent_id, limit?})
propose_cart({intent_id, offer_id, qty?})
evaluate_policy({purchase_id})
get_order({purchase_id, since?})
create_return({purchase_id, reason})
list_purchases({})
get_audit_trail({purchase_id})
get_notifications({purchase_id?, since?})
get_evidence_bundle({purchase_id})
```

This is the only MCP surface in the repository. It retains the teammate
prototype's discover → suggest → propose → evaluate → track → resolve language,
while using the OPayAI PLN/BLIK lifecycle and evidence model.

`draft_intent`, `propose_cart`, and `create_return` can only create drafts or
return `awaiting_human_authorization`. `evaluate_policy` is read-only: policy is
executed deterministically inside the service before merchant actions.

There is deliberately no MCP tool for authorization, approval, signing,
passkeys, payment confirmation, order advancement, or resolution approval.
Those actions belong to the human UI or internal merchant/demo surfaces.
