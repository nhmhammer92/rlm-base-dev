// Entirely demo, Act 1: verification walk.
// Drives use cases 01-05 as far as Apex can and prints PASS/FAIL per check, then submits
// the regional approval. Destructive to the Kestrel records — run act1_reset.apex after.
//
// The approve/reject half is not here. Approval Orchestration completes a work item by
// running its screen flow; there is no Apex equivalent of the old Approval.process().
// This script leaves a live request behind for the browser to finish.

final String ACCOUNT_NAME = 'Kestrel Home & Living GmbH';
final String DEAL_TERRITORY = 'Austria & CEE';

// Simple assert helper. Anonymous Apex has no top-level types, so this is an inner class
// with instance methods.
public class Check {
    public List<String> lines = new List<String>();
    public Integer pass = 0;
    public Integer fail = 0;
    public void is(Boolean condition, String label) {
        if (condition) { pass++; lines.add('PASS  ' + label); }
        else { fail++; lines.add('FAIL  ' + label); }
    }
}
Check c = new Check();

// 1. Owner territory and approver membership are set up by the reset.
User me = [SELECT Id, RLM_Territory__c FROM User WHERE Id = :UserInfo.getUserId()];
c.is(me.RLM_Territory__c == 'Germany', '1a. Running user territory is Germany (is: ' + me.RLM_Territory__c + ')');

List<GroupMember> membership = [
    SELECT Id FROM GroupMember
    WHERE Group.DeveloperName = 'RLM_Entirely_Sales_VP' AND UserOrGroupId = :UserInfo.getUserId()
];
c.is(!membership.isEmpty(), '1b. Running user is in the RLM_Entirely_Sales_VP approver group');

// 2. The inbound lead carries its HubSpot origin and qualification data.
Lead lead = [
    SELECT Id, Status, LeadSource, RLM_Selling_Company__c, RLM_Territory__c,
           RLM_HubSpot_Form__c, RLM_HubSpot_Record_Id__c, RLM_Customer_Need__c,
           RLM_Budget__c, RLM_Timing__c
    FROM Lead WHERE Company = :ACCOUNT_NAME AND IsConverted = false LIMIT 1
];
c.is(lead.LeadSource == 'HubSpot', '2a. Lead source is HubSpot (is: ' + lead.LeadSource + ')');
c.is(lead.RLM_HubSpot_Record_Id__c != null, '2b. HubSpot record id captured');
c.is(lead.RLM_Budget__c != null && lead.RLM_Timing__c != null, '2c. Budget and timing captured');
c.is(lead.RLM_Territory__c == null, '2d. Territory starts blank, as the demo expects');

// 3. Qualifying without a territory is blocked.
try {
    update new Lead(Id = lead.Id, Status = 'Qualified');
    c.is(false, '3. Qualify without territory is blocked');
} catch (DmlException e) {
    c.is(e.getMessage().contains('before qualifying'), '3. Qualify without territory is blocked');
}

// 4. Fill the territory, then convert.
update new Lead(Id = lead.Id, RLM_Territory__c = DEAL_TERRITORY, Status = 'Qualified');

Database.LeadConvert lc = new Database.LeadConvert();
lc.setLeadId(lead.Id);
lc.setConvertedStatus('Converted');
lc.setDoNotCreateOpportunity(false);
lc.setOpportunityName(ACCOUNT_NAME + ' - Censhare Platform');
Database.LeadConvertResult lcr = Database.convertLead(lc);
c.is(lcr.isSuccess(), '4a. Lead converts');

Account acct = [SELECT Id, RLM_Selling_Company__c FROM Account WHERE Id = :lcr.getAccountId()];
c.is(acct.RLM_Selling_Company__c == 'Censhare', '4b. Selling Company carried to the account (is: ' + acct.RLM_Selling_Company__c + ')');

Opportunity opp = [
    SELECT Id, Name, StageName, Amount, RLM_Selling_Company__c, RLM_Territory__c,
           RLM_Owner_Territory__c, RLM_Regional_Exception__c, RLM_Regional_Approval_Status__c
    FROM Opportunity WHERE Id = :lcr.getOpportunityId()
];
c.is(opp.RLM_Selling_Company__c == 'Censhare' && opp.RLM_Territory__c == DEAL_TERRITORY,
    '4c. Selling Company and Territory carried to the opportunity');
c.is(opp.Amount == lead.RLM_Budget__c,
    '4d. Budget flowed into Amount (expected ' + lead.RLM_Budget__c + ', is ' + opp.Amount + ')');

// 5. The territory mismatch raises the regional exception.
c.is(opp.RLM_Owner_Territory__c == 'Germany', '5a. Owner Territory formula resolves (is: ' + opp.RLM_Owner_Territory__c + ')');
c.is(opp.RLM_Regional_Exception__c == true, '5b. Regional exception is true for an out-of-region deal');
c.is(opp.RLM_Regional_Approval_Status__c == 'Not Required', '5c. Approval status starts at Not Required (is: ' + opp.RLM_Regional_Approval_Status__c + ')');

// 6. Advancing the stage is blocked until the exception is approved.
try {
    update new Opportunity(Id = opp.Id, StageName = 'Discovery');
    c.is(false, '6. Stage change blocked pending regional approval');
} catch (DmlException e) {
    c.is(e.getMessage().contains('regional ownership approval'), '6. Stage change blocked pending regional approval');
}

// 7. An opportunity created by the API at a later stage is untouched by either rule.
// Act 7 builds quotes this way, so the guard matters.
Opportunity apiOpp = new Opportunity(
    Name = 'Entirely verify - API created',
    AccountId = acct.Id,
    StageName = 'Proposal/Quote',
    CloseDate = Date.today().addDays(60)
);
try {
    insert apiOpp;
    c.is(true, '7. API-created opportunity at Proposal/Quote is unaffected');
    delete apiOpp;
} catch (DmlException e) {
    c.is(false, '7. API-created opportunity at Proposal/Quote is unaffected -- ' + e.getMessage());
}

// 8. Start the orchestration. Its steps run asynchronously, so the work item will not
// exist yet in this transaction — check for it in a separate call.
RLM_AA_Submit_Approval.svcParameter p = new RLM_AA_Submit_Approval.svcParameter();
p.flowName = 'RLM_Entirely_Regional_Approval';
p.recordId = opp.Id;
p.comments = 'Kestrel is an Austrian account owned out of Germany.';
try {
    RLM_AA_Submit_Approval.callFlow(new List<RLM_AA_Submit_Approval.svcParameter>{ p });
    c.is(true, '8. Regional approval orchestration started');
} catch (Exception e) {
    c.is(false, '8. Regional approval orchestration started -- ' + e.getMessage());
}

for (String line : c.lines) { System.debug(LoggingLevel.ERROR, line); }
System.debug(LoggingLevel.ERROR, '=== ' + c.pass + ' passed, ' + c.fail + ' failed ===');
System.debug(LoggingLevel.ERROR, 'Opportunity under approval: ' + opp.Id);
