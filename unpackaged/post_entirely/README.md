# Entirely demo (`post_entirely`)

Revenue Cloud demo for the Entirely group (Censhare, Marmind, Facelift, Elaine,
Epoq, Business OS), following the fictional customer **Kestrel Home & Living
GmbH** through eight acts in about 60 minutes.

This bundle is **not** wired into `cumulusci.yml`. It is deployed on demand with
the `sf` CLI on top of an org already built by `prepare_rlm_org`.

## Acts

| Act | Topic | Status | Details |
| --- | ----- | ------ | ------- |
| 1 | HubSpot lead to qualified opportunity | Done | [act1-lead-to-opportunity.md](act1-lead-to-opportunity.md) |
| 2a | Catalog and standard pricing | Done | [act2a-pcm-and-pricing.md](act2a-pcm-and-pricing.md) |
| 2b | Derived support pricing | Done | [act2b-derived-pricing.md](act2b-derived-pricing.md) |
| 2c | Censhare configurator (CML) | Done | [act2c-cml.md](act2c-cml.md) |
| 3 | Price governance | Planned | — |
| 4 | Group selling | Planned | — |
| 5 | Usage-based pricing | Planned | — |
| 6 | Signature, Deal Desk and ERP handover | Planned | — |
| 7 | Amendment and renewal | Planned | — |
| 8 | Reporting | Planned | — |

Each act gets its own `act<N>-<topic>.md` file beside this one, covering its
click path, setup, components, design decisions and known issues. Act 2 is split
into three pieces that are validated and gated in order, so a failure in one
cannot be mistaken for a problem in another.

## Where things live

The demo uses the repo's existing folders rather than a separate project
folder. Everything carries `entirely` in its folder name or `RLM_Entirely` in
its API name.

| Location | Contents | Acts |
| -------- | -------- | ---- |
| `unpackaged/post_entirely/` | Salesforce metadata, in source format, one folder per metadata type | 1, 2 |
| `scripts/apex/entirely/` | Setup, reset and verify scripts, prefixed by act (`act1_*.apex`) | 1, 2 |
| `scripts/entirely/` | Workbook-to-SFDMU generator and test-quote builder | 2 |
| `datasets/sfdmu/entirely/` | SFDMU data plans for the catalog and pricing | 2 |
| `datasets/expression_set_overlays/entirely_*.json` | Pricing procedure overlay | 2 |
| `.agents/artifacts/` | Working notes and spike findings; private, not committed | All |

Metadata from every act shares one bundle so the whole demo deploys in one
command. When a component serves only one act, its act file says so.

## Deploy

```bash
sf project deploy start --source-dir unpackaged/post_entirely --target-org Entirely
sf org assign permset --name RLM_Entirely --target-org Entirely
```

Each act file lists any extra setup, reset scripts and first-deploy ordering it
needs.

## Things UX assembly will overwrite

UX assembly (`assemble_and_deploy_ux`) owns several components this demo
changes. Running it against the demo org undoes those changes:

- **Account, Contract and Opportunity layouts.** This bundle carries full
  copies of `RLM Account Layout`, `RLM Contract Layout` and
  `RLM Opportunity Layout`, whose source is `templates/layouts/base/`.
  Redeploy this bundle afterwards.
- **`RLM_Opportunity_Record_Page`.** Edited directly in the org and not stored
  in the repo. See the act files for what to redo.

The clean fix is a feature-gated UX patch under `templates/`, the way
`post_approvals` handles the Quote page. That needs a feature flag in
`cumulusci.yml`, which this demo deliberately leaves untouched.
