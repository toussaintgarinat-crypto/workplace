const assert = require('node:assert/strict');
const { reconcileNotifications } = require('./kuma-notifications.cjs');
assert.deepEqual(reconcileNotifications({'1':true,'2':true}, 1, false), {'2':true});
assert.deepEqual(reconcileNotifications({'2':true}, 1, true), {'1':true,'2':true});
assert.deepEqual(reconcileNotifications({'2':true}, undefined, false), {'2':true});
console.log('Trois cas de rattachement/désactivation Telegram validés');
