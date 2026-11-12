---
title: Phone numbers
description: Organisation number inventory, and attaching numbers to agents.
---

`apps/api/app/routers/phone_numbers.py`, prefix `/api/v1/phone-numbers`. The organisation's DID inventory, plus attach and detach against telephony agents.

## `GET /phone-numbers`

Bearer. Array of `PhoneNumberResponse` for the active organisation: `phone_number`, `provider`, `org_id`, `agent_id`, timestamps, and the four `last_link_*` audit fields.

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

Bearer. Body `{ "phone_number": "+15551234567" }`. Unlinks at the provider and clears the agent association. The inventory row survives — remove it with [`DELETE /phone-numbers/delete`](#delete-phone-numbersdelete). Returns `SuccessResponse`.

## `DELETE /phone-numbers/delete`

Bearer. Body `{ "phone_number": "+15551234567" }`. Permanently removes the number from the organisation's inventory. Returns `SuccessResponse`.

The number must be detached first: a number still attached to an agent returns `409`. `404` when the number is not in any inventory, `403` when it belongs to another organisation.

<Note>
Delete does **not** release the number at the telephony provider. It stays in your provider account — and still shows in `GET /phone-numbers/providers/{provider}/inventory` — so you can import it again with `POST /phone-numbers/attach`.
</Note>

## `GET /phone-numbers/providers/{provider}/inventory`

Bearer. Numbers held in the organisation's account **at the provider**, which is not the same set as your VoicEra inventory. Returns `PhoneNumberInventoryResponse`: `{status, numbers: []}`. An unregistered provider returns `422`.

## Related

* [Endpoints cheatsheet](endpoints-cheatsheet) — every route on one page
* [Authentication](authentication) — tokens, headers, and roles
* [Errors](errors) — status codes and error shapes
