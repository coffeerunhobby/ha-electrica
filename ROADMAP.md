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
