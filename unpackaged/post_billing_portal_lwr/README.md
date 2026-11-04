# LWR Billing Self-Service Site Metadata

This directory holds the Experience Cloud site metadata for the RLM LWR billing
self-service site: a Lightning Web Runtime (LWR) `DigitalExperienceBundle`, its `Network`,
`NavigationMenu`, and — if the retrieve produces one — its `CustomSite`.

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
is a standalone **Manage Saved Payment Methods** page. Keep both sites only while you need
the Aura one; they are independent Networks and do not share content.

## Status — bundle not yet populated

**This directory currently contains only this README.** The site content has to come from
an org retrieve, not from hand-authored JSON: the internal component names and attribute
keys for the five LWR components are not published anywhere, are not queryable
(`LightningComponentBundle` returns custom components only), and are not recorded in the
Help or Developer Guide snapshots. Guessing them produces a bundle that deploys but renders
nothing.

That is why `billing_portal_lwr_deploy` defaults to `false`. With it off,
`prepare_billing_portal_lwr` creates and publishes a bare Build Your Own (LWR) site and
skips the deploy, so the flow is safe to enable before this bundle has content. Turn the
flag on only after completing the round-trip below.

## Populating the bundle (one-time round-trip)

### 1. Create the site

```bash
cci task run create_billing_portal_lwr --org <cci_alias>
```

The site needs a 264 org with Billing and Payments, and a configured merchant account — the
Payment Sheet cannot take a payment without one. Set up the merchant account first; see
[`ind.billing_self_service_portal_pay_invoices.htm.md`](../../docs/salesforce/264/help/articles/ind.billing_self_service_portal_pay_invoices.htm.md).

### 2. Build the pages in Experience Builder

This step is manual: the components have to be dragged onto pages in the builder.

| Page | Component | Settings |
|------|-----------|----------|
| Home | Posted Invoices | — |
| Invoice detail | Invoice Line Viewer | plus a link to the Pay Invoice page |
| Pay Invoice | Self-Service Payment Sheet | Invoice ID `{!invoiceId}`, Merchant Account ID, Payment Method Set Developer Name (optional), Payment Confirmation Page URL `payment-confirmation` |
| Payment Confirmation | Self-Service Payment Confirmation | — |
| Manage Payment Methods | Manage Saved Payment Methods | — |

Build the navigation menu with My Cases, Help Center and Manage Payment Methods, then
publish.

Without a Payment Method Set Developer Name the sheet offers only credit card, ACH and
saved payment methods. Retrieve the available sets with:

```bash
sf data query -q "SELECT Id, DeveloperName, MerchantAccountId FROM MerchAccPaymentMethodSet" --target-org <sf_alias>
```

### 3. Retrieve

Confirm the derived metadata names first — do not guess the transform from the community
name, the same caution `post_billing_portal/README.md` records:

```bash
sf data query -q "SELECT Name, UrlPathPrefix FROM Network WHERE UrlPathPrefix = 'billingss'" --target-org <sf_alias>
sf data query -q "SELECT Name FROM Site WHERE Name LIKE 'Billing_Self%'" --target-org <sf_alias>
```

Then retrieve into this directory:

```bash
sf project retrieve start \
  --metadata "DigitalExperienceBundle:site/<SiteName>" \
  --metadata "DigitalExperienceConfig:<SiteName>" \
  --metadata "Network:<NetworkName>" \
  --metadata "CustomSite:<SiteName>" \
  --metadata "NavigationMenu:<NavMenuName>" \
  --target-org <sf_alias> \
  --output-dir unpackaged/post_billing_portal_lwr
```

Record the real component names and attribute keys the retrieve reveals in a table in this
README, so later readers do not have to re-derive them.

### 4. Apply the portability fixes

| Value | Fix |
|-------|-----|
| `Network.emailSenderAddress` | Immutable after creation but required by the deploy. Store the placeholder `billing-selfservice-sender@example.com`; `patch_network_email_for_deploy` / `revert_network_email_after_deploy` substitute the org's real value for the deploy and restore the placeholder afterwards. Already wired as steps 2 and 4 of `prepare_billing_portal_lwr` — no new Python needed, both tasks take `network_meta_xml_path` and `placeholder_email` options. |
| `CustomSite.siteAdmin`, `siteGuestRecordDefaultOwner` | Only if the retrieve produces a `CustomSite`. Placeholder them and add `patch_payments_site_for_deploy` / `revert_payments_site_after_deploy` steps around the deploy, overriding `site_meta_xml_path` and `placeholder_username` — the same tasks `prepare_payments` uses for `Payments_Webhook.site-meta.xml`, already parameterized in `tasks/rlm_community.py`. |
| Merchant Account ID on the Payment Sheet | Org-specific. Blank it and document setting it per org as a post-deploy admin step, or add a deploy-time patch task that queries the org's merchant account. Decide after seeing the retrieved JSON. |
| Embedded Messaging `scrtUrl` | Points at the source org's auto-generated SCRT domain and is meaningless elsewhere. Strip the component if the template dropped an unconfigured one in, as was done for the Aura portal. |
| Other org-specific domains, `trustedSites` | Strip or placeholder. |

Then set `billing_portal_lwr_deploy: true` and verify the full flow on a fresh org.

## Deployment

```bash
cci flow run prepare_billing_portal_lwr --org <cci_alias>
```

Steps, each gated on `billing`, `payments` and `billing_portal_lwr`:

1. `create_billing_portal_lwr` — create the site
2. `patch_network_email_for_deploy` — only when `billing_portal_lwr_deploy` is also true
3. `deploy_post_billing_portal_lwr` — only when `billing_portal_lwr_deploy` is also true
4. `revert_network_email_after_deploy` — only when `billing_portal_lwr_deploy` is also true
5. `publish_community`

The `payments` gate is not incidental: the Payment Sheet needs a merchant account, which
`prepare_payments` sets up. `prepare_payments` is step 4 of `prepare_rlm_org` and
`prepare_billing` is step 13, so the ordering already holds.

The flow is step 6 of `prepare_billing_portal`, which is step 16 of `prepare_billing`, so it
runs as part of `prepare_rlm_org` whenever the gates are true. It is appended rather than
inserted so no existing step numbers shift.

If the deploy step fails, CumulusCI stops the flow before the revert. Restore the
placeholder before committing or rerunning:

```bash
cci task run revert_network_email_after_deploy \
  -o network_meta_xml_path "unpackaged/post_billing_portal_lwr/force-app/main/default/networks/Billing Self Service.network-meta.xml" \
  -o placeholder_email billing-selfservice-sender@example.com
```

This local recovery task does not take `--org`. The shared failure-path limitation is
tracked in [`#354`](https://github.com/bgaldino/rlm-base-dev/issues/354).

## Customer access (required — this flow is metadata-only)

A published site is not usable by customers until they are provisioned separately; the flow
does not do it. Per the Self-Service Billing Portal Help:

- **Build/customize the site:** the **Billing Admin** permission set.
- **Portal customers:** the **Billing Experience Cloud User** permission set, plus record
  access to their invoices. Create Customer Community Plus or Partner Community users and a
  sharing set before they log in.

## PII Handling

`Network.EmailSenderAddress` is immutable after community creation and required by the
metadata deploy, so the committed file stores the non-PII placeholder
`billing-selfservice-sender@example.com` and the patch/revert tasks substitute the org's
real value for the deploy only. Same pattern as `post_prm` and `post_billing_portal`,
reusing the same task classes in `tasks/rlm_community.py` via `options:` overrides.

## Feature Flags

```yaml
project_config:
  project__custom__:
    billing: true                    # Required parent feature
    payments: true                   # Required: the Payment Sheet needs a merchant account
    billing_portal_lwr: true         # Create the LWR site
    billing_portal_lwr_deploy: true  # Also deploy this bundle's content (needs a populated bundle)
```

`billing_portal_lwr` is independent of `billing_portal`: run either site, both, or neither.

## Related Documentation

- [`unpackaged/post_billing_portal/README.md`](../post_billing_portal/README.md) — the Aura
  portal; structural precedent for naming, PII handling and portability fixes
- [`unpackaged/post_payments/`](../post_payments/) — the other LWR site in the repo
  (Payments Webhook), precedent for `CustomSite` patch/revert
- [Repository Integration Skill](../../.cursor/skills/repo-integration/SKILL.md)
