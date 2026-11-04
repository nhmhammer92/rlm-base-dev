# post_billing_portal_lwr

Metadata for the LWR billing self-service site: the `Billing Self Service` Network, its Lightning
Web Runtime `DigitalExperienceBundle`, and its NavigationMenu. This site hosts the five billing
self-service components Salesforce added in Release 264 — Posted Invoices, Invoice Line Viewer,
Self-Service Payment Sheet, Self-Service Payment Confirmation and Manage Saved Payment Methods —
which appear in the Experience Builder palette only on LWR sites. The Aura Self-Service Billing
Portal in [`post_billing_portal`](post-billing-portal.md) cannot host them, so the two sites are
separate Networks that run independently.

The bundle is not populated yet: the components' internal names and attribute keys are neither
published nor queryable, so the site content has to come from an org retrieve rather than
hand-authored JSON. `billing_portal_lwr_deploy` therefore defaults to false, and
`prepare_billing_portal_lwr` creates and publishes a bare Build Your Own (LWR) site until the
round-trip is done.

Deploy through the `prepare_billing_portal_lwr` flow, step 6 of `prepare_billing_portal`. When
`billing`, `payments` and `billing_portal_lwr` are true, it creates and publishes the site. When
`billing_portal_lwr_deploy` is also true, it patches the Network email placeholder, deploys the
bundle with `deploy_post_billing_portal_lwr`, and reverts the placeholder before publishing.
Running the deploy task directly bypasses the required email patch.

See
[`unpackaged/post_billing_portal_lwr/README.md`](../../unpackaged/post_billing_portal_lwr/README.md)
for the retrieve-and-sanitize procedure, page and component settings, the naming-derivation rule,
PII handling and failure recovery, and required permission sets.
