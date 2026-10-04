# Maestro Cheat Sheet — Bhookle flows

Authoritative patterns for authoring `state/maestro/<TC-ID>.yaml`. Keep flows declarative, idempotent, and self-contained.

## File header (every flow)

```yaml
appId: ${APP_ID_IOS}      # or ${APP_ID_ANDROID} — picked by run-suite.sh per platform
name: TC-001 — Guest first order (Get Today)
tags:
  - smoke
  - P0
  - get-today
---
- launchApp:
    clearState: true
    arguments:
      env: SIT
```

`---` separates config block from the steps list.

## Common selectors

| Goal | Pattern |
|---|---|
| Tap by visible text | `- tapOn: "Continue"` |
| Tap by testID (preferred when set) | `- tapOn: { id: "btn-continue" }` |
| Tap nth occurrence | `- tapOn: { text: "Add", index: 0 }` |
| Tap by partial text | `- tapOn: { text: "Demo Chef.*", regex: true }` |
| Type into focused field | `- inputText: "<TEST_PHONE>"` |
| Type into specific field | `- inputText: { text: "${BHOOKLE_PHONE}", id: "phone-input" }` |
| Hide keyboard | `- hideKeyboard` |
| Scroll | `- scroll` or `- scrollUntilVisible: { element: { text: "Demo Chef" } }` |
| Swipe | `- swipe: { direction: UP }` |
| Wait for element | `- extendedWaitUntil: { visible: "Welcome", timeout: 10000 }` |
| Assert visible | `- assertVisible: "Order Placed"` |
| Assert not visible | `- assertNotVisible: "Error" }` |
| Back navigation | `- back` |
| Screenshot | `- takeScreenshot: result-TC-001` |

## Bhookle-specific patterns

### Login sub-flow (`state/maestro/subflows/login.yaml`)

```yaml
appId: ${APP_ID_IOS}
---
- tapOn: { text: "Login|Sign In", regex: true }
- inputText: "${BHOOKLE_PHONE}"
- tapOn: "Send OTP"
- extendedWaitUntil: { visible: "Enter OTP", timeout: 8000 }
- inputText: "${BHOOKLE_OTP}"
- tapOn: "Verify"
- extendedWaitUntil: { visible: "Welcome|Home", regex: true, timeout: 12000 }
```

Use from any flow:
```yaml
- runFlow: subflows/login.yaml
```

### Selecting Demo Chef chef

```yaml
- tapOn: { text: "Home" }          # ensure on Home tab
- scrollUntilVisible: { element: { text: "Demo Chef" }, timeout: 15000 }
- tapOn: "Demo Chef"
- assertVisible: "Demo Chef"
```

### Adding a dish and placing a Get Today order

```yaml
- tapOn: { text: "ADD", index: 0 }
- assertVisible: "1"               # quantity indicator
- tapOn: { id: "cart-fab" }
- assertVisible: "Order Summary"
- tapOn: "Proceed to Pay"
- extendedWaitUntil: { visible: "Payment", timeout: 8000 }
- # Payment screen is provider-mediated; assert + screenshot only
- takeScreenshot: payment-handoff
```

### Veg Mode toggle (two-valued)

```yaml
- tapOn: { id: "veg-mode-toggle" }
- assertVisible: "Veg from all kitchens"
- tapOn: { text: "Veg from all kitchens" }
- # Cycle to Pure Veg variant
- tapOn: { id: "veg-mode-toggle" }
- assertVisible: "Veg from Pure Veg kitchens"
```

### Network-offline (negative test)

Maestro can't toggle airplane mode directly. Use shell hooks:
```yaml
- runScript: |
    xcrun simctl status_bar booted override --dataNetwork hidden
- tapOn: "Reload"
- assertVisible: "No internet"
- runScript: |
    xcrun simctl status_bar booted clear
```

## Run conventions

- Every flow ends with `- takeScreenshot: result-<TC-ID>`.
- Every flow starts with `launchApp: { clearState: true }` so tests are independent.
- Never hardcode credentials — use `${BHOOKLE_PHONE}` / `${BHOOKLE_OTP}` from `config.yaml`.
- Prefer `extendedWaitUntil` over fixed sleeps; cap timeouts at 15s.
- For payment screens, **screenshot and assert handoff** only — do not attempt to complete real payments.

## Output

`run-suite.sh` invokes each flow with:
```
maestro test \
  --env-file state/maestro/config.yaml \
  --format junit \
  --output state/reports/<ts>/junit/<TC-ID>.xml \
  state/maestro/<TC-ID>.yaml
```
