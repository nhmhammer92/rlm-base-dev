# LWR Billing Self-Service Site Metadata

This directory contains the Experience Cloud site metadata for the RLM LWR billing
self-service site: a Lightning Web Runtime (LWR) `DigitalExperienceBundle` and its
`DigitalExperienceConfig`, `Network`, `NavigationMenu` and `CustomSite`.

## Why a second billing site

Salesforce Release 264 (Winter '27) added five billing self-service components to the
Experience Builder palette, under the **Layout** section:

| Component | Purpose |
|-----------|---------|
| Posted Invoices | List of posted invoices for the current user's account |
| Invoice Line Viewer | Line items of an invoice |
| Self-Service Payment Sheet | Payment methods for an invoice, including saved ones; add a new method, save it, and submit payment |
| Self-Service Payment Confirmation | Whether a payment submitted from the Payment Sheet succeeded |
| Manage Saved Payment Methods | Add or delete a saved payment method and set a default |

These are available **only on LWR sites**
([`ind.billing_self_service_lwr_components.htm.md`](../../docs/salesforce/264/help/articles/ind.billing_self_service_lwr_components.htm.md)).
The existing Self-Service Billing Portal (`unpackaged/post_billing_portal/`,
`create_billing_portal`) is an Aura site — `ExperienceBundle`, type
`ChatterNetworkPicasso`, `/s` URL prefix, `siteforce:sldsOneColLayout` page layouts — so
the components never appear in its palette. Adding them requires a separate LWR site,
which is what this bundle and `create_billing_portal_lwr` provide.

The Aura portal already covers most of the same ground with its own components
(`runtime_payments:paymentSheet`, `runtime_payments:paymentByExpress`,
`runtime_revenue_foundation:postedInvoices`, `runtime_revenue_foundation:invoiceLineViewer`,
`runtime_revenue_foundation:selfServiceConfModal`). The capability it has no equivalent for
is a standalone **Manage Saved Payment Methods** page. The two sites are independent
Networks and share no content; neither replaces the other.

## Status — skeleton only, components not yet placed

This bundle is the **unmodified "Build Your Own (LWR)" template** as created in a Release
264 org (API v68.0), with the portability fixes below applied. **None of the five billing
components is placed yet**, so the site renders the stock "Start Building Your Page"
placeholder.

The components have to be dragged onto pages in Experience Builder and the site
re-retrieved: their internal names and attribute keys are not published in the Help or
Developer Guide snapshots and are not queryable (`LightningComponentBundle` returns custom
components only). Guessing them produces a bundle that deploys but renders nothing.

`billing_portal_lwr_deploy` therefore defaults to `false`. With it off,
`prepare_billing_portal_lwr` creates and publishes the site and skips the deploy, so
turning `billing_portal_lwr` on is safe meanwhile. Flip the deploy flag once step 2 below
is done and the bundle has been re-retrieved.

## Contents

```
digitalExperiences/site/Billing_Self_Service1/   # pages, theme layouts, routes (LWR)
digitalExperienceConfigs/                        # site config
navigationMenus/                                 # default navigation
networks/Billing Self Service.network-meta.xml   # Network (email placeholdered)
sites/Billing_Self_Service.site-meta.xml         # CustomSite (siteAdmin placeholdered)
```

The layout is flat, matching `unpackaged/post_payments/` rather than the
`force-app/main/default/` nesting in `unpackaged/post_billing_portal/`. That is what
`sf project retrieve start --output-dir <this dir>` produces, and
`cumulusci.tasks.salesforce.Deploy` accepts either.

LWR pages are JSON under `sfdc_cms__view/<page>/content.json` and name components with a
`"definition"` key (`community_layout:section`, `community_builder:htmlEditor`), not the
Aura bundle's `componentName` / `fqn` pair. Record the billing components' real
`definition` values and attribute keys in a table here once they are placed.

## Naming

`create_billing_portal_lwr` creates the community with `name: "Billing Self Service"`.
Salesforce derives the rest; these were read back from a 264 org rather than guessed, the
same caution `post_billing_portal/README.md` records:

| Metadata | Name |
|----------|------|
| Network | `Billing Self Service` (spaces preserved — the file name **is** the metadata full name) |
| CustomSite | `Billing_Self_Service` |
| DigitalExperienceBundle | `site/Billing_Self_Service1` |
| DigitalExperienceConfig | `Billing_Self_Service1` |
| NavigationMenu | `SFDC_Default_Navigation_Billing_Self_Service` |

If `create_billing_portal_lwr`'s `name` option ever changes, re-derive all of the above the
same way — create a throwaway community with the new name and query the results. Don't
guess the transform.

`urlPathPrefix` is committed as `billingssvforcesite`, not the `billingss` the task
requests: the org appends the suffix at creation. `post_payments` carries the same
`sfpwebhookvforcesite` for the same reason.

## Portability Notes

A full scan of the retrieved bundle found exactly two org-specific values, both
placeholdered and both restored at deploy time by existing tasks:

| Value | Placeholder | Handled by |
|-------|-------------|------------|
| `Network.emailSenderAddress` | `billing-selfservice-sender@example.com` | `patch_network_email_for_deploy` / `revert_network_email_after_deploy` (flow steps 2 and 5) |
| `CustomSite.siteAdmin`, `siteGuestRecordDefaultOwner` | `billing-selfservice-site-admin@example.com` | `patch_payments_site_for_deploy` / `revert_payments_site_after_deploy` (flow steps 3 and 6) |

Both pairs live in `tasks/rlm_community.py` and are parameterized by path and placeholder,
so reusing them needed no new Python — only `options:` overrides in the flow. The second
pair is named for Payments because that is where it was introduced; it is generic.

Nothing else needed fixing. Unlike the Aura template, this one dropped in no Embedded
Messaging component, so there is no per-org `scrtUrl` to strip, and the bundle carries no
`trustedSites` entries, instance URLs or org IDs. `tests/test_billing_portal_config.py`
asserts the committed placeholders still match what the flow substitutes, so the two cannot
drift into a deploy-time "Placeholder not found".

## Remaining work — placing the components

### 1. Prerequisites

A 264 org with Billing and Payments, and a merchant account in `Complete` status — the
Payment Sheet cannot take a payment without one. Check with:

```bash
sf data query -q "SELECT Id, Name, Status FROM MerchantAccount" --target-org <sf_alias>
sf data query -q "SELECT Id, DeveloperName, MerchantAccountId FROM MerchAccPaymentMethodSet" --target-org <sf_alias>
```

Without a Payment Method Set the sheet offers only credit card, ACH and saved payment
methods. Setup steps:
[`ind.billing_self_service_portal_pay_invoices.htm.md`](../../docs/salesforce/264/help/articles/ind.billing_self_service_portal_pay_invoices.htm.md).

### 2. Build the pages in Experience Builder

Manual — the components have to be dragged onto pages.

| Page | Component | Settings |
|------|-----------|----------|
| Home | Posted Invoices | — |
| Invoice detail | Invoice Line Viewer | plus a link to the Pay Invoice page |
| Pay Invoice | Self-Service Payment Sheet | Invoice ID `{!invoiceId}`, Merchant Account ID, Payment Method Set Developer Name (optional), Payment Confirmation Page URL `payment-confirmation` |
| Payment Confirmation | Self-Service Payment Confirmation | — |
| Manage Payment Methods | Manage Saved Payment Methods | — |

Build the navigation menu with My Cases, Help Center and Manage Payment Methods, then
publish.

### 3. Re-retrieve over this directory

```bash
sf project retrieve start \
  --metadata "DigitalExperienceBundle:site/Billing_Self_Service1" \
  --metadata "DigitalExperienceConfig:Billing_Self_Service1" \
  --metadata "Network:Billing Self Service" \
  --metadata "CustomSite:Billing_Self_Service" \
  --metadata "NavigationMenu:SFDC_Default_Navigation_Billing_Self_Service" \
  --target-org <sf_alias> \
  --output-dir unpackaged/post_billing_portal_lwr
```

The retrieve overwrites the two placeholders with the source org's real values. Restore
them before committing, or the repo stores PII:

```bash
git diff -- unpackaged/post_billing_portal_lwr/networks unpackaged/post_billing_portal_lwr/sites
```

The Merchant Account ID on the Payment Sheet is also org-specific. Decide once the
retrieved JSON shows how it is stored: either blank it and document setting it per org as a
post-deploy admin step, or add a deploy-time patch task that queries the org's merchant
account.

Then set `billing_portal_lwr_deploy: true`.

## Deployment

```bash
cci flow run prepare_billing_portal_lwr --org <cci_alias>
```

Steps, each gated on `billing`, `payments` and `billing_portal_lwr`:

1. `create_billing_portal_lwr` — create the site
2. `patch_network_email_for_deploy` — steps 2-6 also require `billing_portal_lwr_deploy`
3. `patch_payments_site_for_deploy`
4. `deploy_post_billing_portal_lwr`
5. `revert_network_email_after_deploy`
6. `revert_payments_site_after_deploy`
7. `publish_community`

The `payments` gate is not incidental: the Payment Sheet needs a merchant account, which
`prepare_payments` sets up. `prepare_payments` is step 4 of `prepare_rlm_org` and
`prepare_billing` is step 13, so the ordering already holds.

The flow is step 6 of `prepare_billing_portal`, which is step 16 of `prepare_billing`, so it
runs as part of `prepare_rlm_org` whenever the gates are true. It is appended rather than
inserted so no existing step coordinates shift.

If the deploy fails, CumulusCI stops the flow before the reverts. Restore both placeholders
before committing or rerunning:

```bash
cci task run revert_network_email_after_deploy \
  -o network_meta_xml_path "unpackaged/post_billing_portal_lwr/networks/Billing Self Service.network-meta.xml" \
  -o placeholder_email billing-selfservice-sender@example.com

cci task run revert_payments_site_after_deploy \
  -o site_meta_xml_path "unpackaged/post_billing_portal_lwr/sites/Billing_Self_Service.site-meta.xml" \
  -o placeholder_username billing-selfservice-site-admin@example.com
```

Neither recovery task takes `--org`. The shared failure-path limitation is tracked in
[`#354`](https://github.com/bgaldino/rlm-base-dev/issues/354).

## Customer access (required — this flow is metadata-only)

A published site is not usable by customers until they are provisioned separately; the flow
does not do it. Per the Self-Service Billing Portal Help:

- **Build/customize the site:** the **Billing Admin** permission set.
- **Portal customers:** the **Billing Experience Cloud User** permission set, plus record
  access to their invoices. Create Customer Community Plus or Partner Community users and a
  sharing set before they log in.

## PII Handling

`Network.EmailSenderAddress` is immutable after community creation and required by the
metadata deploy, and `CustomSite.siteAdmin` must name a user that exists in the target org.
Both are stored as non-PII placeholders and substituted for the deploy only. Same pattern as
`post_prm`, `post_billing_portal` and `post_payments`, reusing the same task classes in
`tasks/rlm_community.py` via `options:` overrides.

## Feature Flags

```yaml
project_config:
  project__custom__:
    billing: true                    # Required parent feature
    payments: true                   # Required: the Payment Sheet needs a merchant account
    billing_portal_lwr: true         # Create the LWR site
    billing_portal_lwr_deploy: true  # Also deploy this bundle (see Status above first)
```

`billing_portal_lwr` is independent of `billing_portal`: run either site, both, or neither.

## Verification

Created, retrieved and redeployed against a Release 264 Enterprise org (API v68.0): the
bundle round-trips and the Network and CustomSite deploy cleanly with the patched values.
Not yet exercised on a fresh scratch org, and not yet exercised through
`cci flow run prepare_billing_portal_lwr` end to end.

## Related Documentation

- [`unpackaged/post_billing_portal/README.md`](../post_billing_portal/README.md) — the Aura
  portal; structural precedent for naming, PII handling and portability fixes
- [`unpackaged/post_payments/`](../post_payments/) — the other LWR site in the repo
  (Payments Webhook), precedent for the `CustomSite` patch/revert pair
- [Repository Integration Skill](../../.cursor/skills/repo-integration/SKILL.md)
