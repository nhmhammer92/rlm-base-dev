/**
 * Creates a configured, priced quote in ONE Place Sales Transaction call, for callers that
 * cannot express the Revenue Cloud line contract themselves — specifically the Slack/MCP
 * quoting path. The generic `createSalesTransaction` MCP tool picks the PricebookEntry on its
 * own (lowest Id wins, so a requested "Term Monthly" silently became "Term Annual" and a
 * 12-month term became 12 years), never asks the configurator for bundle defaults (bundles
 * arrive with zero components), and has no field for BillingFrequency.
 *
 * What this action guarantees per requested line:
 *   - the PricebookEntry is resolved from the requested SellingModelType + PricingTermUnit,
 *     never guessed; an unmatched request returns the product's real selling-model options
 *   - term lines get StartDate + EndDate; evergreen lines get StartDate only; one-time lines
 *     get neither dates nor billing fields
 *   - term/evergreen lines carry BillingFrequency (from the term unit) and PeriodBoundary,
 *     both validated by the platform — PeriodBoundary before the save, so no before-save flow
 *     can supply it
 *   - bundles are configured by the platform (addDefaultConfiguration), so their components
 *     are real linked child lines that survive repricing
 *   - ProductSellingModelId is never sent (FLS-protected; the PricebookEntry carries the model)
 *
 * Component discounts are applied in a second Place Sales Transaction call, after the
 * configurator has created the child lines, because their Ids do not exist until then.
 *
 * Published as a tool on a custom MCP server; also callable from Flow. One Place Sales
 * Transaction call per input row, so callers pass a single quote per invocation.
 */
public with sharing class RLM_CreateConfiguredQuote {

    private static final Map<String, String> TERM_UNIT_TO_BILLING_FREQUENCY = new Map<String, String>{
        'months' => 'Monthly',
        'annual' => 'Annual',
        'quarterly' => 'Quarterly',
        'semi-annual' => 'Semi-Annual',
        'weekly' => 'Weekly'
    };

    private static final Integer DEFAULT_TERM_MONTHS = 12;

    public class Input {
        @InvocableVariable(required=true label='Account Id'
            description='18-character Salesforce Id of the Account to quote (starts with 001).')
        public String accountId;

        @InvocableVariable(required=true label='Quote Name'
            description='Name for the new quote.')
        public String quoteName;

        @InvocableVariable(label='Start Date'
            description='Subscription start date as yyyy-MM-dd. Defaults to today.')
        public String startDate;

        @InvocableVariable(required=true label='Lines JSON'
            description='JSON array of top-level products only — never bundle components. Each entry: {"sku":"QB-COMPLETE","quantity":20,"sellingModelType":"TermDefined","pricingTermUnit":"Months","termMonths":12,"discountPercent":5,"componentDiscounts":[{"sku":"QB-DB","discountPercent":2}]}. sellingModelType is OneTime, TermDefined or Evergreen; pricingTermUnit is Months, Annual, Quarterly, Semi-Annual or Weekly. Omit dates and term for OneTime.')
        public String linesJson;

        @InvocableVariable(label='Opportunity Id'
            description='Optional Opportunity to link the quote to.')
        public String opportunityId;
    }

    public class Output {
        @InvocableVariable(label='Success')
        public Boolean success;

        @InvocableVariable(label='Quote Id')
        public String quoteId;

        @InvocableVariable(label='Orphan Quote'
            description='True when the quote header was saved but its lines failed. Delete the quote instead of retrying into a second header.')
        public Boolean isOrphanQuote;

        @InvocableVariable(label='Error Message')
        public String errorMessage;

        @InvocableVariable(label='Grand Total')
        public Decimal grandTotal;

        @InvocableVariable(label='Currency')
        public String currencyIsoCode;

        @InvocableVariable(label='Lines Summary JSON'
            description='JSON array of every saved line: sku, name, parentSku, sellingModel, billingFrequency, quantity, dates, discountPercent, netUnitPrice, netTotalPrice.')
        public String linesSummaryJson;
    }

    @InvocableMethod(
        label='Create Configured Quote'
        description='Creates a priced Draft quote with the requested selling models, bundle components configured by the platform, and line plus component discounts, in one Place Sales Transaction call.'
        category='Revenue Cloud'
    )
    public static List<Output> execute(List<Input> inputs) {
        List<Output> outputs = new List<Output>();
        if (inputs == null || inputs.isEmpty()) {
            outputs.add(failure('No input provided.'));
            return outputs;
        }
        for (Input in0 : inputs) {
            outputs.add(run(in0));
        }
        return outputs;
    }

    // ── Request model ────────────────────────────────────────────────────────

    @TestVisible
    private class LineSpec {
        public String sku;
        public Decimal quantity;
        public String sellingModelType;
        public String pricingTermUnit;
        public Integer termMonths;
        public Decimal discountPercent;
        public Map<String, Decimal> componentDiscounts = new Map<String, Decimal>();
    }

    private class QuoteRequestException extends Exception {}

    // ── Orchestration ────────────────────────────────────────────────────────

    private static Output run(Input in0) {
        Id accountId;
        try {
            accountId = Id.valueOf(String.isBlank(in0.accountId) ? null : in0.accountId.trim());
        } catch (Exception e) {
            return failure('Invalid Account Id: ' + in0.accountId);
        }
        if (String.isBlank(in0.quoteName)) {
            return failure('Quote Name is required.');
        }
        Id opportunityId = null;
        if (String.isNotBlank(in0.opportunityId)) {
            try {
                opportunityId = Id.valueOf(in0.opportunityId.trim());
            } catch (Exception e) {
                return failure('Invalid Opportunity Id: ' + in0.opportunityId);
            }
        }

        List<LineSpec> specs;
        Date startDate;
        try {
            specs = parseLines(in0.linesJson);
            startDate = parseStartDate(in0.startDate);
        } catch (QuoteRequestException e) {
            return failure(e.getMessage());
        }

        SObject account = loadWithCurrency('Account', accountId);
        if (account == null) {
            return failure('Account not found or not accessible: ' + accountId);
        }
        Id pricebookId = standardPricebookId();
        if (pricebookId == null) {
            return failure('No active standard price book found.');
        }

        Map<String, PricebookEntry> resolved;
        try {
            resolved = resolvePricebookEntries(specs, pricebookId, currencyOf(account));
        } catch (QuoteRequestException e) {
            return failure(e.getMessage());
        }

        List<GraphRecord> records = buildCreateGraph(in0.quoteName, accountId, opportunityId, pricebookId, specs, resolved, startDate);
        PstResult created = invoker().place(records, true);
        if (!created.isSuccess) {
            Output out = failure('Place Sales Transaction failed: ' + created.errorText);
            out.quoteId = created.quoteId;
            out.isOrphanQuote = String.isNotBlank(created.quoteId);
            return out;
        }

        Id quoteId;
        try {
            quoteId = Id.valueOf(created.quoteId);
        } catch (Exception e) {
            return failure('Place Sales Transaction returned no quote Id.');
        }

        List<QuoteLineItem> lines = loadLines(quoteId);
        Map<Id, String> parentSkuByLineId = parentSkuByLine(quoteId, lines);

        List<GraphRecord> discountRecords = buildComponentDiscountGraph(quoteId, specs, lines, parentSkuByLineId);
        String discountError = null;
        if (!discountRecords.isEmpty()) {
            PstResult discounted = invoker().place(discountRecords, false);
            if (!discounted.isSuccess) {
                discountError = 'Component discounts were not applied: ' + discounted.errorText;
            }
            lines = loadLines(quoteId);
            parentSkuByLineId = parentSkuByLine(quoteId, lines);
        }

        Output out = new Output();
        out.quoteId = quoteId;
        out.isOrphanQuote = false;
        out.success = discountError == null;
        out.errorMessage = discountError;
        out.linesSummaryJson = summarise(lines, parentSkuByLineId);
        SObject quote = loadWithCurrency('Quote', quoteId, new List<String>{ 'GrandTotal' });
        if (quote != null) {
            out.grandTotal = (Decimal) quote.get('GrandTotal');
            out.currencyIsoCode = currencyOf(quote);
        }
        return out;
    }

    // ── Parsing ──────────────────────────────────────────────────────────────

    @TestVisible
    private static List<LineSpec> parseLines(String linesJson) {
        if (String.isBlank(linesJson)) {
            throw new QuoteRequestException('Lines JSON is required.');
        }
        Object parsed;
        try {
            parsed = JSON.deserializeUntyped(linesJson);
        } catch (Exception e) {
            throw new QuoteRequestException('Lines JSON is not valid JSON: ' + e.getMessage());
        }
        if (!(parsed instanceof List<Object>)) {
            throw new QuoteRequestException('Lines JSON must be a JSON array of line objects.');
        }
        List<LineSpec> specs = new List<LineSpec>();
        for (Object entry : (List<Object>) parsed) {
            if (!(entry instanceof Map<String, Object>)) {
                throw new QuoteRequestException('Each Lines JSON entry must be a JSON object.');
            }
            Map<String, Object> row = (Map<String, Object>) entry;
            LineSpec spec = new LineSpec();
            spec.sku = textOf(row.get('sku'));
            if (String.isBlank(spec.sku)) {
                spec.sku = textOf(row.get('productCode'));
            }
            if (String.isBlank(spec.sku)) {
                throw new QuoteRequestException('Every Lines JSON entry needs a "sku".');
            }
            spec.quantity = decimalOf(row.get('quantity'));
            if (spec.quantity == null || spec.quantity <= 0) {
                spec.quantity = 1;
            }
            spec.sellingModelType = textOf(row.get('sellingModelType'));
            spec.pricingTermUnit = textOf(row.get('pricingTermUnit'));
            Decimal term = decimalOf(row.get('termMonths'));
            spec.termMonths = term == null ? null : Integer.valueOf(term);
            spec.discountPercent = decimalOf(row.get('discountPercent'));
            Object components = row.get('componentDiscounts');
            if (components instanceof List<Object>) {
                for (Object component : (List<Object>) components) {
                    if (!(component instanceof Map<String, Object>)) {
                        continue;
                    }
                    Map<String, Object> componentRow = (Map<String, Object>) component;
                    String componentSku = textOf(componentRow.get('sku'));
                    Decimal componentDiscount = decimalOf(componentRow.get('discountPercent'));
                    if (String.isNotBlank(componentSku) && componentDiscount != null) {
                        spec.componentDiscounts.put(componentSku.toUpperCase(), componentDiscount);
                    }
                }
            }
            specs.add(spec);
        }
        if (specs.isEmpty()) {
            throw new QuoteRequestException('Lines JSON contains no lines.');
        }
        return specs;
    }

    @TestVisible
    private static Date parseStartDate(String raw) {
        if (String.isBlank(raw)) {
            return Date.today();
        }
        try {
            return Date.valueOf(raw.trim());
        } catch (Exception e) {
            throw new QuoteRequestException('Start Date must be yyyy-MM-dd, received: ' + raw);
        }
    }

    // ── Catalog resolution ───────────────────────────────────────────────────

    /**
     * One PricebookEntry per requested line, keyed by uppercased SKU. The selling model is
     * matched on the caller's SellingModelType and PricingTermUnit; an ambiguous or unmatched
     * request fails with the product's actual options rather than picking one.
     */
    @TestVisible
    private static Map<String, PricebookEntry> resolvePricebookEntries(
        List<LineSpec> specs,
        Id pricebookId,
        String currencyIsoCode
    ) {
        Set<String> skus = new Set<String>();
        for (LineSpec spec : specs) {
            skus.add(spec.sku);
        }
        Map<String, List<PricebookEntry>> bySku = new Map<String, List<PricebookEntry>>();
        for (PricebookEntry pbe : queryPricebookEntries(skus, pricebookId, currencyIsoCode)) {
            String key = pbe.Product2.StockKeepingUnit.toUpperCase();
            if (!bySku.containsKey(key)) {
                bySku.put(key, new List<PricebookEntry>());
            }
            bySku.get(key).add(pbe);
        }

        Map<String, PricebookEntry> resolved = new Map<String, PricebookEntry>();
        for (LineSpec spec : specs) {
            String key = spec.sku.toUpperCase();
            List<PricebookEntry> candidates = bySku.get(key);
            if (candidates == null || candidates.isEmpty()) {
                throw new QuoteRequestException(
                    'No active price book entry for SKU ' + spec.sku + ' in ' + currencyIsoCode +
                    '. Check the SKU and that the product is priced on the standard price book.'
                );
            }
            List<PricebookEntry> matches = new List<PricebookEntry>();
            for (PricebookEntry pbe : candidates) {
                if (matchesRequestedModel(pbe, spec)) {
                    matches.add(pbe);
                }
            }
            if (matches.size() != 1) {
                throw new QuoteRequestException(
                    (matches.isEmpty() ? 'No selling model matches' : 'Several selling models match') +
                    ' the request for ' + spec.sku + ' (sellingModelType=' +
                    blankAs(spec.sellingModelType, 'any') + ', pricingTermUnit=' +
                    blankAs(spec.pricingTermUnit, 'any') + '). Available: ' + describeOptions(candidates)
                );
            }
            resolved.put(key, matches[0]);
        }
        return resolved;
    }

    private static List<PricebookEntry> queryPricebookEntries(Set<String> skus, Id pricebookId, String currencyIsoCode) {
        // Dynamic because CurrencyIsoCode only exists on PricebookEntry in multi-currency orgs,
        // and this class also deploys to single-currency builds.
        String soql =
            'SELECT Id, Product2Id, Product2.Name, Product2.StockKeepingUnit, UnitPrice, ' +
            'ProductSellingModel.Name, ProductSellingModel.SellingModelType, ProductSellingModel.PricingTermUnit ' +
            'FROM PricebookEntry WHERE IsActive = true AND Pricebook2Id = :pricebookId ' +
            'AND Product2.StockKeepingUnit IN :skus';
        Map<String, Object> binds = new Map<String, Object>{
            'pricebookId' => pricebookId,
            'skus' => skus
        };
        if (isMultiCurrency() && String.isNotBlank(currencyIsoCode)) {
            soql += ' AND CurrencyIsoCode = :currencyIsoCode';
            binds.put('currencyIsoCode', currencyIsoCode);
        }
        return (List<PricebookEntry>) Database.queryWithBinds(soql, binds, AccessLevel.USER_MODE);
    }

    private static Boolean matchesRequestedModel(PricebookEntry pbe, LineSpec spec) {
        String type = pbe.ProductSellingModel == null ? null : String.valueOf(pbe.ProductSellingModel.SellingModelType);
        String unit = pbe.ProductSellingModel == null ? null : String.valueOf(pbe.ProductSellingModel.PricingTermUnit);
        if (String.isNotBlank(spec.sellingModelType) && !normalisedType(spec.sellingModelType).equalsIgnoreCase(type)) {
            return false;
        }
        if (String.isNotBlank(spec.pricingTermUnit) && !spec.pricingTermUnit.trim().equalsIgnoreCase(unit)) {
            return false;
        }
        return true;
    }

    /** Accepts the shorthands an LLM produces ("Term", "One-Time") alongside the API values. */
    @TestVisible
    private static String normalisedType(String raw) {
        String value = raw == null ? '' : raw.trim().toLowerCase().replaceAll('[^a-z]', '');
        if (value == 'onetime') {
            return 'OneTime';
        }
        if (value == 'evergreen') {
            return 'Evergreen';
        }
        if (value == 'term' || value == 'termdefined') {
            return 'TermDefined';
        }
        return raw == null ? '' : raw.trim();
    }

    private static String describeOptions(List<PricebookEntry> candidates) {
        List<String> options = new List<String>();
        for (PricebookEntry pbe : candidates) {
            if (pbe.ProductSellingModel == null) {
                continue;
            }
            options.add(
                pbe.ProductSellingModel.Name + ' (' + pbe.ProductSellingModel.SellingModelType +
                '/' + pbe.ProductSellingModel.PricingTermUnit + ')'
            );
        }
        return String.join(options, ', ');
    }

    // ── Graph building ───────────────────────────────────────────────────────

    @TestVisible
    private static List<GraphRecord> buildCreateGraph(
        String quoteName,
        Id accountId,
        Id opportunityId,
        Id pricebookId,
        List<LineSpec> specs,
        Map<String, PricebookEntry> resolved,
        Date startDate
    ) {
        GraphRecord header = new GraphRecord('refQuote', 'Quote', 'POST', null);
        // QuoteAccountId, not AccountId — AccountId is derived and not writable on the graph.
        header.fields.put('Name', quoteName);
        header.fields.put('QuoteAccountId', accountId);
        header.fields.put('Pricebook2Id', pricebookId);
        if (opportunityId != null) {
            header.fields.put('OpportunityId', opportunityId);
        }
        List<GraphRecord> records = new List<GraphRecord>{ header };

        Integer index = 0;
        for (LineSpec spec : specs) {
            PricebookEntry pbe = resolved.get(spec.sku.toUpperCase());
            GraphRecord line = new GraphRecord('refLine' + index, 'QuoteLineItem', 'POST', null);
            line.fields.put('QuoteId', '@{refQuote.id}');
            line.fields.put('Product2Id', pbe.Product2Id);
            line.fields.put('PricebookEntryId', pbe.Id);
            line.fields.put('Quantity', spec.quantity);
            if (spec.discountPercent != null && spec.discountPercent != 0) {
                line.fields.put('Discount', spec.discountPercent);
            }
            String type = pbe.ProductSellingModel == null
                ? null
                : String.valueOf(pbe.ProductSellingModel.SellingModelType);
            String unit = pbe.ProductSellingModel == null
                ? null
                : String.valueOf(pbe.ProductSellingModel.PricingTermUnit);
            String billingFrequency = unit == null
                ? null
                : TERM_UNIT_TO_BILLING_FREQUENCY.get(unit.toLowerCase());
            if (type == 'TermDefined' || type == 'Evergreen') {
                line.fields.put('StartDate', isoDate(startDate));
                // Anniversary is validated by Place Sales Transaction before the save, so it
                // cannot be defaulted by a before-save flow — always send it.
                line.fields.put('PeriodBoundary', 'Anniversary');
                if (String.isNotBlank(billingFrequency)) {
                    line.fields.put('BillingFrequency', billingFrequency);
                }
            }
            if (type == 'TermDefined') {
                Integer months = spec.termMonths == null || spec.termMonths <= 0
                    ? DEFAULT_TERM_MONTHS
                    : spec.termMonths;
                line.fields.put('EndDate', isoDate(startDate.addMonths(months).addDays(-1)));
            }
            records.add(line);
            index++;
        }
        return records;
    }

    /**
     * Component discounts target the child lines the configurator created, so their Ids only
     * exist after the create call. Matched by component SKU under the requesting bundle's SKU.
     */
    @TestVisible
    private static List<GraphRecord> buildComponentDiscountGraph(
        Id quoteId,
        List<LineSpec> specs,
        List<QuoteLineItem> lines,
        Map<Id, String> parentSkuByLineId
    ) {
        Map<String, Decimal> wanted = new Map<String, Decimal>();
        for (LineSpec spec : specs) {
            for (String componentSku : spec.componentDiscounts.keySet()) {
                wanted.put(spec.sku.toUpperCase() + '|' + componentSku, spec.componentDiscounts.get(componentSku));
            }
        }
        List<GraphRecord> records = new List<GraphRecord>();
        if (wanted.isEmpty()) {
            return records;
        }
        for (QuoteLineItem line : lines) {
            String parentSku = parentSkuByLineId.get(line.Id);
            String sku = line.Product2 == null ? null : line.Product2.StockKeepingUnit;
            if (String.isBlank(parentSku) || String.isBlank(sku)) {
                continue;
            }
            String key = parentSku.toUpperCase() + '|' + sku.toUpperCase();
            if (!wanted.containsKey(key)) {
                continue;
            }
            GraphRecord record = new GraphRecord('refDisc' + records.size(), 'QuoteLineItem', 'PATCH', line.Id);
            record.fields.put('Discount', wanted.get(key));
            records.add(record);
        }
        if (!records.isEmpty()) {
            records.add(0, new GraphRecord('refQuote', 'Quote', 'PATCH', quoteId));
        }
        return records;
    }

    // ── Read back ────────────────────────────────────────────────────────────

    private static List<QuoteLineItem> loadLines(Id quoteId) {
        return [
            SELECT Id, Product2Id, Product2.Name, Product2.StockKeepingUnit, ParentQuoteLineItemId,
                   Quantity, Discount, BillingFrequency, PeriodBoundary, StartDate, EndDate,
                   NetUnitPrice, NetTotalPrice, PricebookEntry.ProductSellingModel.Name
            FROM QuoteLineItem
            WHERE QuoteId = :quoteId
            WITH USER_MODE
            ORDER BY LineNumber
        ];
    }

    /**
     * Component to bundle SKU map. ParentQuoteLineItemId is the direct signal; QuoteLineRelationship
     * is the fallback because the field is not populated on every configuration path.
     */
    private static Map<Id, String> parentSkuByLine(Id quoteId, List<QuoteLineItem> lines) {
        Map<Id, String> skuByLineId = new Map<Id, String>();
        for (QuoteLineItem line : lines) {
            skuByLineId.put(line.Id, line.Product2 == null ? null : line.Product2.StockKeepingUnit);
        }
        Map<Id, String> parentSku = new Map<Id, String>();
        Boolean anyParent = false;
        for (QuoteLineItem line : lines) {
            if (line.ParentQuoteLineItemId != null) {
                anyParent = true;
                parentSku.put(line.Id, skuByLineId.get(line.ParentQuoteLineItemId));
            }
        }
        if (anyParent) {
            return parentSku;
        }
        for (QuoteLineRelationship relationship : [
            SELECT MainQuoteLineId, AssociatedQuoteLineId
            FROM QuoteLineRelationship
            WHERE QuoteId = :quoteId
              AND AssociatedQuoteLineRole = 'BundleComponent'
            WITH USER_MODE
        ]) {
            parentSku.put(relationship.AssociatedQuoteLineId, skuByLineId.get(relationship.MainQuoteLineId));
        }
        return parentSku;
    }

    @TestVisible
    private static String summarise(List<QuoteLineItem> lines, Map<Id, String> parentSkuByLineId) {
        List<Object> rows = new List<Object>();
        for (QuoteLineItem line : lines) {
            String sellingModel = line.PricebookEntry != null && line.PricebookEntry.ProductSellingModel != null
                ? line.PricebookEntry.ProductSellingModel.Name
                : null;
            rows.add(new Map<String, Object>{
                'sku' => line.Product2 == null ? null : line.Product2.StockKeepingUnit,
                'name' => line.Product2 == null ? null : line.Product2.Name,
                'parentSku' => parentSkuByLineId.get(line.Id),
                'sellingModel' => sellingModel,
                'billingFrequency' => line.BillingFrequency,
                'quantity' => line.Quantity,
                'startDate' => line.StartDate,
                'endDate' => line.EndDate,
                'discountPercent' => line.Discount,
                'netUnitPrice' => line.NetUnitPrice,
                'netTotalPrice' => line.NetTotalPrice
            });
        }
        return JSON.serialize(rows);
    }

    // ── Place Sales Transaction seam ─────────────────────────────────────────

    /**
     * Object-agnostic graph record, so the request can be built and asserted without the
     * managed RevSalesTrxn types (which no unit test can execute).
     */
    @TestVisible
    private class GraphRecord {
        public String referenceId;
        public String objectName;
        public String method;
        public Id recordId;
        public Map<String, Object> fields = new Map<String, Object>();

        public GraphRecord(String referenceId, String objectName, String method, Id recordId) {
            this.referenceId = referenceId;
            this.objectName = objectName;
            this.method = method;
            this.recordId = recordId;
        }
    }

    @TestVisible
    private class PstResult {
        public Boolean isSuccess = false;
        public String quoteId;
        public String errorText;
    }

    @TestVisible
    private interface PstInvoker {
        PstResult place(List<GraphRecord> records, Boolean runConfigurator);
    }

    @TestVisible
    private static PstInvoker testInvoker;

    private static PstInvoker invoker() {
        return testInvoker == null ? new PlatformPstInvoker() : testInvoker;
    }

    private class PlatformPstInvoker implements PstInvoker {
        public PstResult place(List<GraphRecord> records, Boolean runConfigurator) {
            List<RevSalesTrxn.RecordWithReferenceRequest> graphRecords =
                new List<RevSalesTrxn.RecordWithReferenceRequest>();
            for (GraphRecord record : records) {
                Schema.SObjectType type = record.objectName == 'Quote'
                    ? Quote.getSObjectType()
                    : QuoteLineItem.getSObjectType();
                RevSalesTrxn.RecordResource resource = record.recordId == null
                    ? new RevSalesTrxn.RecordResource(type, record.method)
                    : new RevSalesTrxn.RecordResource(type, record.method, record.recordId);
                resource.fieldValues = record.fields;
                graphRecords.add(new RevSalesTrxn.RecordWithReferenceRequest(record.referenceId, resource));
            }
            RevSalesTrxn.ConfigurationOptionsInput options = new RevSalesTrxn.ConfigurationOptionsInput();
            options.addDefaultConfiguration = runConfigurator;
            options.executeConfigurationRules = runConfigurator;
            options.validateProductCatalog = runConfigurator;
            options.validateAmendRenewCancel = runConfigurator;
            PstResult result = new PstResult();
            try {
                RevSalesTrxn.PlaceSalesTransactionResponse response = RevSalesTrxn.PlaceSalesTransactionExecutor.execute(
                    new RevSalesTrxn.GraphRequest('CreateConfiguredQuote', graphRecords),
                    RevSalesTrxn.PricingPreferenceEnum.SYSTEM,
                    // FORCE runs the configurator so bundles get their default components; the
                    // discount pass sends SKIP so nothing is reconfigured a second time.
                    runConfigurator
                        ? RevSalesTrxn.ConfigurationExecutionEnum.FORCE
                        : RevSalesTrxn.ConfigurationExecutionEnum.SKIP,
                    options,
                    null,
                    (RevSalesTrxn.CatalogRatesPreferenceEnum) null,
                    RevSalesTrxn.TaxPreferenceEnum.SKIP,
                    (RevSalesTrxn.PersistPreferenceEnum) null
                );
                if (response == null) {
                    result.errorText = 'Place Sales Transaction returned no response.';
                    return result;
                }
                result.quoteId = response.salesTransactionId;
                result.isSuccess = response.isSuccess == true;
                if (!result.isSuccess) {
                    result.errorText = response.errorResponse == null
                        ? 'unknown error'
                        : String.valueOf(response.errorResponse);
                }
            } catch (Exception e) {
                result.errorText = e.getMessage();
            }
            return result;
        }
    }

    // ── Small helpers ────────────────────────────────────────────────────────

    /**
     * Single record with CurrencyIsoCode included only where the field exists — it is absent in
     * single-currency orgs, so a static SOQL naming it would not compile there.
     */
    private static SObject loadWithCurrency(String objectName, Id recordId) {
        return loadWithCurrency(objectName, recordId, new List<String>());
    }

    private static SObject loadWithCurrency(String objectName, Id recordId, List<String> extraFields) {
        List<String> fields = new List<String>{ 'Id' };
        fields.addAll(extraFields);
        if (isMultiCurrency()) {
            fields.add('CurrencyIsoCode');
        }
        String soql = 'SELECT ' + String.join(fields, ', ') + ' FROM ' + objectName +
            ' WHERE Id = :recordId LIMIT 1';
        List<SObject> records = Database.queryWithBinds(
            soql,
            new Map<String, Object>{ 'recordId' => recordId },
            AccessLevel.USER_MODE
        );
        return records.isEmpty() ? null : records[0];
    }

    private static Id standardPricebookId() {
        if (Test.isRunningTest()) {
            // The org's standard price book is invisible to tests; this is the same accommodation
            // RLM_ProductCatalogPbeService makes.
            return Test.getStandardPricebookId();
        }
        for (Pricebook2 pricebook : [
            SELECT Id
            FROM Pricebook2
            WHERE IsStandard = true AND IsActive = true
            WITH USER_MODE
            LIMIT 1
        ]) {
            return pricebook.Id;
        }
        return null;
    }

    private static Boolean isMultiCurrency() {
        return UserInfo.isMultiCurrencyOrganization();
    }

    private static String currencyOf(SObject record) {
        return isMultiCurrency() ? (String) record.get('CurrencyIsoCode') : UserInfo.getDefaultCurrency();
    }

    private static String isoDate(Date value) {
        return DateTime.newInstanceGmt(value, Time.newInstance(0, 0, 0, 0)).formatGmt('yyyy-MM-dd');
    }

    private static String blankAs(String value, String fallback) {
        return String.isBlank(value) ? fallback : value.trim();
    }

    private static String textOf(Object value) {
        return value == null ? null : String.valueOf(value).trim();
    }

    private static Decimal decimalOf(Object value) {
        if (value == null) {
            return null;
        }
        if (value instanceof Decimal) {
            return (Decimal) value;
        }
        if (value instanceof Integer) {
            return (Decimal) (Integer) value;
        }
        if (value instanceof Double) {
            return Decimal.valueOf((Double) value);
        }
        try {
            return Decimal.valueOf(String.valueOf(value).trim());
        } catch (Exception e) {
            return null;
        }
    }

    private static Output failure(String message) {
        Output out = new Output();
        out.success = false;
        out.isOrphanQuote = false;
        out.errorMessage = message;
        return out;
    }
}
