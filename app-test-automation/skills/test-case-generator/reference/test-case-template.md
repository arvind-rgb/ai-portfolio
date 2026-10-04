# Test-Case Schema

Every TC in `state/testcases/test-cases.md` must follow this exact structure. The Maestro authoring phase reads these fields directly.

## Schema

```markdown
### TC-XXX — <short title>

- **Journey:** <name from user-flow.md, e.g., "Guest first order — Get Today">
- **Priority:** P0 | P1 | P2 | P3
- **Type:** smoke | regression | edge | negative
- **Platforms:** iOS | Android | both
- **Preconditions:**
  - <e.g., "App freshly installed">
  - <e.g., "SIT backend reachable">
- **Test data:**
  - phone: <TEST_PHONE>
  - otp: <TEST_OTP>
  - chef: Demo Chef (chef_id=99999)
  - <any TC-specific data>
- **Steps:**
  1. <action>
  2. <action>
  3. ...
- **Expected:**
  - <observable outcome 1>
  - <observable outcome 2>
- **Failure indicators:** <what a bug would look like — e.g., "OTP screen shows error toast", "Payment screen never opens">
- **Maps to source:** `src/screens/<file>.tsx` (best guess of the screen under test)
```

## Priority guide

| Priority | Use for |
|---|---|
| **P0** | Golden paths — login, place order Get Today, place order Get Later, subscription flow, payment handoff. Failures block release. |
| **P1** | High-traffic edge cases — coupon apply, address change, Veg Mode, cart empty state. |
| **P2** | Lower-traffic edges — slot expiry, OTP retry, address out of service area. |
| **P3** | Cosmetic / negative paths — bad input handling, force-close recovery. |

## Type guide

- **smoke** — quick golden-path check, < 60s per flow
- **regression** — broader coverage, may chain multiple screens
- **edge** — boundary conditions
- **negative** — invalid input or error states

## Counting / coverage rules (for the self-critique gate)

- Every journey in `user-flow.md` must have ≥1 P0 smoke TC.
- Every gotcha in `bhookleApp/CLAUDE.md §5` must map to ≥1 TC (edge or negative).
- Every critical journey (login, Get Today, Get Later, subscription) must have ≥1 negative TC.
- Veg Mode must have both values tested. Get Today and Get Later must each have a dedicated TC. Coupon must be tested both valid and invalid.
