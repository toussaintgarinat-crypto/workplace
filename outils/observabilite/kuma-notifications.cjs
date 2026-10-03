/* Modifier seulement le canal Telegram géré par S235, préserver les autres. */
function reconcileNotifications(existing, managedID, enabled) {
    const result = {...existing};
    if (managedID != null) {
        if (enabled) result[managedID] = true;
        else delete result[managedID];
    }
    return result;
}
module.exports = { reconcileNotifications };
