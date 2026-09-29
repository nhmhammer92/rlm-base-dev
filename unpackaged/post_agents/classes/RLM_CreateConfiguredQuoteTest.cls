/**
 * Unit tests for RLM_CreateConfiguredQuote. The Place Sales Transaction call is replaced by a
 * stub through the PstInvoker seam — the managed executor cannot run in a test context — so the
 * assertions cover what this class is responsible for: selling-model resolution, the graph it
 * builds (dates, BillingFrequency, PeriodBoundary, discounts), component-discount targeting,
 * and the failure/orphan paths.
 */
@isTest
private class RLM_CreateConfiguredQuoteTest {

    private static Integer idCounter = 0;

    private static Id fakeId(Schema.SObjectType sobjectType) {
        idCounter++;
        String suffix = String.valueOf(idCounter);
        return Id.valueOf(sobjectType.getDescribe().getKeyPrefix() + '0'.repeat(12 - suffix.length()) + suffix);
    }

    private class StubInvoker implements RLM_CreateConfiguredQuote.PstInvoker {
        RLM_CreateConfiguredQuote.PstResult result;
        List<List<RLM_CreateConfiguredQuote.GraphRecord>> calls =
            new List<List<RLM_CreateConfiguredQuote.GraphRecord>>();
        List<Boolean> configuratorFlags = new List<Boolean>();

        StubInvoker(RLM_CreateConfiguredQuote.PstResult result) {
            this.result = result;
        }

        public RLM_CreateConfiguredQuote.PstResult place(
            List<RLM_CreateConfiguredQuote.GraphRecord> records,
            Boolean runConfigurator
        ) {
            calls.add(records);
            configuratorFlags.add(runConfigurator);
            return result;
        }
    }

    private static RLM_CreateConfiguredQuote.PstResult successResult(Id quoteId) {
        RLM_CreateConfiguredQuote.PstResult result = new RLM_CreateConfiguredQuote.PstResult();
        result.isSuccess = true;
        result.quoteId = quoteId;
        return result;
    }

    /** Product with two selling models (Term Monthly + Term Annual) priced on the standard book. */
    private static Map<String, PricebookEntry> setupCatalog(String sku) {
        Product2 product = new Product2(Name = sku, StockKeepingUnit = sku, IsActive = true);
        insert product;
        List<ProductSellingModel> models = new List<ProductSellingModel>{
            new ProductSellingModel(
                Name = 'Term Monthly', SellingModelType = 'TermDefined', PricingTermUnit = 'Months',
                PricingTerm = 1, Status = 'Active'
            ),
            new ProductSellingModel(
                Name = 'Term Annual', SellingModelType = 'TermDefined', PricingTermUnit = 'Annual',
                PricingTerm = 1, Status = 'Active'
            )
        };
        insert models;
        // A PricebookEntry is refused unless the product offers that selling model.
        insert new List<ProductSellingModelOption>{
            new ProductSellingModelOption(
                Product2Id = product.Id, ProductSellingModelId = models[0].Id, IsDefault = true
            ),
            new ProductSellingModelOption(
                Product2Id = product.Id, ProductSellingModelId = models[1].Id, IsDefault = false
            )
        };
        Id pricebookId = Test.getStandardPricebookId();
        List<PricebookEntry> entries = new List<PricebookEntry>{
            new PricebookEntry(
                Pricebook2Id = pricebookId, Product2Id = product.Id, UnitPrice = 30,
                IsActive = true, ProductSellingModelId = models[0].Id
            ),
            new PricebookEntry(
                Pricebook2Id = pricebookId, Product2Id = product.Id, UnitPrice = 360,
                IsActive = true, ProductSellingModelId = models[1].Id
            )
        };
        insert entries;
        return new Map<String, PricebookEntry>{
            'Months' => entries[0],
            'Annual' => entries[1]
        };
    }

    private static Quote setupQuote(Id pricebookId) {
        Account account = new Account(Name = 'Configured Quote Test');
        insert account;
        Opportunity opportunity = new Opportunity(
            Name = 'Configured Quote Opp', AccountId = account.Id,
            StageName = 'Prospecting', CloseDate = Date.today().addDays(30)
        );
        insert opportunity;
        Quote quote = new Quote(
            Name = 'Configured Quote', Pricebook2Id = pricebookId,
            OpportunityId = opportunity.Id, Status = 'Draft'
        );
        insert quote;
        return quote;
    }

    @isTest
    static void emptyInputReturnsFailure() {
        List<RLM_CreateConfiguredQuote.Output> outputs = RLM_CreateConfiguredQuote.execute(null);
        Assert.areEqual(1, outputs.size());
        Assert.isFalse(outputs[0].success);
        Assert.areEqual('No input provided.', outputs[0].errorMessage);
    }

    @isTest
    static void invalidIdsAndMissingFieldsReturnFailures() {
        RLM_CreateConfiguredQuote.Input badAccount = new RLM_CreateConfiguredQuote.Input();
        badAccount.accountId = 'not-an-id';
        badAccount.quoteName = 'Q';
        badAccount.linesJson = '[]';

        RLM_CreateConfiguredQuote.Input missingName = new RLM_CreateConfiguredQuote.Input();
        missingName.accountId = fakeId(Account.getSObjectType());
        missingName.linesJson = '[]';

        RLM_CreateConfiguredQuote.Input badOpportunity = new RLM_CreateConfiguredQuote.Input();
        badOpportunity.accountId = fakeId(Account.getSObjectType());
        badOpportunity.quoteName = 'Q';
        badOpportunity.opportunityId = 'nope';
        badOpportunity.linesJson = '[{"sku":"X"}]';

        List<RLM_CreateConfiguredQuote.Output> outputs = RLM_CreateConfiguredQuote.execute(
            new List<RLM_CreateConfiguredQuote.Input>{ badAccount, missingName, badOpportunity }
        );

        Assert.isTrue(outputs[0].errorMessage.contains('Invalid Account Id'));
        Assert.areEqual('Quote Name is required.', outputs[1].errorMessage);
        Assert.isTrue(outputs[2].errorMessage.contains('Invalid Opportunity Id'));
        for (RLM_CreateConfiguredQuote.Output out : outputs) {
            Assert.isFalse(out.success);
            Assert.isFalse(out.isOrphanQuote);
        }
    }

    @isTest
    static void parseLinesReadsQuantitiesDiscountsAndComponents() {
        List<RLM_CreateConfiguredQuote.LineSpec> specs = RLM_CreateConfiguredQuote.parseLines(
            '[{"sku":"QB-COMPLETE","quantity":20,"sellingModelType":"Term","pricingTermUnit":"Months",' +
            '"termMonths":12,"componentDiscounts":[{"sku":"qb-db","discountPercent":2}]},' +
            '{"productCode":"TEST-SUB","discountPercent":5}]'
        );
        Assert.areEqual(2, specs.size());
        Assert.areEqual('QB-COMPLETE', specs[0].sku);
        Assert.areEqual(20, specs[0].quantity.intValue());
        Assert.areEqual(12, specs[0].termMonths);
        Assert.areEqual(2, specs[0].componentDiscounts.get('QB-DB').intValue());
        // Missing quantity defaults to 1; productCode is accepted as a sku alias.
        Assert.areEqual('TEST-SUB', specs[1].sku);
        Assert.areEqual(1, specs[1].quantity.intValue());
        Assert.areEqual(5, specs[1].discountPercent.intValue());
    }

    @isTest
    static void parseLinesRejectsMalformedInput() {
        Map<String, String> cases = new Map<String, String>{
            '' => 'Lines JSON is required.',
            '{"sku":"X"}' => 'must be a JSON array',
            '[{"quantity":1}]' => 'needs a "sku"',
            '["X"]' => 'must be a JSON object',
            '[]' => 'contains no lines',
            'not json' => 'not valid JSON'
        };
        for (String payload : cases.keySet()) {
            try {
                RLM_CreateConfiguredQuote.parseLines(payload);
                Assert.fail('Expected a failure for: ' + payload);
            } catch (Exception e) {
                Assert.isTrue(
                    e.getMessage().contains(cases.get(payload)),
                    'Unexpected message for ' + payload + ': ' + e.getMessage()
                );
            }
        }
    }

    @isTest
    static void startDateDefaultsToTodayAndRejectsBadFormat() {
        Assert.areEqual(Date.today(), RLM_CreateConfiguredQuote.parseStartDate(null));
        Assert.areEqual(Date.newInstance(2026, 10, 1), RLM_CreateConfiguredQuote.parseStartDate('2026-10-01'));
        try {
            RLM_CreateConfiguredQuote.parseStartDate('October 1st');
            Assert.fail('Expected a failure for an unparseable date');
        } catch (Exception e) {
            Assert.isTrue(e.getMessage().contains('yyyy-MM-dd'));
        }
    }

    @isTest
    static void normalisedTypeAcceptsShorthands() {
        Assert.areEqual('TermDefined', RLM_CreateConfiguredQuote.normalisedType('Term'));
        Assert.areEqual('TermDefined', RLM_CreateConfiguredQuote.normalisedType('term-defined'));
        Assert.areEqual('OneTime', RLM_CreateConfiguredQuote.normalisedType('One-Time'));
        Assert.areEqual('Evergreen', RLM_CreateConfiguredQuote.normalisedType(' evergreen '));
    }

    @isTest
    static void resolvePricebookEntriesMatchesRequestedSellingModel() {
        Map<String, PricebookEntry> catalog = setupCatalog('RLM-TEST-SUB');
        List<RLM_CreateConfiguredQuote.LineSpec> specs = RLM_CreateConfiguredQuote.parseLines(
            '[{"sku":"RLM-TEST-SUB","sellingModelType":"TermDefined","pricingTermUnit":"Months"}]'
        );
        Map<String, PricebookEntry> resolved = RLM_CreateConfiguredQuote.resolvePricebookEntries(
            specs, Test.getStandardPricebookId(), UserInfo.getDefaultCurrency()
        );
        Assert.areEqual(catalog.get('Months').Id, resolved.get('RLM-TEST-SUB').Id);
    }

    @isTest
    static void resolvePricebookEntriesReportsAmbiguityAndMisses() {
        setupCatalog('RLM-TEST-SUB');
        // No term unit given and the product has two term models: the caller must choose.
        try {
            RLM_CreateConfiguredQuote.resolvePricebookEntries(
                RLM_CreateConfiguredQuote.parseLines('[{"sku":"RLM-TEST-SUB","sellingModelType":"TermDefined"}]'),
                Test.getStandardPricebookId(),
                UserInfo.getDefaultCurrency()
            );
            Assert.fail('Expected an ambiguity failure');
        } catch (Exception e) {
            Assert.isTrue(e.getMessage().contains('Several selling models match'), e.getMessage());
            Assert.isTrue(e.getMessage().contains('Term Monthly'), 'Options should be listed: ' + e.getMessage());
        }
        // A model the product does not offer reports the ones it does.
        try {
            RLM_CreateConfiguredQuote.resolvePricebookEntries(
                RLM_CreateConfiguredQuote.parseLines('[{"sku":"RLM-TEST-SUB","sellingModelType":"Evergreen"}]'),
                Test.getStandardPricebookId(),
                UserInfo.getDefaultCurrency()
            );
            Assert.fail('Expected an unmatched-model failure');
        } catch (Exception e) {
            Assert.isTrue(e.getMessage().contains('No selling model matches'), e.getMessage());
        }
        // Unknown SKU.
        try {
            RLM_CreateConfiguredQuote.resolvePricebookEntries(
                RLM_CreateConfiguredQuote.parseLines('[{"sku":"RLM-NO-SUCH-SKU"}]'),
                Test.getStandardPricebookId(),
                UserInfo.getDefaultCurrency()
            );
            Assert.fail('Expected a missing-price-book-entry failure');
        } catch (Exception e) {
            Assert.isTrue(e.getMessage().contains('No active price book entry'), e.getMessage());
        }
    }

    @isTest
    static void createGraphCarriesTermDatesAndBillingFields() {
        setupCatalog('RLM-TEST-SUB');
        List<RLM_CreateConfiguredQuote.LineSpec> specs = RLM_CreateConfiguredQuote.parseLines(
            '[{"sku":"RLM-TEST-SUB","quantity":20,"sellingModelType":"TermDefined",' +
            '"pricingTermUnit":"Months","termMonths":12,"discountPercent":5}]'
        );
        Map<String, PricebookEntry> resolved = RLM_CreateConfiguredQuote.resolvePricebookEntries(
            specs, Test.getStandardPricebookId(), UserInfo.getDefaultCurrency()
        );
        Id accountId = fakeId(Account.getSObjectType());

        List<RLM_CreateConfiguredQuote.GraphRecord> records = RLM_CreateConfiguredQuote.buildCreateGraph(
            'My Quote', accountId, null, Test.getStandardPricebookId(), specs, resolved,
            Date.newInstance(2026, 10, 1)
        );

        Assert.areEqual(2, records.size());
        Map<String, Object> header = records[0].fields;
        Assert.areEqual('Quote', records[0].objectName);
        Assert.areEqual(accountId, header.get('QuoteAccountId'));
        Assert.isFalse(header.containsKey('AccountId'), 'AccountId is not writable on the graph');

        Map<String, Object> line = records[1].fields;
        Assert.areEqual('@{refQuote.id}', line.get('QuoteId'));
        Assert.areEqual(resolved.get('RLM-TEST-SUB').Id, line.get('PricebookEntryId'));
        Assert.areEqual(20, ((Decimal) line.get('Quantity')).intValue());
        Assert.areEqual(5, ((Decimal) line.get('Discount')).intValue());
        Assert.areEqual('2026-10-01', line.get('StartDate'));
        Assert.areEqual('2027-09-30', line.get('EndDate'));
        Assert.areEqual('Monthly', line.get('BillingFrequency'));
        Assert.areEqual('Anniversary', line.get('PeriodBoundary'));
        Assert.isFalse(
            line.containsKey('ProductSellingModelId'),
            'ProductSellingModelId is FLS-protected and must never be sent'
        );
    }

    @isTest
    static void createGraphDefaultsTermToTwelveMonths() {
        setupCatalog('RLM-TEST-SUB');
        List<RLM_CreateConfiguredQuote.LineSpec> specs = RLM_CreateConfiguredQuote.parseLines(
            '[{"sku":"RLM-TEST-SUB","sellingModelType":"TermDefined","pricingTermUnit":"Annual"}]'
        );
        Map<String, PricebookEntry> resolved = RLM_CreateConfiguredQuote.resolvePricebookEntries(
            specs, Test.getStandardPricebookId(), UserInfo.getDefaultCurrency()
        );
        List<RLM_CreateConfiguredQuote.GraphRecord> records = RLM_CreateConfiguredQuote.buildCreateGraph(
            'My Quote', fakeId(Account.getSObjectType()), null, Test.getStandardPricebookId(),
            specs, resolved, Date.newInstance(2026, 10, 1)
        );
        Assert.areEqual('2027-09-30', records[1].fields.get('EndDate'));
        Assert.areEqual('Annual', records[1].fields.get('BillingFrequency'));
    }

    @isTest
    static void componentDiscountGraphTargetsTheChildLineUnderItsBundle() {
        Id bundleLineId = fakeId(QuoteLineItem.getSObjectType());
        Id componentLineId = fakeId(QuoteLineItem.getSObjectType());
        Id otherLineId = fakeId(QuoteLineItem.getSObjectType());
        Id quoteId = fakeId(Quote.getSObjectType());

        List<QuoteLineItem> lines = new List<QuoteLineItem>{
            lineWithSku(bundleLineId, 'QB-COMPLETE'),
            lineWithSku(componentLineId, 'QB-DB'),
            lineWithSku(otherLineId, 'QB-DB')
        };
        Map<Id, String> parentSku = new Map<Id, String>{
            componentLineId => 'QB-COMPLETE',
            otherLineId => 'SOME-OTHER-BUNDLE'
        };
        List<RLM_CreateConfiguredQuote.LineSpec> specs = RLM_CreateConfiguredQuote.parseLines(
            '[{"sku":"QB-COMPLETE","componentDiscounts":[{"sku":"QB-DB","discountPercent":2}]}]'
        );

        List<RLM_CreateConfiguredQuote.GraphRecord> records =
            RLM_CreateConfiguredQuote.buildComponentDiscountGraph(quoteId, specs, lines, parentSku);

        // Quote header PATCH + exactly the one matching component line.
        Assert.areEqual(2, records.size());
        Assert.areEqual('Quote', records[0].objectName);
        Assert.areEqual(quoteId, records[0].recordId);
        Assert.areEqual('PATCH', records[1].method);
        Assert.areEqual(componentLineId, records[1].recordId);
        Assert.areEqual(2, ((Decimal) records[1].fields.get('Discount')).intValue());
    }

    @isTest
    static void componentDiscountGraphIsEmptyWithoutRequests() {
        List<RLM_CreateConfiguredQuote.GraphRecord> records =
            RLM_CreateConfiguredQuote.buildComponentDiscountGraph(
                fakeId(Quote.getSObjectType()),
                RLM_CreateConfiguredQuote.parseLines('[{"sku":"QB-COMPLETE"}]'),
                new List<QuoteLineItem>(),
                new Map<Id, String>()
            );
        Assert.isTrue(records.isEmpty());
    }

    @isTest
    static void successfulRunReportsQuoteAndRunsConfigurator() {
        setupCatalog('RLM-TEST-SUB');
        Quote quote = setupQuote(Test.getStandardPricebookId());
        StubInvoker stub = new StubInvoker(successResult(quote.Id));
        RLM_CreateConfiguredQuote.testInvoker = stub;

        RLM_CreateConfiguredQuote.Input in0 = new RLM_CreateConfiguredQuote.Input();
        in0.accountId = [SELECT AccountId FROM Opportunity WHERE Id = :quote.OpportunityId].AccountId;
        in0.quoteName = 'Stubbed Quote';
        in0.startDate = '2026-10-01';
        in0.linesJson = '[{"sku":"RLM-TEST-SUB","quantity":20,"sellingModelType":"TermDefined","pricingTermUnit":"Months"}]';

        List<RLM_CreateConfiguredQuote.Output> outputs = RLM_CreateConfiguredQuote.execute(
            new List<RLM_CreateConfiguredQuote.Input>{ in0 }
        );

        Assert.isTrue(outputs[0].success, 'Unexpected failure: ' + outputs[0].errorMessage);
        Assert.areEqual(quote.Id, outputs[0].quoteId);
        Assert.isFalse(outputs[0].isOrphanQuote);
        Assert.areEqual('[]', outputs[0].linesSummaryJson, 'Stub creates no lines');
        Assert.areEqual(1, stub.calls.size(), 'No component discounts means a single call');
        Assert.isTrue(stub.configuratorFlags[0], 'The create call must run the configurator');
    }

    @isTest
    static void failedPlaceReportsOrphanQuote() {
        setupCatalog('RLM-TEST-SUB');
        Account account = new Account(Name = 'Orphan Test');
        insert account;
        RLM_CreateConfiguredQuote.PstResult failed = new RLM_CreateConfiguredQuote.PstResult();
        failed.isSuccess = false;
        failed.quoteId = fakeId(Quote.getSObjectType());
        failed.errorText = 'INVALID_PERIOD_BOUNDARY';
        RLM_CreateConfiguredQuote.testInvoker = new StubInvoker(failed);

        RLM_CreateConfiguredQuote.Input in0 = new RLM_CreateConfiguredQuote.Input();
        in0.accountId = account.Id;
        in0.quoteName = 'Doomed Quote';
        in0.linesJson = '[{"sku":"RLM-TEST-SUB","sellingModelType":"TermDefined","pricingTermUnit":"Months"}]';

        List<RLM_CreateConfiguredQuote.Output> outputs = RLM_CreateConfiguredQuote.execute(
            new List<RLM_CreateConfiguredQuote.Input>{ in0 }
        );

        Assert.isFalse(outputs[0].success);
        Assert.isTrue(outputs[0].isOrphanQuote, 'A failed place still leaves a quote header');
        Assert.areEqual(failed.quoteId, outputs[0].quoteId);
        Assert.isTrue(outputs[0].errorMessage.contains('INVALID_PERIOD_BOUNDARY'));
    }

    @isTest
    static void unknownAccountReportsFailure() {
        setupCatalog('RLM-TEST-SUB');
        RLM_CreateConfiguredQuote.Input in0 = new RLM_CreateConfiguredQuote.Input();
        in0.accountId = fakeId(Account.getSObjectType());
        in0.quoteName = 'No Account';
        in0.linesJson = '[{"sku":"RLM-TEST-SUB","sellingModelType":"TermDefined","pricingTermUnit":"Months"}]';

        List<RLM_CreateConfiguredQuote.Output> outputs = RLM_CreateConfiguredQuote.execute(
            new List<RLM_CreateConfiguredQuote.Input>{ in0 }
        );

        Assert.isFalse(outputs[0].success);
        Assert.isTrue(outputs[0].errorMessage.contains('Account not found'), outputs[0].errorMessage);
    }

    /** In-memory quote line with a Product2 relationship, which only JSON deserialisation allows. */
    private static QuoteLineItem lineWithSku(Id lineId, String sku) {
        return (QuoteLineItem) JSON.deserialize(
            '{"attributes":{"type":"QuoteLineItem"},"Id":"' + lineId + '",' +
            '"Product2":{"attributes":{"type":"Product2"},"StockKeepingUnit":"' + sku + '"}}',
            QuoteLineItem.class
        );
    }
}
