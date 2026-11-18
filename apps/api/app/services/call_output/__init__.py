"""Post-call ``call_output``: fields worked out after a call ends.

The core here is provider-neutral (scheduling, retries, storage, the webhook
hand-off). What the fields are and where they come from is a provider's job;
an agent opts in with ``config.call_output = {"enabled": true, "provider": …}``.
"""
