# Act 1: HubSpot lead to qualified opportunity

Part of the [Entirely demo](README.md). Covers process-flow use cases 01-05:
capture the lead, qualify it, convert it, record the customer and contact, and
manage regional deal ownership.

## Story

Kestrel Home & Living GmbH fills in a Censhare demo request in HubSpot. The lead
arrives in Salesforce with its marketing origin attached. Sales qualifies it,
and neither the lead nor the opportunity can move forward until the selling
company and territory are known. Kestrel is an Austrian account, but the deal
owner sits in Germany, so the opportunity needs a regional ownership approval
before it can leave Qualification.

## Click path (about 5 minutes)

1. Open the **Kestrel** lead. The Path shows **New**, with the HubSpot form and
   Censhare as the selling company.
2. Move to **Working** and fill in the need, budget and timing. The **Nurture in
   HubSpot** checkbox is the "not ready to buy" branch; mention it, don't tick it.
3. Click **Qualified** and **Mark Status as Complete**. It is blocked, asking
   for Territory. Set Territory to **Austria & CEE** and mark it again.
4. **Convert**. The opportunity opens in Qualification with Selling Company,
   Territory and Amount carried over, and the account shows Censhare as its
   selling company.
5. The highlights panel shows **Regional Status: Out of region - approval
   required**, because the owner's territory is Germany. Try moving to
   **Discovery**: it is blocked.
6. Click **Request Regional Approval**, add a comment and submit. Regional
   Status changes to **Out of region - awaiting approval**, and the request
   appears in the **Approvals** tab.
7. Open the request from the Approvals tab, choose **Approve** and submit.
   Regional Status changes to **Out of region - approved**.
8. Move to **Discovery**. It now succeeds.

## Setup

Once per org, after `prepare_rlm_org`:

```bash
sf project deploy start --source-dir unpackaged/post_entirely/flows \
  --source-dir unpackaged/post_entirely/quickActions \
  --source-dir unpackaged/post_entirely/groups --target-org Entirely
sf project deploy start --source-dir unpackaged/post_entirely --target-org Entirely
sf org assign permset --name RLM_Entirely --target-org Entirely
sf apex run --file scripts/apex/entirely/act1_setup_user.apex --target-org Entirely
```

Before each demo:

```bash
sf apex run --file scripts/apex/entirely/act1_reset.apex --target-org Entirely
```

Then make one change on the Lightning record page by hand, because the page is
not part of this bundle (see [Org-only changes](#org-only-changes)).

| Script | What it does |
| ------ | ------------ |
| `act1_setup_user.apex` | Sets your territory to Germany and adds you to the approver group |
| `act1_reset.apex` | Cancels any open approval, deletes the Kestrel records and re-creates the lead with Territory blank |
| `act1_verify.apex` | Drives the path through Apex and prints PASS/FAIL per check. Destructive; run the reset afterwards |

## What is built

### Data model

| Component | Purpose |
| --------- | ------- |
| `RLM_Entirely_Company` global value set | Censhare, Marmind, Facelift, Elaine, Epoq, Business OS |
| `RLM_Entirely_Territory` global value set | Germany, Austria & CEE, Switzerland, UK & Ireland, Nordics, Benelux |
| `LeadSource` standard value set | Adds **HubSpot** |
| `RLM_Selling_Company__c` on Lead, Opportunity, Account, Contract | Which group company sells or owns the relationship |
| `RLM_Territory__c` on Lead, Opportunity, User | The deal's territory, and the territory a user owns |
| `Lead.RLM_HubSpot_Form__c`, `RLM_HubSpot_Record_Id__c` | Marketing origin; the record id is an external id |
| `Lead.RLM_Customer_Need__c`, `RLM_Budget__c`, `RLM_Timing__c` | What the qualification conversation captures |
| `Lead.RLM_Nurture_In_HubSpot__c` | Not ready to buy; stays in HubSpot |
| `Opportunity.RLM_Owner_Territory__c` | Formula: the owner's territory |
| `Opportunity.RLM_Regional_Exception__c` | Formula: deal territory differs from the owner's |
| `Opportunity.RLM_Regional_Approval_Status__c` | Not Required, Pending, Approved, Rejected; written by the approval |
| `Opportunity.RLM_Regional_Status_Flag__c` | Formula: one readable verdict built from the two fields above |

### Process and rules

| Component | Purpose |
| --------- | ------- |
| `RLM_Entirely_Lead_Process`, `RLM_Entirely_Lead` record type | Trims lead statuses to New, Working, Qualified, Unqualified, Converted |
| `RLM_Entirely_Lead_Path`, `RLM_Entirely_Opportunity_Path` | Key fields and guidance per step |
| `RLM_Qualify_Requires_Company_Territory` | Blocks Qualified or Converted while either field is blank |
| `RLM_Stage_Requires_Company_Territory` | Blocks moving past Qualification while either field is blank |
| `RLM_Regional_Approval_Required` | Blocks moving past Qualification on an unapproved out-of-region deal |
| `LeadConvertSettings` | Maps the lead fields onto the opportunity and account |
| `RLM_Entirely_Lead_Budget_To_Amount` flow | Copies the lead's Budget into the opportunity's Amount at conversion |

### Approval

| Component | Purpose |
| --------- | ------- |
| `RLM_Entirely_Regional_Approval` flow | The Approval Orchestration: Pending, approval step, then Approved or Rejected |
| `RLM_Entirely_Submit_Regional_Approval` flow | Submitter screen; starts the orchestration |
| `RLM_Entirely_Evaluate_Regional_Approval` flow | The Approve / Reject screen the approver sees |
| `RLM_Entirely_Set_Opp_Approval_Status` flow | Background step writing the status back |
| `RLM_Entirely_Cancel_Approval_Submission` flow | Lets the reset cancel an open request |
| `RLM_Entirely_Sales_VP` public group | The approvers |
| `Opportunity.RLM_Submit_for_Approval` quick action | Labelled **Request Regional Approval**; opens the submitter screen |

### UI and access

| Component | Purpose |
| --------- | ------- |
| `RLM_Entirely_Opportunity`, `RLM_Entirely_Lead` compact layouts | Put the governance fields in the highlights panel |
| Layouts for Lead, Opportunity, Account, Contract | Add the fields. The Opportunity layout hides the standard Submit button and has no Approval History list |
| `RLM_Entirely` permission set | Field access and lead record type visibility; needed even by admins |

## Org-only changes

`RLM_Opportunity_Record_Page` is owned by UX assembly and uses Dynamic Actions,
so its buttons come from the page, not from the layout. Two changes were made
directly on the live page in App Builder:

- The standard **Submit** action is replaced by
  `Opportunity.RLM_Submit_for_Approval`.
- An **Approvals** tab holds the Approval Trace component and the Approval
  Workflow component, with `flowApiName` set to `RLM_Entirely_Regional_Approval`.

Running `assemble_and_deploy_ux` against the org undoes both. Redo them
afterwards.

## Design decisions

**Approval Orchestration, not a classic approval process.** Only orchestration
writes `ApprovalWorkItem` records, which is what the Approvals tab reads. It
also accepts a public group as approver; a classic Opportunity approval does
not, because Opportunity is not queue-enabled. The flows follow
`RLM_Quote_Smart_Approval` in `post_approvals` and reuse its
`RLM_AA_Submit_Approval` invocable.

**One working Submit button.** The standard Submit for Approval button and the
Approval History related list both drive the classic engine, and answer "No
applicable approval process was found". Both are removed, and the quick action
has a different label so it cannot be confused with them.

**A status flag next to the status.** Before submission the raw status reads
"Not Required" whether the deal is in region or out of region and unsubmitted.
`RLM_Regional_Status_Flag__c` folds in the exception and reports the six real
states. It is plain text rather than an `IMAGE()` formula so that it renders in
the highlights panel, list views and reports.

**Amount through a flow.** Lead conversion maps a custom field only onto
another custom field, so Budget cannot reach the standard Amount through
`LeadConvertSettings`. A record-triggered flow does it at conversion.

**Stage rules ignore inserts.** The rules fire only when someone changes the
stage on an existing record, so scripts that create opportunities at a later
stage, such as `scripts/build_quote_to_asset.py`, keep working. The lead rule
also applies at conversion because the org has **Require Validation for
Converted Leads** switched on; enable it in Lead Settings on any other org.

## Known issues

- **First deploy fails on the Opportunity layout** with *no QuickAction named
  RLM_Submit_for_Approval found*. Deploy `flows`, `quickActions` and `groups`
  first, as in Setup above.
- **Path deploy fails** with *Cannot create more than 1 Path per sobjectType and
  recordType*. The Metadata API will not overwrite an active Path. Delete the two
  `PathAssistant` records (`sf data delete record -t -s PathAssistant -i <id>`)
  and redeploy.
- **`MIXED_DML_OPERATION`** if user and group setup run in the same transaction
  as lead or opportunity changes. That is why `act1_setup_user.apex` is
  separate from the reset.
- **An open approval cannot be deleted or edited**, only cancelled, and only
  through the standard `cancelApprovalSubmission` action, which Apex cannot call.
  The reset therefore runs `RLM_Entirely_Cancel_Approval_Submission`.
- **Approve and reject cannot be scripted.** Orchestration completes a work item
  by running its screen flow, and there is no Apex equivalent of
  `Approval.process()`. Test them in the browser.
- **A retired classic process remains in the org.** `RLM_Entirely_Regional_Ownership`
  is inactive and no longer in the repo; Salesforce will not delete an approval
  process that has had submissions. Inactive is harmless.
