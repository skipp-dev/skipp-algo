# Blockquote-nested fences and inline spans

> **Always** run the following before pushing such edits:
> ```bash
> grep -nE "<old-value-or-pattern>" <edited-file>
> ```
> on the **whole file**, not just the diff hunk.

A nested blockquote also OK:

>> ```python
>> print("hi")
>> ```

Inline span inside blockquote: > use `make test` to verify.
