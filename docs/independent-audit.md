# Independent implementation and usage audit

Date: 2026-11-03. Reviewer: independent Codex agent (`audit`), not Gemini. Scope: skill entrypoints, project record/recovery SOP, review protocol, existing H3 finish/concat and submission safeguards. This audit does not count as any of the 24 Gemini usage trials.

## Evidence

- `python -m pytest tests -q`: **21 passed** in 0.28 s at audit start.
- Checked Markdown local links from every `skills/**/SKILL.md`: **zero missing targets**.
- Director can route a text-only project without media generation; catalogue marks writing and H3 prompt skills as external dependencies and provides a missing-dependency path.
- Review protocol specifies deterministic sampling, artifact hashes, actual user provenance for human review, and stopping bounds.
- Tests currently cover legacy safety, JSON atomicity/corruption, artifact hashes and import conflicts; they do not yet prove end-to-end finish/concat or 24 independent agent usages.

## Findings at audited state

### P1 — finish permits an unreviewed selected final

`h3proj.py:802-817` checks the `first.video` and its visual review, then selects arbitrary `a.final` or `files.final`. There is no comparison between selected final and reviewed source. `run_qc(...full=False)` at line 921 intentionally skips visual checking. Reproduced with temp files and mocked stream/FFmpeg boundary: a valid review on bytes A plus `--final` file B reached FFmpeg extraction with B. Output: `OLD_REVIEW_ACCEPTED_FOR_DIFFERENT_FINAL=True`.

Fix: bind the selected final to explicit review evidence or a validated derivation from the reviewed source, and invalidate that review if selected final bytes change. Add a regression that rejects B before FFmpeg processing.

### P1 — concat can destroy an older successful whole-film artifact

`cmd_concat` chooses `out` at approximately line 1024 and FFmpeg writes `-y` directly to it (lines 1042/1063/1093). Unlike segment finish, there is no temporary output plus validation then atomic replacement. A failed/cancelled concat may truncate a prior deliverable. Output aliasing any input path is also not rejected early.

Fix: prohibit output/input alias; produce a sibling temporary file; inspect/decode and atomically replace only on successful checks; preserve the previous deliverable on failure.

### P2 — blocking review policy is an SOP responsibility, not a script invariant

Current `require_review` only consumes first QC and visual_review, not the new `checks/` review records or project blocking/human policy. Therefore passing old-style visual_review does not prove all required blocking reviews passed. The final release path must either consume these records or require an explicit coordinator final-review evidence step before calling delivery. Do not describe this as programmatically enforced until tested.

### P2 — fingerprints do not yet cover selected skill / project policy revisions

`require_current_inputs` compares segment specification and declared file hashes only. The submitted graph contributes to input_fingerprint but is not recomputed against changed selected skills/project settings at downstream release. A skill/profile change without changed prompt/workflow bytes can leave an old record appearing current. Clearly bind the project-selected production version (relevant subset only, excluding mixing-only fields) and test targeted invalidation.

## Recommended closure evidence

Run regressions for all findings above; perform skill replacement and rollback on an isolated project with saved old/new hashes; execute the fixed fixture tasks in new external-agent sessions. Keep physical validity, content quality and external-agent usability as separate report columns. Hardware generation and visual/auditory quality were not evaluated in this audit.


## Follow-up verification after fixes

Rechecked current implementation and executed `python -m pytest tests -q`: **30 passed in 0.70 s**. No GPU task was submitted by this reviewer.

- **Original P1 final-source review bypass: closed.** `cmd_finish` now compares selected final content hash to reviewed first content, requiring a separate `final_review` for a different final. The new `test_final_cannot_reuse_other_video_review` exercises rejection before media processing.
- **Original P1 destructive concat output: closed for the reported failure and direct input-alias cases.** FFmpeg now writes a sibling `.candidate.mp4`, requires a video stream and positive duration, then uses `os.replace`. `test_concat_failure_preserves_old_output` proves a failed write retains previous film bytes; `test_concat_rejects_input_alias` proves direct source-overwrite rejection.
- **Configured review consumer: added and verified.** `require_configured_reviews` checks required status, nonempty evidence, requested reviewer kind, human-source reference and current artifact hash. `cmd_concat` calls it before output creation. Tests cover missing human provenance, changed artifact and nonblocking review behavior. This enforces reviews explicitly declared in `plan.required_reviews`; it does not infer undeclared policies.
- **Production context invalidation: added and verified.** Snapshot comparison includes `render_context(project)` with selected skills/render settings/style/production path/keyframe requirement. The regression proves changing selected render skill invalidates generation while adding mixing parameters preserves it.
- **Recovery regressions: passed.** Lost receipt is reconciled by original client identity without `/prompt`, while unresolved receipt refuses retry even with force.

Remaining validation limits: media candidate acceptance currently uses stream metadata and positive duration; this audit did not prove full decode or expected total duration matching. Actual video/audio quality still requires the separate media review workflow. Human-source fields are provenance references supplied by the coordinator, not cryptographic proof of user identity. Actual Gemini trials and real GPU sample review remain separate evidence and were not performed here.
