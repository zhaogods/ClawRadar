# Publishers

This directory hosts channel-specific publishing adapters.

Scope:
- `delivery.py` keeps payload validation, archival, and receipt aggregation.
- `publishers/*` keeps auth, content conversion, remote API calls, and channel receipts.

Suggested subpackages:
- `wechat/`
- `feishu/`
- `webhook/`
