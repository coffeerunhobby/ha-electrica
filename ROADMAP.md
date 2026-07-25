# Roadmap

## v0.2.0 — multi-NLC correctness, Romanian UX, docs

### Correctness (highest priority)

- [ ] **Payment attribution for multi-NLC accounts.** Payments are fetched per
      client code and currently copied to *every* NLC beneath it, so an account
      with several consumption points shows the same payments on each device.
      Correlate payments to a point via the invoices they settle
      (`InvoiceID` → invoice → NLC) instead.
- [ ] **Invoice attribution fallback.** When an invoice carries no `nlcField`,
      the code falls back to attributing *all* client invoices to the point.
      That is right for single-NLC accounts but wrong when a client code owns
      several. Fall back to the contract account instead, and only attribute
      unambiguously.
- [ ] Add a multi-NLC test fixture (synthetic) covering both of the above —
      the current test data has a single point, which is exactly why these
      slipped through.

### Credential handling

Goal: stop persisting the account password once setup has completed.

Home Assistant stores config-entry data in plaintext in `.storage`, and any
local encryption would need its key on the same machine — so encrypting the
password there is obfuscation, not protection. The meaningful improvement is to
**store a session token instead of the password**: a leaked token is scoped to
Electrica and is invalidated by a password change, whereas a leaked password may
unlock unrelated accounts through password reuse.

Measured so far (against the live API):

- `/login` returns an opaque 58-character server-side token — not a JWT, so it
  carries no readable expiry.
- Every login mints a **new** token, and **older tokens stay valid** — signing in
  on the mobile app does not evict Home Assistant's session.
- Token lifetime is still unknown; `tools/probe_electrica.py tokentest` records
  a token with a timestamp and re-checks it on later runs to measure it.

Confirmed by inspecting the official Android app (v4.0.4):

- Its login response carries **only** `{error, message, app_token}` — there is
  **no refresh token and no expiry field** anywhere in the API. So there is no
  refresh mechanism to adopt; the only choice is token-until-it-dies (then
  reauth) or storing the password for unattended re-login.
- The app's own login is `/api/login-mobile`, which differs from the web
  `/api/login` only by an extra `versiune` (version) field. Same response shape,
  so nothing is gained by switching.

- [ ] Decide based on the measured lifetime:
      - **long-lived** → store only the token; drop the password after setup and
        send the user through the existing reauth flow when it finally expires.
      - **short-lived** → keep the password (unattended re-login is required),
        and document plainly that `.storage` must be protected.
- [ ] Either way: never log the token, and keep it redacted in diagnostics.
- [ ] **Revoke the token on unload/removal** via `POST /api/logout/current`, so a
      removed integration does not leave a live session behind. Cheap, and the
      single clearest security win available.

### Endpoints known but deliberately unused

Discovered while mapping the API; recorded so nobody re-investigates them:

- `/api/download/sap/…`, `/api/download/open/…` — invoice PDF fetch (we already
  surface `DownloadPDFUrl`).
- `/api/gdpr`, `/api/gdpr/{client_code}` — personal-data export.
- `/api/adauga-cod-client`, `/api/electronic-mail-options` — account admin.
- **Never implement:** `/api/request-plata` (initiates a payment),
  `/api/modifica-parola`, `/api/solicitare-resetare-parola`, `/api/sterge-cont`
  (deletes the account). A home-automation integration must not move money or
  perform destructive account operations.

### Features

- [ ] **Select which NLCs to monitor** in the config flow and OptionsFlow.
      Today every discovered point is monitored; accounts with many points
      have no way to narrow it down.
- [ ] **Contract / customer detail sensors.** The contract payload is already
      parsed but not surfaced. Expose as diagnostic, disabled-by-default
      entities so they add no clutter by default.
- [ ] Consider making the invoice/payment history depth configurable
      (currently the latest 12 are exposed as attributes).

### Localisation

- [ ] **Romanian translation** (`translations/ro.json`) for the config flow,
      options and error messages. Entity names and states stay English —
      only the setup/UI text is localised.
- [ ] Nicer address formatting for device names (title-casing, county codes)
      — the API returns SHOUTED address fields.

### Documentation

- [ ] `SETUP.md` (step-by-step with screenshots), `FAQ.md`, troubleshooting.
- [ ] Dashboard and automation examples — notably "notify me when the
      self-reading window opens" and "notify me before an invoice is due",
      which are the two highest-value automations this integration enables.

### Project maturity

- [ ] Release workflow (tag → build notes → publish) instead of manual
      releases.
- [ ] Submit to the HACS default store.

## Known documentation fixes

- [x] README said "istoric complet" (complete history) for invoices and
      payments; only the latest 12 are exposed as attributes. Corrected.
