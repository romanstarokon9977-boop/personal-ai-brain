# Router audit — empty-response cooldown recovery

**Date:** 2026-11-20  
**Base:** `main` at `6e1c53b607e90287ee70d611ca39ac7a209f0cc5`  
**Scope:** OpenRouter/Gemini/local model health state, automatic route locks, and cooldown recovery.

## Findings

### P1 — AUTO route lock bypasses model cooldown

`rank_models()` excludes candidates while either `cooldown_until` or `empty_cooldown_until` is in the future. However, `controller_route()` returned any existing `model_lock` before calling `rank_models()`, regardless of whether the lock was `AUTO` or `MANUAL`.

An automatically selected model could therefore remain pinned after it entered cooldown. The availability display and the actual route could disagree.

**Correction:** retain explicit `MANUAL` locks, but invalidate an `AUTO` lock when its model has an active 429 or empty-response cooldown; then reselect through the normal ranking path.

### P1 — Successful recovery did not clear the cooldown timestamp

The API, Gemini, and local success paths reset `empty_streak` but did not reset `empty_cooldown_until`. A successful response could therefore leave a stale active cooldown in persisted router state until the 30-minute TTL elapsed.

**Correction:** clear both `empty_streak` and `empty_cooldown_until` after a successful response.

### P2 — Configured primary model is absent from the observed free catalog

`PRIMARY_MODEL` is configured as `nvidia/nemotron-3-super-120b-a12b:free`, while the user's current 29-model catalog did not contain that ID. The primary-model score bonus is consequently inert for that catalog, and the status label may be mistaken for the currently selectable model.

**Disposition:** documented, not changed. Replacing the preferred model is a product/model-selection decision and should not be inferred from a single catalog snapshot.

## Changes prepared

- Invalidate stale automatic route locks when the locked model is in cooldown.
- Preserve explicit manual model locks.
- Clear empty-response cooldown after successful API, Gemini, or local inference.
- Add regression tests for successful cooldown recovery, automatic lock reselection, and manual-lock preservation.

## Verification plan

GitHub Actions CI must pass for the PR head. Runtime confirmation on the POCO F6 should then verify:
1. A model with an active empty cooldown is not retained by AUTO routing.
2. A successful response clears its empty cooldown and restores READY eligibility.
3. A MANUAL lock remains unchanged.
