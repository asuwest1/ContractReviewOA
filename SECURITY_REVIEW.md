# Code Review & Security Check

Date: 2026-02-15

## Scope
- `contract_review/` backend modules
- `tests/` coverage around auth and file handling

## Checks Run
- Unit tests (`pytest`)
- Bytecode compilation (`python -m compileall`)
- Static risky-pattern scan (`rg` for dynamic execution, unsafe deserialization, shell execution)
- Attempted Bandit static analysis (`bandit -r contract_review -q`) but tool unavailable in this environment

## Findings and Actions
1. **High: Development header auth enabled by default**
   - Risk: in production-like deployments, spoofable `X-Remote-User` / `X-User-Roles` headers could be trusted when IIS-integrated variables are absent.
   - Action: changed default `ALLOW_DEV_HEADERS` to `false`; operators must opt in explicitly.

2. **High: Potential path traversal in document filename**
   - Risk: user-supplied filenames like `../x` could escape intended storage folder.
   - Action: sanitize filename via basename and reject path-like values (`..`, separators, empty).

3. **Medium: Internal exception details leaked over API**
   - Risk: returning raw exception text in HTTP 500 can expose implementation details.
   - Action: replaced 500 response payload with generic message.

## Post-fix Validation
- Added regression tests for auth-header default behavior and path traversal rejection.
- Full test suite passes.
