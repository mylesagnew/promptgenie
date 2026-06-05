# Prompt for Claude Code

## Objective
Refactor the auth module to replace session-based auth with JWT tokens using the PyJWT library.

## Scope
Work only within src/auth/ and src/middleware/auth.py.
Do not modify database schema or migration files.

## Constraints
- Do not install any packages without approval
- Do not modify files outside the defined scope
- Run the test suite after each file change

## Stop Conditions
Stop and ask for approval if:
- A new dependency would be added
- Tests fail after refactor
- Any file outside scope needs editing

## Output Format
Show diffs for each changed file.
Run tests and report results.
Summarise what changed and why.

## Acceptance Criteria
Done when:
- All auth routes use JWT
- Existing tests pass
- No session references remain in scope
