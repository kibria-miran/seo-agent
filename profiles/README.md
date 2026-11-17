# profiles/ — site profiles

## WARNING: `landc.json` contains a placeholder FCA reference

`landc.json` has `fca_firm_ref: "000000"`. This is a placeholder, not a real
FCA firm reference number. The FCA register (register.fca.org.uk) could not
be queried from the build environment, so no value was fabricated.

Consequences until the real FRN is filled in:

- Any compliance-linted output generated against this profile (e.g. drafts
  produced with `--with-drafts`) is untrusted. The lint cannot verify the
  FRN and may pass or flag `000000` arbitrarily.
- Drafts on the landc domain must not be published in this state.
- To fix: search "London & Country" on register.fca.org.uk, read the FRN
  from the firm page, replace `000000` in `landc.json`, and commit.
