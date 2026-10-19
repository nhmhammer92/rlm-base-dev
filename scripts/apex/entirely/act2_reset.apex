// Entirely demo, Act 2: reset the Kestrel quoting state.
// Deletes every quote on the Kestrel opportunity and puts the opportunity back into the
// state Act 2 starts from: Discovery, EUR, on the standard price book. Safe to run
// repeatedly — run it before each demo.
//
// Act 2 can be rehearsed without replaying Act 1: if the opportunity is missing entirely,
// this creates the account, contact and opportunity directly. Running act1_reset.apex
// afterwards still works, because that script deletes these records first.

final String ACCOUNT_NAME = 'Kestrel Home & Living GmbH';
final String SELLING_COMPANY = 'Censhare';
final String TERRITORY = 'Austria & CEE';
final String STAGE = 'Discovery';
final String CURRENCY_CODE = 'EUR';

// Step 1: delete the quotes. Quote lines cascade with their quote, so the quote is the
// only delete needed. Act 2 is rehearsed repeatedly, so a demo typically leaves several
// behind, including the CS-02 clone.
List<Quote> oldQuotes = [SELECT Id FROM Quote WHERE Opportunity.Account.Name = :ACCOUNT_NAME];
if (!oldQuotes.isEmpty()) {
    delete oldQuotes;
}

// Step 2: find — or build — the opportunity Act 2 quotes against.
List<Opportunity> opps = [
    SELECT Id, StageName, CurrencyIsoCode, Pricebook2Id,
           RLM_Selling_Company__c, RLM_Territory__c
    FROM Opportunity
    WHERE Account.Name = :ACCOUNT_NAME
    ORDER BY CreatedDate DESC
];

Id standardPricebookId = [SELECT Id FROM Pricebook2 WHERE IsStandard = true LIMIT 1].Id;

// The standard Account and Contact duplicate rules match these records against the
// org's sample data and block the insert outright. These are known demo records being
// recreated deliberately, so save through the rule rather than around it by renaming.
Database.DMLOptions allowDuplicates = new Database.DMLOptions();
allowDuplicates.DuplicateRuleHeader.AllowSave = true;

if (opps.isEmpty()) {
    // No Act 1 run in this org. Build the converted shape directly.
    Account kestrel = new Account(
        Name = ACCOUNT_NAME,
        Industry = 'Retail',
        NumberOfEmployees = 850,
        BillingCity = 'Vienna',
        BillingCountry = 'Austria',
        Phone = '+43 1 2345678',
        // The whole Kestrel deal is quoted in EUR. A quote inherits its currency from
        // the account, so setting it only on the opportunity leaves quotes in the org
        // default — and a quote's currency cannot be changed once it has lines.
        CurrencyIsoCode = CURRENCY_CODE,
        RLM_Selling_Company__c = SELLING_COMPANY
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
        LeadSource = 'HubSpot',
        OwnerId = UserInfo.getUserId(),
        RLM_Selling_Company__c = SELLING_COMPANY,
        RLM_Territory__c = TERRITORY,
        Description = 'Replace a legacy content platform across 55 users, with translation, '
            + 'print production and headless APIs for the webshop.'
    );
    System.debug('Act 2 ready: built the Kestrel account and opportunity from scratch.');
} else {
    // Act 1 leaves the opportunity in Qualification and in the org's default currency.
    // Act 2 quotes in EUR, and the currency cannot be changed once quote lines exist —
    // which is why step 1 clears the quotes before this runs.
    // Bring the account along: a quote takes its currency from the account, so an
    // account left in the org default produces quotes Act 2 cannot price in EUR.
    Account acct = [SELECT Id, CurrencyIsoCode FROM Account WHERE Name = :ACCOUNT_NAME LIMIT 1];
    if (acct.CurrencyIsoCode != CURRENCY_CODE) {
        acct.CurrencyIsoCode = CURRENCY_CODE;
        update acct;
    }

    Opportunity opp = opps[0];
    opp.StageName = STAGE;
    opp.CurrencyIsoCode = CURRENCY_CODE;
    opp.Pricebook2Id = standardPricebookId;
    opp.RLM_Selling_Company__c = SELLING_COMPANY;
    opp.RLM_Territory__c = TERRITORY;
    // Kestrel is an Austria & CEE deal owned from Germany, so it carries a regional
    // exception and cannot leave Qualification until that approval is granted. Act 1
    // ends with it granted, which is the state Act 2 starts from.
    opp.RLM_Regional_Approval_Status__c = 'Approved';
    update opp;
    System.debug('Act 2 ready: opportunity ' + opp.Id + ' reset to ' + STAGE + ' in ' + CURRENCY_CODE);
}

System.debug('Deleted ' + oldQuotes.size() + ' quote(s).');
