# Prompt for Claude Code

## Objective
Refactor the authentication module to replace session tokens with JWT using PyJWT.

## Scope
Work only within:
- src/auth/
- src/middleware/auth.py

## Constraints
- Do not install packages without approval
- Do not modify files outside the defined scope

## Forbidden Actions
- Do not run migrations
- Do not push to any live environment

## Stop Conditions
Stop and ask for approval if:
- A new dependency would be added
- Tests fail and the fix is non-obvious
- Any file outside scope needs changing

## Output Format
Show diffs for each changed file.
Run tests and report results.

## Acceptance Criteria
Done when:
- All auth routes use JWT
- Existing tests pass
- No session references remain in scope
