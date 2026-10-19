// Drops the Censhare Cloud sizing attributes so the entirely-pcm plan can
// rebuild them.
//
// AttributeDefinition.DataType and PicklistId are fixed at creation: an upsert
// that changes them reports success and silently leaves the old values, which
// then fails every dependent insert with "Select the same data type as the
// attribute definition's data type". Deleting first is the only way to change
// an attribute's type. Run this before reloading entirely-pcm, and only then —
// it is not part of the normal reset.
//
//   sf apex run -f scripts/apex/entirely/act2_reset_attributes.apex --target-org Entirely

List<String> codes = new List<String>{
    'ENT_NAMED_USERS', 'ENT_TOTAL_NAMED_USERS'
};

// Child to parent: a product attribute instantiates a classification
// attribute, which in turn references the definition.
List<ProductAttributeDefinition> pads = [
    SELECT Id FROM ProductAttributeDefinition
    WHERE AttributeDefinition.Code IN :codes
];
if (!pads.isEmpty()) {
    delete pads;
}
System.debug('Deleted ProductAttributeDefinition: ' + pads.size());

List<ProductClassificationAttr> pcas = [
    SELECT Id FROM ProductClassificationAttr
    WHERE AttributeDefinition.Code IN :codes
];
if (!pcas.isEmpty()) {
    delete pcas;
}
System.debug('Deleted ProductClassificationAttr: ' + pcas.size());

List<AttributeCategoryAttribute> acas = [
    SELECT Id FROM AttributeCategoryAttribute
    WHERE AttributeDefinition.Code IN :codes
];
if (!acas.isEmpty()) {
    delete acas;
}
System.debug('Deleted AttributeCategoryAttribute: ' + acas.size());

List<AttributeDefinition> defs = [
    SELECT Id FROM AttributeDefinition WHERE Code IN :codes
];
if (!defs.isEmpty()) {
    delete defs;
}
System.debug('Deleted AttributeDefinition: ' + defs.size());
