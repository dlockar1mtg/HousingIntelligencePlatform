# UIP integration

`HousingIntelligencePlatform` → `housing_uip_contract.json` (versioned, validated) → UIP publication cycle
(optional source, never blocks the certified domains) → Homestead page.

The housing repo owns the housing facts: market state, Entry Score and signal with calibration status,
forecasts with ranges, triggers, financing scenarios. The UIP owns the cross-domain decision: what the plan
can afford when, how much stays invested, and the house's effect on net worth.

The household side comes from the UIP's household plan (versioned profile contract) instead of a separate
`personal_profile.json`.

Planned Homestead uses: home price at the target date (today's target price grown by the market forecast),
a live mortgage rate instead of the 6.5% placeholder, Wichita and DFW market cards, and triggers.
