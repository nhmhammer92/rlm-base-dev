// Entirely demo, Act 2a: reset the Kestrel quoting state on an org with no Entirely
// metadata deployed. Deletes every quote on the Kestrel opportunity and puts the
// opportunity back into the state Act 2a starts from: Discovery, EUR, on the standard
// price book. Safe to run repeatedly.
//
// This is the metadata-free sibling of act2_reset.apex. That script also sets the Act 1
// fields (RLM_Selling_Company__c, RLM_Territory__c, RLM_Regional_Approval_Status__c),
// which only exist once unpackaged/post_entirely is deployed. Act 2a validates the
// catalog and standard pricing, neither of which needs them, so this script leaves them
// out and runs on a bare prepare_rlm_org build. Use act2_reset.apex instead once the
// bundle is deployed.

final String ACCOUNT_NAME = 'Kestrel Home & Living GmbH';
final String STAGE = 'Discovery';
final String CURRENCY_CODE = 'EUR';

List<Quote> oldQuotes = [SELECT Id FROM Quote WHERE Opportunity.Account.Name = :ACCOUNT_NAME];
if (!oldQuotes.isEmpty()) {
    delete oldQuotes;
}

List<Opportunity> opps = [
    SELECT Id, StageName, CurrencyIsoCode, Pricebook2Id
    FROM Opportunity
    WHERE Account.Name = :ACCOUNT_NAME
    ORDER BY CreatedDate DESC
];

Id standardPricebookId = [SELECT Id FROM Pricebook2 WHERE IsStandard = true LIMIT 1].Id;

// The standard Account and Contact duplicate rules match these records against the org's
// sample data and block the insert outright. These are known demo records being recreated
// deliberately, so save through the rule rather than around it by renaming.
Database.DMLOptions allowDuplicates = new Database.DMLOptions();
allowDuplicates.DuplicateRuleHeader.AllowSave = true;

if (opps.isEmpty()) {
    Account kestrel = new Account(
        Name = ACCOUNT_NAME,
        Industry = 'Retail',
        NumberOfEmployees = 850,
        BillingCity = 'Vienna',
        BillingCountry = 'Austria',
        Phone = '+43 1 2345678',
        // The whole Kestrel deal is quoted in EUR. A quote inherits its currency from the
        // account, so setting it only on the opportunity leaves quotes in the org default
        // — and a quote's currency cannot be changed once it has lines.
        CurrencyIsoCode = CURRENCY_CODE
    );
    Database.insert(kestrel, allowDuplicates);

    Contact anna = new Contact(
        AccountId = kestrel.Id,
        FirstName = 'Anna',
        LastName = 'Schulz',
        Title = 'Head of E-Commerce',
        Email = 'anna.schulz@kestrel-living.example.com',
        Phone = '+43 1 2345678'
    );
    Database.insert(anna, allowDuplicates);

    insert new Opportunity(
        AccountId = kestrel.Id,
        Name = ACCOUNT_NAME + ' - Censhare Cloud',
        StageName = STAGE,
        CloseDate = Date.today().addDays(60),
        CurrencyIsoCode = CURRENCY_CODE,
        Pricebook2Id = standardPricebookId,
        Amount = 60000,
        LeadSource = 'Other',
        OwnerId = UserInfo.getUserId(),
        Description = 'Replace a legacy content platform across 55 users, with translation, '
            + 'print production and headless APIs for the webshop.'
    );
    System.debug('Act 2a ready: built the Kestrel account and opportunity from scratch.');
} else {
    // A quote takes its currency from the account, so an account left in the org default
    // produces quotes Act 2a cannot price in EUR.
    Account acct = [SELECT Id, CurrencyIsoCode FROM Account WHERE Name = :ACCOUNT_NAME LIMIT 1];
    if (acct.CurrencyIsoCode != CURRENCY_CODE) {
        acct.CurrencyIsoCode = CURRENCY_CODE;
        update acct;
    }

    Opportunity opp = opps[0];
    opp.StageName = STAGE;
    opp.CurrencyIsoCode = CURRENCY_CODE;
    opp.Pricebook2Id = standardPricebookId;
    update opp;
    System.debug('Act 2a ready: opportunity ' + opp.Id + ' reset to ' + STAGE + ' in ' + CURRENCY_CODE);
}

System.debug('Deleted ' + oldQuotes.size() + ' quote(s).');
