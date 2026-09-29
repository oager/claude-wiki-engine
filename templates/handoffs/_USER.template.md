---
key: _user
type: user
updated: <YYYY-MM-DDTHH:MMZ>
updated_by: <hostname>
---
# User handoff

_Read by /preflight at the start of every session, in every project. /sync proposes changes; nothing is written
without your yes. Keep it small (max_kb, default 8): one line per Convention, detail in a linked page._

## Conventions
_One line each; applied silently by /preflight and /sync._

## Profile
```json
{
  "identity": {"names": [], "emails": [], "hosts": {}},
  "checks": [],
  "publish_deny": [],
  "publish_allow": [],
  "max_kb": 8
}
```

## Standing notes

## Declined
_Proposals you said no to; /sync does not propose them again._
