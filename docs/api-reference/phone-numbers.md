---
title: Phone numbers
description: Organisation number inventory, and attaching numbers to agents.
---

`apps/api/app/routers/phone_numbers.py`, prefix `/api/v1/phone-numbers`. The organisation's DID inventory, plus attach and detach against telephony agents.

## `GET /phone-numbers`

Bearer. Array of `PhoneNumberResponse` for the active organisation: `phone_number`, `provider`, `org_id`, `agent_id`, timestamps, and the four `last_link_*` audit fields.

## `GET /phone-numbers/activity`

Bearer. Paginated append-only activity log for the active organisation (`?limit=&offset=`). Returns `PhoneNumberActivityResponse`: `{events, total, limit, offset}`. Each event has `phone_number`, `provider`, `action` (`imported` / `attached` / `detached` / `removed`), optional `agent_id` / `agent_name`, `by_email`, and `at`. Newest first. On first list for an org with no events, seeds one event per inventory row from existing `last_link_*` fields when present.

## `GET /phone-numbers/agent/{agent_id}`

Bearer. The single `PhoneNumberResponse` bound to that agent.

## `POST /phone-numbers/attach`

Bearer. `201`.

```json
{
  "phone_number": "+15551234567",
  "provider": "vobiz",
  "agent_id": "optional-agent-uuid"
}
```

With `agent_id` the number is added to the inventory, linked at the provider, and written to `Agents.linked_phone_number`. Omit `agent_id` to import into inventory only, with no provider link. Returns `SuccessResponse`.

<Note>
The uniqueness index on `phone_number` has no `org_id` component, so a number already held by another organisation fails on a duplicate key rather than with a clear conflict message. See [Data model](../developer/reference/data-model).
</Note>

## `DELETE /phone-numbers/detach`

Bearer. Body `{ "phone_number": "+15551234567" }`. Unlinks at the provider and clears the agent association. The inventory row survives. Returns `SuccessResponse`.

## `DELETE /phone-numbers/remove`

Bearer. Body `{ "phone_number": "+15551234567" }`. Detaches first if the number is attached to an agent, then deletes the inventory row. Does not release the number at the telephony provider — you can import it again later. Returns `SuccessResponse`.

## `GET /phone-numbers/providers/{provider}/inventory`

Bearer. Numbers held in the organisation's account **at the provider**, which is not the same set as your VoicEra inventory. Returns `PhoneNumberInventoryResponse`: `{status, numbers: []}`. An unregistered provider returns `422`.

## Related

* [Endpoints cheatsheet](endpoints-cheatsheet) — every route on one page
* [Authentication](authentication) — tokens, headers, and roles
* [Errors](errors) — status codes and error shapes
