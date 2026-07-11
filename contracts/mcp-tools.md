# MCP tool contract

```text
search_products({query, category?, max_price?})
draft_intent({description})
request_purchase({intent_id, sku, qty})
get_purchase_status({purchase_id})
initiate_return({purchase_id, reason})
list_purchases({})
get_evidence_bundle({purchase_id})
```

`request_purchase` and `initiate_return` can only return a proposal or
`awaiting_human_authorization`. There is deliberately no authorization,
approval, signature, confirmation, or payment MCP tool.
