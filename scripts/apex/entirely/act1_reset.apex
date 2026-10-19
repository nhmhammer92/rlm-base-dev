// Entirely demo, Act 1: reset the Kestrel lead.
// Deletes any Kestrel records left over from an earlier run, then re-creates the inbound
// HubSpot lead owned by the running user. Safe to run repeatedly — run it before each demo.
//
// Territory is deliberately left blank. Filling it in with Austria & CEE during the demo
// is what makes the deal differ from the owner's territory and so triggers the regional
// ownership approval. Run act1_setup_user.apex once first to set that owner territory.

final String ACCOUNT_NAME = 'Kestrel Home & Living GmbH';
final String CONTACT_LAST_NAME = 'Schulz';

// Step 1: drop any approval still in flight, so a re-run after a half-finished demo
// does not leave a stale work item sitting in the Approvals tab.
List<Opportunity> oldOpps = [SELECT Id FROM Opportunity WHERE Account.Name = :ACCOUNT_NAME];
if (!oldOpps.isEmpty()) {
    // RelatedRecordId is polymorphic, so bind a materialised set rather than semi-joining.
    Set<Id> oppIds = new Map<Id, Opportunity>(oldOpps).keySet();
    List<ApprovalSubmission> submissions = [
        SELECT Id, Status FROM ApprovalSubmission
        WHERE RelatedRecordId IN :oppIds AND Status = 'InProgress'
    ];
    // An active submission cannot be deleted or edited directly — it has to be cancelled
    // through the standard invocable action, which only a flow can reach.
    for (ApprovalSubmission submission : submissions) {
        Flow.Interview.createInterview(
            'RLM_Entirely_Cancel_Approval_Submission',
            new Map<String, Object>{ 'approvalSubmissionId' => submission.Id }
        ).start();
    }
    if (!submissions.isEmpty()) {
        for (Database.DeleteResult dr : Database.delete(
                [SELECT Id FROM ApprovalSubmission WHERE Id IN :submissions], false)) {
            if (!dr.isSuccess()) {
                System.debug(LoggingLevel.ERROR, 'Could not delete approval submission: ' + dr.getErrors());
            }
        }
    }
}

// Step 2: remove the converted records from a previous run, child before parent.
if (!oldOpps.isEmpty()) {
    delete oldOpps;
}

List<Contact> oldContacts = [SELECT Id FROM Contact WHERE Account.Name = :ACCOUNT_NAME];
if (!oldContacts.isEmpty()) {
    delete oldContacts;
}

List<Account> oldAccounts = [SELECT Id FROM Account WHERE Name = :ACCOUNT_NAME];
if (!oldAccounts.isEmpty()) {
    delete oldAccounts;
}

// Step 3: remove the lead itself. Converted leads are excluded from the standard list views
// but still exist, so match on both converted and unconverted.
List<Lead> oldLeads = [SELECT Id FROM Lead WHERE Company = :ACCOUNT_NAME AND LastName = :CONTACT_LAST_NAME];
if (!oldLeads.isEmpty()) {
    delete oldLeads;
}

// Step 4: re-create the inbound lead.
Id entirelyLeadRtId = Schema.SObjectType.Lead.getRecordTypeInfosByDeveloperName()
    .get('RLM_Entirely_Lead')
    .getRecordTypeId();

Lead kestrel = new Lead(
    RecordTypeId = entirelyLeadRtId,
    FirstName = 'Anna',
    LastName = CONTACT_LAST_NAME,
    Title = 'Head of E-Commerce',
    Company = ACCOUNT_NAME,
    Status = 'New',
    LeadSource = 'HubSpot',
    Industry = 'Retail',
    NumberOfEmployees = 850,
    Email = 'anna.schulz@kestrel-living.example.com',
    Phone = '+43 1 2345678',
    City = 'Vienna',
    Country = 'Austria',
    OwnerId = UserInfo.getUserId(),
    // Act 2 quotes this deal in EUR. The currency carries through conversion, so it has
    // to be right on the lead — an opportunity in the org's default currency cannot be
    // switched once quote lines exist.
    CurrencyIsoCode = 'EUR',
    RLM_Selling_Company__c = 'Censhare',
    RLM_HubSpot_Form__c = 'Censhare - Request a demo',
    RLM_HubSpot_Record_Id__c = 'HS-104872',
    RLM_Customer_Need__c = 'Replace a legacy content platform across 55 users, with translation, '
        + 'print production and headless APIs for the webshop.',
    RLM_Budget__c = 60000,
    RLM_Timing__c = 'Next quarter',
    Description = 'HubSpot form: Censhare - Request a demo. ' +
        'Looking to replace a legacy content platform across 55 users, with translation, ' +
        'print production and headless APIs.'
);
insert kestrel;

System.debug('Kestrel lead ready: ' + kestrel.Id);
