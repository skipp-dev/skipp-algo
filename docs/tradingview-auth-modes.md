# TradingView Auth Modes

## Purpose

TradingView automation must distinguish between a reusable authenticated session and a browser state that only looks partially usable.

The preflight now records the chosen auth source explicitly.

## Report Fields

- `auth_mode`
- `auth_source_path`
- `auth_reused_ok`

## Resolution Order

The automation resolves auth in this order:

1. `storage_state`
2. `persistent_profile`
3. `fresh_login`

## `storage_state`

Chosen when:

- `TV_STORAGE_STATE` is configured
- the file exists
- its cookies or TradingView localStorage keys match the auth heuristics

Result:

- preferred reusable mode
- `auth_reused_ok = true`

## `persistent_profile`

Chosen when:

- a valid storage-state file is not available
- `TV_PERSISTENT_PROFILE_DIR` is configured as the fallback source

Typical cases:

- the storage-state file exists but is anonymous
- the storage-state file is missing, but the persistent Chromium profile is intentionally reused

Result:

- explicit fallback mode
- the report keeps the profile path in `auth_source_path`

## `fresh_login`

Chosen when:

- no reusable auth source is configured

Result:

- preflight does not attempt an interactive login
- the report is written with failed auth status instead of continuing into misleading UI failures

## Practical Guidance

- Use `npm run tv:storage-state` when you want a portable reusable session file.
- Use `npm run tv:profile-login` when storage-state capture is unreliable and the persistent browser profile is the intended fallback.
- If the report says `fresh_login`, fix auth first and rerun preflight.
