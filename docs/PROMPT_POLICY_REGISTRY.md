# Prompt and policy registry

`config/prompt_registry.json` is the reviewed, version-controlled source for prompt definitions and conservative workflow limits. `flowx_os.policies.load_registry` reads the file into immutable typed objects and rejects malformed JSON, unknown fields, duplicate prompt ID/version pairs, unsafe template fields, nonpositive versions, invalid retry limits, and inconsistent approval/publishing settings. Multiple versions of one ID are retained; callers can pin an exact version, while an omitted version selects the highest registered version.

Prompt versions are immutable identifiers at lookup time. Registry changes should increment the registry version and the changed prompt's version, then receive ordinary code review. Templates declare an exact allowlist of plain string placeholders; attribute/index expressions, conversions, and format operations are rejected. Rendering bounds input values and total prompt size and screens for common credential patterns. Rendered values are inserted as data, while system instructions tell the provider to treat user/source text as untrusted. Rendering does not invoke a model or confer authority on remote content.

The initial policy caps scene regeneration at two attempts, requires human approval, and keeps autonomous publishing disabled. These are local configuration defaults, not evidence of a live provider integration or a complete production authorization system. Secrets and credentials do not belong in prompt files.

Run `python -m unittest discover -s tests -v` to validate the parser and policy rules.
