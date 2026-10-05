## Session handoff
`/preflight` opens a session and `/sync` closes it. Both are user-only: never call them through the Skill tool or
follow their SKILL.md by hand; ask the user to type them. Live state per project: `<config>/handoffs/<key>.md`;
user-wide conventions: `<config>/handoffs/_USER.md`. `SESSION_RESUME.md` is legacy (converted by the first /sync).
Never edit `_USER.md` mid-session: a general rule the user states is noted and left for `/sync` to propose (its yes/no
gate).
To hand something to another session or machine, write a note: `python3 <config>/tools/session/close.py note
--to <key> --from <you> --subject "..."` (also when a cross-session message fails because the target has ended).
