/* Provisionnement S235 : exécuté dans l'image Kuma (Socket.IO fourni par Kuma).
 * Identifiants via stdin JSON ; aucune sortie contenant les secrets.
 * Les sondes existantes sont préservées, jamais supprimées implicitement.
 */
const fs = require('fs');
const { io } = require('socket.io-client');
const { reconcileNotifications } = require('./kuma-notifications.cjs');
const config = JSON.parse(fs.readFileSync(0, 'utf8'));
const socket = io('http://localhost:3001', { reconnection: false });
let monitors = {};
let notifications = [];
socket.on('monitorList', data => { monitors = data; });
socket.on('updateMonitorIntoList', data => { Object.assign(monitors, data); });
socket.on('notificationList', data => { notifications = data; });
const deadline = setTimeout(() => finish(1, 'Délai de provisionnement dépassé'), 90000);
function finish(code, message) {
    if (message) console.log(message);
    clearTimeout(deadline);
    socket.disconnect();
    process.exit(code);
}
function rpc(event, ...args) {
    return new Promise((resolve, reject) => {
        socket.timeout(30000).emit(event, ...args, (error, result) => {
            if (error || !result?.ok) reject(new Error(`Échec RPC ${event}`));
            else resolve(result);
        });
    });
}
async function refresh() {
    await rpc('getMonitorList');
}
async function upsert(spec, managedID) {
    const existing = Object.values(monitors).find(m => m.name === spec.name);
    const body = { active: true, maxredirects: 5, expiryNotification: false,
        conditions: [], kafkaProducerBrokers: [], kafkaProducerSaslOptions: {mechanism:'None'},
        rabbitmqNodes: [], ...spec };
    if (existing) {
        // Conserver les notifications manuelles et tous les champs non gérés.
        const full = await rpc('getMonitor', existing.id);
        const merged = {...full.monitor, ...body, id: existing.id};
        merged.notificationIDList = reconcileNotifications(full.monitor.notificationIDList, managedID, config.telegramEnabled);
        await rpc('editMonitor', merged);
        return existing.id;
    }
    body.notificationIDList = reconcileNotifications(body.notificationIDList, managedID, config.telegramEnabled);
    const result = await rpc('add', body);
    return result.monitorID;
}
socket.once('connect', async () => {
    try {
        if (!config.username || !config.password) throw new Error('Identifiants absents');
        // setup est rejeté sans modification si un compte existe déjà.
        if (config.setup) await rpc('setup', config.username, config.password);
        await rpc('login', {username:config.username, password:config.password, token:''});
        await refresh();
        if (config.action === 'list') {
            console.log(JSON.stringify(Object.values(monitors).map(m => ({id:m.id,name:m.name,url:m.url,active:m.active}))));
        } else if (config.action === 'delete') {
            const target = Object.values(monitors).find(m => m.name === config.name);
            if (target) await rpc('deleteMonitor', target.id, false);
            console.log('Sonde de test retirée');
        } else if (config.action === 'beats') {
            const target = Object.values(monitors).find(m => m.name === config.name);
            if (!target) throw new Error('Sonde introuvable');
            const result = await rpc('getMonitorBeats', target.id, 24);
            console.log(JSON.stringify(result));
        } else {
            let notificationID = notifications.find(n => n.name === 'Workplace — Telegram disponibilité')?.id;
            if (config.telegramEnabled) {
                if (!config.telegramToken || !config.telegramChatID) throw new Error('Configuration Telegram incomplète');
                const existing = notifications.find(n => n.name === 'Workplace — Telegram disponibilité');
                const result = await rpc('addNotification', {
                    name:'Workplace — Telegram disponibilité', type:'telegram', isDefault:false,
                    active:true, applyExisting:false, telegramBotToken:config.telegramToken,
                    telegramChatID:config.telegramChatID, telegramMessageThreadID:config.telegramTopicID || '',
                    telegramSendSilently:false, telegramProtectContent:false,
                }, existing?.id || null);
                notificationID = result.id;
            }
            const inventory = config.monitor ? [config.monitor] : JSON.parse(fs.readFileSync('/app/s235-monitors.json', 'utf8'));
            for (const spec of inventory) {
                await upsert(spec, notificationID);
                await refresh();
            }
            console.log(`${inventory.length} sondes provisionnées ; Telegram ${config.telegramEnabled ? 'activé' : 'non activé'}`);
        }
        finish(0);
    } catch (error) {
        // Ne pas exposer de réponse RPC susceptible de contenir un token.
        finish(1, error.message);
    }
});
socket.on('connect_error', () => finish(1, 'Connexion Kuma impossible'));
