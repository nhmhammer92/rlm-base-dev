// Entirely demo, Act 1: one-time setup for the user presenting the demo.
//
// Kept separate from act1_reset.apex because User and GroupMember are setup objects:
// writing them in the same transaction as Opportunity or Lead raises MIXED_DML_OPERATION.
// Run this once per org; the reset then only touches records.

final String OWNER_TERRITORY = 'Germany';
final String APPROVER_GROUP = 'RLM_Entirely_Sales_VP';

// The demo's home territory. The Kestrel deal is Austria & CEE, so this mismatch is what
// raises the regional exception and sends the opportunity to approval.
User me = [SELECT Id, RLM_Territory__c FROM User WHERE Id = :UserInfo.getUserId()];
if (me.RLM_Territory__c != OWNER_TERRITORY) {
    me.RLM_Territory__c = OWNER_TERRITORY;
    update me;
}

// The orchestration assigns its approval step to this group, so without membership the
// request has nowhere to go.
List<Group> approverGroups = [
    SELECT Id FROM Group WHERE DeveloperName = :APPROVER_GROUP AND Type = 'Regular'
];
if (approverGroups.isEmpty()) {
    System.debug(LoggingLevel.ERROR, 'Group ' + APPROVER_GROUP + ' not found — deploy post_entirely first.');
} else {
    List<GroupMember> alreadyIn = [
        SELECT Id FROM GroupMember
        WHERE GroupId = :approverGroups[0].Id AND UserOrGroupId = :UserInfo.getUserId()
    ];
    if (alreadyIn.isEmpty()) {
        insert new GroupMember(GroupId = approverGroups[0].Id, UserOrGroupId = UserInfo.getUserId());
    }
}

System.debug(LoggingLevel.ERROR, 'Demo user ready: territory ' + OWNER_TERRITORY + ', approver in ' + APPROVER_GROUP);
