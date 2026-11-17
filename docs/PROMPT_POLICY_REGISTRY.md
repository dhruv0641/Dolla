# Prompt and policy registry

`config/prompt_registry.json` is the reviewed, version-controlled source for prompt definitions and conservative workflow limits. `flowx_os.policies.load_registry` reads the file into immutable typed objects and rejects malformed JSON, unknown fields, duplicate prompt IDs, nonpositive versions, invalid retry limits, and inconsistent approval/publishing settings.

Prompt versions are immutable identifiers at lookup time: callers must request the supported version and receive a `KeyError` for unknown prompt IDs or versions. Registry changes should increment the registry version and the changed prompt's version, then receive ordinary code review. Prompt text is treated as data; this registry does not render user supplied text, invoke a model, or confer authority on remote content.

The initial policy caps scene regeneration at two attempts, requires human approval, and keeps autonomous publishing disabled. These are local configuration defaults, not evidence of a live provider integration or a complete production authorization system. Secrets and credentials do not belong in prompt files.

Run `python -m unittest discover -s tests -v` to validate the parser and policy rules.
