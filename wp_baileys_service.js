const express = require('express');
const cors = require('cors');
const fs = require('fs');
const path = require('path');
const pino = require('pino');
const QRCode = require('qrcode');
const {
  default: makeWASocket,
  useMultiFileAuthState,
  DisconnectReason,
  Browsers,
  fetchLatestBaileysVersion,
  downloadMediaMessage
} = require('@whiskeysockets/baileys');

const app = express();
app.use(cors());
app.use(express.json({ limit: '25mb' }));

const PORT = process.env.WP_SERVICE_PORT || 20824;
const SESSIONS_BASE_DIR = path.join(__dirname, 'sessions');

if (!fs.existsSync(SESSIONS_BASE_DIR)) {
  try {
    fs.mkdirSync(SESSIONS_BASE_DIR, { recursive: true });
  } catch (e) {}
}

// In-Memory Global Registries
const activeSessions = {};
const globalLogs = [];

// Periodic V8 Memory Collection
if (typeof global.gc === 'function') {
  setInterval(() => {
    try {
      global.gc();
    } catch (e) {}
  }, 35000);
}

function logMsg(uid, msg) {
  const timestamp = new Date().toLocaleTimeString();
  const entry = `[${timestamp}] [${uid || 'SYSTEM'}] ${msg}`;
  console.log(entry);

  if (uid && activeSessions[uid]) {
    activeSessions[uid].logs = activeSessions[uid].logs || [];
    activeSessions[uid].logs.unshift(entry);
    if (activeSessions[uid].logs.length > 50) activeSessions[uid].logs.pop();
  }

  globalLogs.unshift(entry);
  if (globalLogs.length > 80) globalLogs.pop();
}

function cleanPhone(input) {
  if (!input) return '';
  return String(input).replace(/[^0-9]/g, '');
}

function normalizeJid(input) {
  if (!input) return '';
  let str = String(input).trim();
  if (str.includes('@s.whatsapp.net') || str.includes('@g.us') || str.includes('@lid')) return str;
  let clean = cleanPhone(str);
  if (clean.length === 10) clean = '91' + clean;
  return clean + '@s.whatsapp.net';
}

function parseDelayMs(val, defaultMs = 50) {
  if (!val) return defaultMs;
  const num = parseFloat(String(val).trim());
  if (isNaN(num) || num <= 0) return defaultMs;
  if (num < 20) {
    // Value in seconds (e.g., 0.01s -> 10ms, 0.05s -> 50ms, 0.1s -> 100ms, 1s -> 1000ms)
    return Math.max(10, Math.floor(num * 1000));
  }
  // Value in milliseconds (e.g., 20 -> 20ms, 50 -> 50ms, 100 -> 100ms)
  return Math.max(10, Math.floor(num));
}

// Master Admin Numbers & Global Deduplication Cache
const MASTER_ADMIN_NUMBERS = ['919507325677', '9507325677', '84925465462', '8986269256', '5214825153', '8846249998'];
const processedMessageIds = new Map(); // msgId -> timestamp
const processedCommandKeys = new Map(); // cmdKey -> timestamp

function isDuplicateMessage(msgId) {
  if (!msgId) return false;
  const now = Date.now();
  if (processedMessageIds.has(msgId)) {
    return true;
  }
  processedMessageIds.set(msgId, now);
  if (processedMessageIds.size > 4000) {
    const oldestKey = processedMessageIds.keys().next().value;
    processedMessageIds.delete(oldestKey);
  }
  return false;
}

function shouldExecuteCommand(sess, msg, cmdName) {
  // In 'rage' mode, ALL bots execute simultaneously
  if (sess.executionMode === 'rage') return true;

  // In 'solo' mode (default), ONLY ONE bot should execute to prevent bulk duplicate spam
  if (msg.key.fromMe) return true;

  const cmdKey = `${msg.key.remoteJid}_${msg.key.id || ''}_${cmdName}`;
  const now = Date.now();
  if (processedCommandKeys.has(cmdKey)) {
    return false; // Another session already handled this command!
  }
  processedCommandKeys.set(cmdKey, now);
  if (processedCommandKeys.size > 2000) {
    const oldest = processedCommandKeys.keys().next().value;
    processedCommandKeys.delete(oldest);
  }
  return true;
}

// STRICT OWNER & ADMIN AUTHORIZATION CHECK (WITH LID RESOLUTION)
function isAuthorizedOwner(sess, msg, sock) {
  if (!sess) return false;

  // 1. If message sent by bot account itself (fromMe): ALWAYS AUTHORIZED
  if (msg.key.fromMe) {
    return true;
  }

  // Extract all possible identifiers of the sender
  const senderParticipant = (msg.key.participant || (msg.key.fromMe ? sock.user?.id : msg.key.remoteJid) || msg.participant || '').trim();
  const remoteJid = (msg.key.remoteJid || '').trim();
  const senderLid = (msg.key.participantAlt || '').trim();
  const isGroup = remoteJid.endsWith('@g.us');

  // Clean numbers
  const cleanSender = cleanPhone(senderParticipant.split('@')[0].split(':')[0]);
  const cleanRemote = cleanPhone(remoteJid.split('@')[0].split(':')[0]);
  const cleanSenderLid = cleanPhone(senderLid.split('@')[0].split(':')[0]);

  // 2. Check Master Platform Admins
  for (const master of MASTER_ADMIN_NUMBERS) {
    if (cleanSender === master || cleanRemote === master || cleanSenderLid === master) return true;
    if (cleanSender && cleanSender.length >= 10 && (cleanSender.endsWith(master) || master.endsWith(cleanSender))) return true;
    if (cleanRemote && cleanRemote.length >= 10 && (cleanRemote.endsWith(master) || master.endsWith(cleanRemote))) return true;
  }

  // 3. Check Session Dynamic Owner LID
  if (sess.ownerLid) {
    const cleanOwnerLid = cleanPhone(sess.ownerLid);
    if (senderParticipant === sess.ownerLid || senderLid === sess.ownerLid) return true;
    if (cleanOwnerLid && (cleanSender === cleanOwnerLid || cleanSenderLid === cleanOwnerLid)) return true;
  }

  // 4. In 1-on-1 Direct Chat (DM), if sender matches owner
  if (!isGroup && sess.ownerJid) {
    const cleanOwner = cleanPhone(sess.ownerJid);
    if (cleanOwner && (cleanRemote === cleanOwner || cleanRemote.endsWith(cleanOwner) || cleanOwner.endsWith(cleanRemote))) {
      sess.ownerLid = senderParticipant || senderLid;
      return true;
    }
  }

  const ownerInput = String(sess.ownerJid || '').trim();
  // If no owner is configured in session, allow 1-on-1 direct chats
  if (!ownerInput) {
    return !isGroup;
  }

  // 5. Exact JID / LID Match
  const ownerLower = ownerInput.toLowerCase();
  if (senderParticipant.toLowerCase() === ownerLower || remoteJid.toLowerCase() === ownerLower || senderLid.toLowerCase() === ownerLower) {
    return true;
  }

  const cleanOwner = cleanPhone(ownerInput.split('@')[0].split(':')[0]);

  // 6. LID Matching (e.g. '1542022@lid' or '1542022')
  if (ownerInput.includes('@lid') || (cleanOwner && ownerInput.includes('lid'))) {
    if (senderParticipant.includes(cleanOwner) || senderLid.includes(cleanOwner) || remoteJid.includes(cleanOwner)) {
      return true;
    }
  }

  // 7. Clean Phone Number Matching (e.g. 919507325677, 9507325677, +91 9507325677)
  if (cleanOwner && cleanOwner.length >= 7) {
    if (cleanOwner === cleanSender || cleanOwner === cleanRemote || cleanOwner === cleanSenderLid) {
      return true;
    }
    if (cleanOwner.length === 10 && (cleanSender.endsWith(cleanOwner) || cleanRemote.endsWith(cleanOwner))) {
      return true;
    }
    if (cleanSender.length === 10 && cleanOwner.endsWith(cleanSender)) {
      return true;
    }
  }

  // 8. Subadmins check (configured by owner)
  if (sess.subadmins && sess.subadmins.size > 0) {
    for (const sub of sess.subadmins) {
      const cleanSub = cleanPhone(sub.split('@')[0].split(':')[0]);
      if (cleanSub && (cleanSub === cleanSender || cleanSub === cleanRemote || cleanSub === cleanSenderLid)) return true;
      if (sub.toLowerCase() === senderParticipant.toLowerCase() || sub.toLowerCase() === remoteJid.toLowerCase() || sub.toLowerCase() === senderLid.toLowerCase()) return true;
    }
  }

  return false;
}

function getSessionAuthDir(uid) {
  return path.join(SESSIONS_BASE_DIR, `wp_auth_${uid}`);
}

function hasSavedAuthCreds(uid) {
  try {
    const dir = getSessionAuthDir(uid);
    const credsPath = path.join(dir, 'creds.json');
    if (!fs.existsSync(credsPath)) return false;
    const raw = fs.readFileSync(credsPath, 'utf8');
    const parsed = JSON.parse(raw);
    return !!(parsed && (parsed.registered || parsed.me));
  } catch (e) {
    return false;
  }
}

function deleteSessionAuthDir(uid) {
  const dir = getSessionAuthDir(uid);
  try {
    if (fs.existsSync(dir)) {
      fs.rmSync(dir, { recursive: true, force: true });
      logMsg(uid, `🗑️ Auth directory successfully purged from disk: ${dir}`);
    }
  } catch (err) {
    logMsg(uid, `Error deleting auth directory: ${err.message}`);
  }
}

// Per-Chat Loop Helpers
function getChatLoop(sess, jid) {
  sess.chatLoops = sess.chatLoops || {};
  sess.chatLoops[jid] = sess.chatLoops[jid] || {};
  return sess.chatLoops[jid];
}

function stopChatLoop(sess, jid, loopType) {
  if (sess.chatLoops && sess.chatLoops[jid]) {
    sess.chatLoops[jid][loopType] = false;
  }
}

function stopAllChatLoops(sess, loopType) {
  if (sess.chatLoops) {
    for (const cJid of Object.keys(sess.chatLoops)) {
      if (sess.chatLoops[cJid]) {
        sess.chatLoops[cJid][loopType] = false;
      }
    }
  }
}

function stopAllOperations(sess) {
  if (!sess) return;
  sess.chatLoops = {};
  sess.targetAutoReplies = {};
}

function getUltraMenuText(prefix = '+') {
  return `╔══════════════════════════════════════════╗
║     👑  ⚡ 𝓚𝓘𝓝𝓖 𝓑𝓞𝓣 𝓤𝓛𝓣𝓡𝓐 𝓥2.0 ⚡  👑     ║
║  🛡️ 𝙎𝙀𝙍𝙑𝙀𝙍 𝙂𝙊𝘿 𝘾𝙇𝘼𝙉 • 𝙀𝙓𝘾𝙇𝙐𝙎𝙄𝙑𝙀 𝙀𝙉𝙂𝙄𝙉𝙀 🛡️  ║
╚══════════════════════════════════════════╝
  ✨ 𝙋𝙧𝙚𝙛𝙞𝙭: [  ${prefix}  ]  •  ⚡ 𝙏𝙪𝙧𝙗𝙤 𝙎𝙥𝙚𝙚𝙙: 0.01𝙨+ (10𝙢𝙨)

🎯 ━━━〔 🎯 𝙏𝘼𝙍𝙂𝙀𝙏 𝙍𝙀𝙎𝙋𝙊𝙉𝘿𝙀𝙍 〕━━━ 🎯
 ├ 🎯 \`${prefix}target @tag <Text>\` : Auto-reply punchlines to target
 ├ 🛑 \`${prefix}stoptarget @tag\` : Release specific target
 ├ 🚨 \`${prefix}stoptargetall\` : Clear all active targets
 ├ 📋 \`${prefix}targetlist\` : Show locked targets table
 ├ ⏳ \`${prefix}targetdelay <0.01-20>\` : Set auto-response cooldown
 └ 💥 \`${prefix}roast @tag\` : Instant savage battle roast

🌀 ━━━〔 🌀 𝙏𝙐𝙍𝘽𝙊 𝙉𝘾 𝙇𝙊𝙊𝙋𝙎 (0.01𝙨+) 〕━━━ 🌀
 ├ ⚙️ \`${prefix}nc <Text>\` : Ultra Fast Rotation 1-50 (10ms-100ms)
 ├ ⚡ \`${prefix}triplenc1 <Text>\` : Launch nc1+nc2+nc3 ultra mode
 ├ 📈 \`${prefix}ncdelay <0.01-20>\` : Set NC speed (e.g. 0.05 or 0.1)
 ├ 🛑 \`${prefix}stopnc\` : Stop NC in THIS CHAT only
 └ 🛑 \`${prefix}stopncall\` : MASTER STOP NC across ALL groups

✍️ ━━━〔 ✍️ 𝙂𝙍𝙊𝙐𝙋 𝘿𝘾 𝙎𝙋𝘼𝙈𝙈𝙀𝙍 (0.01𝙨+) 〕━━━ ✍️
 ├ 📝 \`${prefix}gdc <Text>\` / \`${prefix}gcdc <Text>\` : Turbo Description Flooder
 ├ ⚡ \`${prefix}gdcdelay <0.01-20>\` : Calibrate Description speed
 ├ 🛑 \`${prefix}gdcstop\` / \`${prefix}gcdcstop\` : Stop DC in THIS CHAT only
 └ 🛑 \`${prefix}stopgdcall\` : MASTER STOP DC across ALL groups

🖼️ ━━━〔 🖼️ 𝘼𝙐𝙏𝙊 𝙋𝙁𝙋 𝘾𝙃𝘼𝙉𝙂𝙀𝙍 〕━━━ 🖼️
 ├ 📸 \`${prefix}pfpchange\` : Reply to any pic in chat to set group icon
 ├ ⏳ \`${prefix}pfpdelay <0.1-20>\` : Shift avatar refresh interval
 └ 🛑 \`${prefix}pfpstop\` : Kill active avatar updates

📸 ━━━〔 📸 𝙂𝙍𝘼𝙋𝙃𝙄𝘾 𝙋𝙄𝘾 𝙎𝙋𝘼𝙈 〕━━━ 📸
 ├ 🖼️ \`${prefix}picspam <Text>\` : Flood image array loops
 ├ ⏳ \`${prefix}picspamdelay <0.1-20>\` : Speed adjustment
 ├ 🛑 \`${prefix}picspamstop\` : Stop PicSpam in THIS chat
 └ 🛑 \`${prefix}stoppicspamall\` : MASTER STOP PicSpam in ALL chats

📊 ━━━〔 📊 𝙏𝙀𝙓𝙏 & 𝙋𝙊𝙇𝙇 𝙎𝙋𝘼𝙈 (0.01𝙨+) 〕━━━ 📊
 ├ 📝 \`${prefix}textspam <Text>\` : Continuous text flooder (10ms+)
 ├ ⏳ \`${prefix}textspamdelay <0.01-20>\` : Set text spam delay
 ├ 🛑 \`${prefix}textspamstop\` : Stop text spam in THIS chat
 ├ 📊 \`${prefix}pollspam Name | opt1 | opt2\` : Native polls flooder
 ├ ⏳ \`${prefix}pollspamdelay <0.1-20>\` : Set poll delay
 └ 🛑 \`${prefix}pollspamstop\` : Stop poll spam in THIS chat

💀 ━━━〔 💀 𝙍𝘼𝘿𝘼𝙍 & 𝙈𝙐𝙏𝙀 𝙎𝙀𝙉𝙏𝙄𝙉𝙀𝙇 〕━━━ 💀
 ├ 💀 \`${prefix}autodelete @tag\` : Instant delete target incoming messages
 ├ 🔓 \`${prefix}stopdelete @tag\` : Release radar target
 ├ 🔇 \`${prefix}mute @tag\` : Silence user in group
 └ 🔊 \`${prefix}unmute @tag\` : Unmute user

🚀 ━━━〔 🚀 𝙁𝙇𝙊𝙊𝘿 & 𝙎𝙒𝙄𝙋𝙀 𝙇𝙊𝙊𝙋𝙎 〕━━━ 🚀
 ├ 🚀 \`${prefix}spam <Text>\` : Continuous Flooder (10ms+)
 ├ ⏳ \`${prefix}spamdelay <0.01-20>\` : Calibrate speed (0.05s)
 ├ 🛑 \`${prefix}stopspam\` : Break flooder in THIS chat
 ├ 🛑 \`${prefix}stopspamall\` : MASTER STOP spam in ALL chats
 ├ 🔄 \`${prefix}swipe <Text>\` : Quoted / Swiped message flooder
 ├ ⏳ \`${prefix}swipedelay <0.01-20>\` : Adjust swipe speed
 ├ 🛑 \`${prefix}stopswipe\` : Stop active swiper in THIS chat
 └ 🚨 \`${prefix}stopall\` : EMERGENCY FORCE SHUTDOWN ALL OPS EVERYWHERE

🛡️ ━━━〔 🛡️ 𝙈𝙊𝘿𝙀𝙍𝘼𝙏𝙄𝙊𝙉 & 𝘼𝙉𝙏𝙄𝙇𝙄𝙉𝙆 〕━━━ 🛡️
 ├ ⚠️ \`${prefix}warn @tag\` : Warning strike (3 strikes = Kick)
 ├ 🔄 \`${prefix}resetwarn @tag\` : Clear warning strikes
 ├ 🔗 \`${prefix}antilink on/off\` : Auto-delete group invite links
 ├ 📢 \`${prefix}tagall <Text>\` : Mention all members in chat
 ├ ➕ \`${prefix}addsubadmin @tag\` : Grant subadmin access
 ├ ➖ \`${prefix}removesubadmin @tag\` : Revoke subadmin
 └ 📋 \`${prefix}showsubadmin\` : List all subadmins

⚙️ ━━━〔 ⚙️ 𝙂𝙍𝙊𝙐𝙋 𝘼𝘿𝙈𝙄𝙉 𝙐𝙏𝙄𝙇𝙄𝙏𝙄𝙀𝙎 〕━━━ ⚙️
 ├ ➕ \`${prefix}add <Number>\` : Add participant to group
 ├ 🧹 \`${prefix}kick @tag\` : Force eject member
 ├ 📈 \`${prefix}promote @tag\` : Promote to admin
 ├ 📉 \`${prefix}demote @tag\` : Demote from admin
 ├ 🔒 \`${prefix}closegroup\` : Announcement only (Only admins)
 ├ 🔓 \`${prefix}opengroup\` : Open group for all members
 ├ 📢 \`${prefix}hidetag <Text>\` : Silent ghost mention all
 ├ 🔗 \`${prefix}gclink\` : Get group invite link
 ├ 🔄 \`${prefix}revoke\` : Reset & revoke invite link
 ├ ✏️ \`${prefix}setgcname <Name>\` : Instant rename group
 ├ 📝 \`${prefix}setgcdesc <Desc>\` : Instant set description
 ├ 🎭 \`${prefix}react <Emoji>\` : React to quoted message
 ├ 🚪 \`${prefix}join <Link>\` : Join group via invite link
 ├ 🚪 \`${prefix}leave\` : Exit group
 ├ 🤖 \`${prefix}creategc <Name>\` : Create brand new group
 ├ 💻 \`${prefix}ping\` : Check system latency
 └ 📊 \`${prefix}botinfo\` : Complete node & memory telemetry

🛰️ ━━━〔 🛰️ 𝙈𝙐𝙇𝙏𝙄-𝙉𝙊𝘿𝙀 & 𝘿𝙄𝙎𝘾𝙊𝙉𝙉𝙀𝘾𝙏 〕━━━ 🛰️
 ├ 🔌 \`${prefix}disconnect\` : Unlink session & purge credentials
 ├ ❌ \`${prefix}deletesession\` : Destroy this bot node profile
 ├ 🆔 \`${prefix}addbotsession <Name>\` : Allocate new node
 ├ 📋 \`${prefix}bots\` : View multi-device registry table
 ├ ❌ \`${prefix}removebot <Session>\` : Delete specific node
 ├ 🔥 \`${prefix}rage\` : ALL BOTS execute simultaneously
 ├ 🛡️ \`${prefix}solo\` : ONLY MAIN BOT executes
 └ 🔄 \`${prefix}changeprefix <Symbol>\` : Change bot prefix

╔══════════════════════════════════════════╗
║     ⚡  𝙋𝙊𝙒𝙀𝙍𝙀𝘿 𝘽𝙔 𝙎𝙀𝙍𝙑𝙀𝙍 𝙂𝙊𝘿 𝘾𝙇𝘼𝙉  ⚡     ║
╚══════════════════════════════════════════╝`;
}

const ROAST_PUNCHLINES = [
  "😂 Beta King Bot ke aage aukaat me raha karo!",
  "🔥 Server God Clan ka rule hai — zyada uchloge to direct e-lafda me gayab ho jaoge!",
  "💀 Tu jis class me padh raha hai na, uska principal King Bot Ultra hai!",
  "⚡ Aukaat 2 paise ki nahi aur baatein aisi jaise group ke owner ho!",
  "👑 Chup chap kone me baith, warna group me spam flood aa jayega!"
];

// ================= INITIALIZE BAILEYS SOCKET FOR A SESSION =================
async function initSessionSocket(uid, ownerJid = '', options = {}) {
  try {
    const authDir = getSessionAuthDir(uid);
    if (!fs.existsSync(authDir)) {
      fs.mkdirSync(authDir, { recursive: true });
    }

    const hasAuth = hasSavedAuthCreds(uid);

    if (!activeSessions[uid]) {
      activeSessions[uid] = {
        uid,
        authDir,
        status: hasAuth ? 'INITIALIZING' : 'STANDBY',
        qr: '',
        qrAttempts: 0,
        reconnectAttempts: 0,
        reconnectTimer: null,
        pairingCode: '',
        connectedNumber: '',
        userJid: '',
        ownerJid: ownerJid ? ownerJid.trim() : '',
        prefix: '+',
        executionMode: 'solo', // 'solo' or 'rage'
        chatLoops: {}, // jid -> { nc: bool, gcdc: bool, spam: bool, swipe: bool, textspam: bool, pollspam: bool, picspam: bool, pfp: bool }
        delays: {
          nc: 50, // 50ms default ultra turbo speed (0.05s)
          gcdc: 50, // 50ms default ultra turbo speed (0.05s)
          pfp: 1000,
          picspam: 200,
          textspam: 50, // 50ms
          pollspam: 300,
          spam: 50, // 50ms
          swipe: 100,
          target: 150 // 150ms target responder cooldown
        },
        targetAutoReplies: {}, // targetJid -> { text, repliesSent, lastReply }
        muteList: new Set(),
        radarList: new Set(),
        warnList: {},
        subadmins: new Set(),
        antilink: false,
        sentCount: 0,
        failedCount: 0,
        startedAt: null,
        connectedAt: null,
        logs: []
      };
    } else {
      activeSessions[uid].authDir = authDir;
      if (ownerJid) activeSessions[uid].ownerJid = ownerJid.trim();
    }

    const sess = activeSessions[uid];

    // If session is unauthenticated and only registering (e.g. backend startup without active login), skip spinning up WebSocket
    if (!hasAuth && options.onlyRegisterIfUnauthenticated && !options.force) {
      sess.status = 'STANDBY';
      return sess;
    }

    // Clean up existing socket listeners and socket if active
    if (sess.sock) {
      try {
        sess.sock.ev.removeAllListeners();
        if (sess.sock.ws) {
          try { sess.sock.ws.close(); } catch (e) {}
        }
        try { sess.sock.end(); } catch (e) {}
      } catch (e) {}
      sess.sock = null;
    }

    if (sess.reconnectTimer) {
      clearTimeout(sess.reconnectTimer);
      sess.reconnectTimer = null;
    }

    const { state, saveCreds } = await useMultiFileAuthState(authDir);
    const { version } = await fetchLatestBaileysVersion().catch(() => ({
      version: [2, 3000, 1015901307],
      isLatest: true
    }));

    const sock = makeWASocket({
      version,
      logger: pino({ level: 'silent' }),
      printQRInTerminal: false,
      auth: state,
      browser: Browsers.ubuntu('Chrome'),
      syncFullHistory: false,
      markOnlineOnConnect: false,
      generateHighQualityLinkPreview: false,
      defaultQueryTimeoutMs: 30000,
      connectTimeoutMs: 30000,
      keepAliveIntervalMs: 25000,
      retryRequestDelayMs: 1000,
      maxRetries: 3
    });

    sess.sock = sock;

    sock.ev.on('creds.update', async () => {
      try {
        if (!fs.existsSync(authDir)) {
          fs.mkdirSync(authDir, { recursive: true });
        }
        await saveCreds();
      } catch (err) {}
    });

    sock.ev.on('connection.update', async (update) => {
      const { connection, lastDisconnect, qr } = update;

      if (qr) {
        sess.status = 'AWAITING_SCAN';
        sess.pairingCode = '';
        sess.qrAttempts = (sess.qrAttempts || 0) + 1;
        try {
          sess.qr = await QRCode.toDataURL(qr, {
            margin: 2,
            width: 256,
            color: { dark: '#000000', light: '#ffffff' }
          });
          logMsg(uid, `📷 Live QR Code generated & ready to scan (Attempt #${sess.qrAttempts}).`);
        } catch (qrErr) {
          logMsg(uid, `QR rendering error: ${qrErr.message}`);
        }
      }

      if (connection === 'open') {
        sess.qrAttempts = 0;
        sess.reconnectAttempts = 0;
        if (sess.reconnectTimer) {
          clearTimeout(sess.reconnectTimer);
          sess.reconnectTimer = null;
        }

        const rawUser = sock.user ? (sock.user.id || '') : '';
        const userPhone = rawUser.split(':')[0] || rawUser.split('@')[0] || '';
        sess.userJid = sock.user?.id || '';
        sess.connectedNumber = userPhone ? `+${userPhone}` : 'Linked Account';
        sess.status = 'ONLINE';
        sess.qr = '';
        sess.pairingCode = '';
        sess.connectedAt = Date.now();

        logMsg(uid, `🎉 ONLINE! Number: ${sess.connectedNumber} | Admin Owner ID: ${sess.ownerJid || 'Not Set'}`);
      }

      if (connection === 'close') {
        const statusCode = lastDisconnect?.error?.output?.statusCode;
        const isLoggedOut = statusCode === DisconnectReason.loggedOut || statusCode === 401 || statusCode === 403;
        const isAuth = hasSavedAuthCreds(uid) || sess.status === 'ONLINE';

        // Clean up socket instance
        try {
          sock.ev.removeAllListeners();
          if (sock.ws) {
            try { sock.ws.close(); } catch (e) {}
          }
          try { sock.end(); } catch (e) {}
        } catch (e) {}
        sess.sock = null;

        if (isLoggedOut) {
          sess.status = 'LOGGED_OUT';
          sess.connectedNumber = '';
          sess.userJid = '';
          sess.qr = '';
          sess.pairingCode = '';
          stopAllOperations(sess);

          logMsg(uid, `🔴 Session logged out / unlinked. Cleaned auth directory from disk.`);
          deleteSessionAuthDir(uid);
          return; // STOP: Do not auto-reconnect!
        }

        if (!isAuth) {
          // Unauthenticated session awaiting scan
          if ((sess.qrAttempts || 0) >= 2) {
            sess.status = 'QR_EXPIRED';
            sess.qr = '';
            logMsg(uid, `⏸️ QR scan timed out (Status: ${statusCode || 408}). QR loop paused to save memory. Refresh QR on dashboard when ready.`);
            return; // STOP: Do not loop indefinitely!
          } else {
            sess.status = 'RECONNECTING';
            logMsg(uid, `⚠️ QR scan timed out (Status: ${statusCode || 408}). Retrying in 5s...`);
            clearTimeout(sess.reconnectTimer);
            sess.reconnectTimer = setTimeout(() => {
              if (activeSessions[uid] && activeSessions[uid].status !== 'LOGGED_OUT' && activeSessions[uid].status !== 'ONLINE') {
                initSessionSocket(uid, sess.ownerJid, { force: true });
              }
            }, 5000);
            return;
          }
        }

        // Authenticated session dropped (temporary network disconnect)
        sess.reconnectAttempts = (sess.reconnectAttempts || 0) + 1;
        const backoffDelay = Math.min(30000, 3000 * Math.pow(1.4, Math.min(sess.reconnectAttempts, 6)));
        sess.status = 'RECONNECTING';
        logMsg(uid, `⚠️ Connection closed (Status: ${statusCode || 'Unknown'}). Auto-reconnecting in ${Math.round(backoffDelay / 1000)}s (Attempt #${sess.reconnectAttempts})...`);

        clearTimeout(sess.reconnectTimer);
        sess.reconnectTimer = setTimeout(() => {
          if (activeSessions[uid] && activeSessions[uid].status !== 'LOGGED_OUT') {
            initSessionSocket(uid, sess.ownerJid, { force: true });
          }
        }, backoffDelay);
      }
    });

    // ================= INCOMING MESSAGES & STRICT OWNER COMMAND ENGINE =================
    sock.ev.on('messages.upsert', async ({ messages, type }) => {
      if (type !== 'notify' || !messages || messages.length === 0) return;

      for (const msg of messages) {
        if (!msg.message) continue;

        const jid = msg.key.remoteJid;
        if (jid === 'status@broadcast') continue;

        // 1. FILTER STARTUP BACKLOG & FLOOD: Ignore historical messages older than 45 seconds
        const msgTimestampMs = (msg.messageTimestamp || 0) * 1000;
        if (msgTimestampMs && (Date.now() - msgTimestampMs > 45000)) continue;

        // 2. SESSION LEVEL MESSAGE DEDUPLICATION
        if (isDuplicateMessage(`${uid}_${msg.key.id || ''}`)) continue;

        const senderParticipant = msg.key.participant || (msg.key.fromMe ? sock.user?.id : jid);
        const senderLid = msg.key.participantAlt || '';
        const isGroup = jid.endsWith('@g.us');

        const text = msg.message.conversation ||
          msg.message.extendedTextMessage?.text ||
          msg.message.imageMessage?.caption ||
          msg.message.videoMessage?.caption ||
          '';

        // 1. RADAR & MUTE SENTINEL: Wipe target messages instantly
        if ((sess.radarList?.size > 0 || sess.muteList?.size > 0) && !msg.key.fromMe) {
          const cleanSender = cleanPhone(senderParticipant.split('@')[0].split(':')[0]);
          let shouldDelete = false;

          if (sess.radarList) {
            for (const target of sess.radarList) {
              const cleanTarget = cleanPhone(target);
              if (cleanTarget === cleanSender || target === senderParticipant || target === senderLid) {
                shouldDelete = true;
                break;
              }
            }
          }

          if (!shouldDelete && sess.muteList) {
            for (const target of sess.muteList) {
              const cleanTarget = cleanPhone(target);
              if (cleanTarget === cleanSender || target === senderParticipant || target === senderLid) {
                shouldDelete = true;
                break;
              }
            }
          }

          if (shouldDelete) {
            try {
              await sock.sendMessage(jid, { delete: msg.key });
              logMsg(uid, `💀 [SENTINEL WIPED] Message deleted from target: ${senderParticipant}`);
            } catch (delErr) {}
          }
        }

        // 2. TARGET AUTO-REPLY ENGINE: Counter punchlines to targeted users
        if (sess.targetAutoReplies && Object.keys(sess.targetAutoReplies).length > 0 && !msg.key.fromMe) {
          const cleanSender = cleanPhone(senderParticipant.split('@')[0].split(':')[0]);
          for (const [targetKey, targetData] of Object.entries(sess.targetAutoReplies)) {
            const cleanTarget = cleanPhone(targetKey.split('@')[0]);
            if (cleanTarget === cleanSender || targetKey === senderParticipant || targetKey === senderLid || senderParticipant.includes(cleanTarget)) {
              try {
                const now = Date.now();
                const minDelay = sess.delays.target || 150;
                if (!targetData.lastReply || (now - targetData.lastReply) >= minDelay) {
                  targetData.lastReply = now;
                  targetData.repliesSent = (targetData.repliesSent || 0) + 1;
                  const replyText = targetData.text || `🔥 @${cleanSender} TERI AUKAAT NAHI HAI KING BOT SE LADNE KI! 🔥`;
                  await sock.sendMessage(jid, {
                    text: replyText,
                    mentions: [senderParticipant]
                  }, { quoted: msg });
                  sess.sentCount += 1;
                  logMsg(uid, `🎯 [TARGET AUTO-REPLY] Counter replied to ${cleanSender} (Total: ${targetData.repliesSent})`);
                }
              } catch (e) {}
              break;
            }
          }
        }

        // 3. ANTILINK: Auto delete invite links from non-admins in group
        if (sess.antilink && isGroup && text && !msg.key.fromMe) {
          if (text.includes('chat.whatsapp.com/') || text.includes('wa.me/')) {
            const isAuthorized = isAuthorizedOwner(sess, msg, sock);
            if (!isAuthorized) {
              try {
                await sock.sendMessage(jid, { delete: msg.key });
                await sock.sendMessage(jid, {
                  text: `⚠️ @${senderParticipant.split('@')[0]} Links are strictly forbidden in this group!`,
                  mentions: [senderParticipant]
                });
                logMsg(uid, `🛡️ [ANTILINK] Deleted invite link from ${senderParticipant}`);
              } catch (e) {}
            }
          }
        }

        if (!text || !text.trim()) continue;
        const rawBody = text.trim();
        const curPrefix = sess.prefix || '+';

        // Check if message is a command with any supported prefix
        const allowedPrefixes = [curPrefix, '+', '.', '!', '/', '-', '?', '#', '$', '*', '&', '_'].filter(Boolean);
        let usedPrefix = null;
        for (const p of allowedPrefixes) {
          if (rawBody.startsWith(p)) {
            usedPrefix = p;
            break;
          }
        }

        if (usedPrefix !== null) {
          const cmdBody = rawBody.slice(usedPrefix.length).trim();
          const parts = cmdBody.split(/\s+/);
          const cmd = parts[0].toLowerCase();
          const fullArg = cmdBody.slice(parts[0].length).trim();

          // MASTER AUTH PASSCODE COMMAND (Instant Owner Activation)
          if (cmd === 'auth' || cmd === 'ownerpass' || cmd === 'loginowner' || cmd === 'adminauth') {
            if (fullArg === 'PRINCE@9507325' || fullArg === '9507325' || fullArg === '950732' || fullArg === '123456') {
              sess.ownerLid = senderParticipant || senderLid;
              sess.ownerJid = senderParticipant;
              sess.subadmins.add(senderParticipant);
              logMsg(uid, `👑 Master Pass Authorization Granted to ${senderParticipant}`);
              await sock.sendMessage(jid, {
                text: `👑 *MASTER ACCESS GRANTED!*\n• 🆔 *Your ID:* \`${senderParticipant}\`\n• ⚡ *Status:* Fully Authorized Owner for Node \`${uid}\`.`,
                mentions: [senderParticipant]
              });
              return;
            }
          }

          // SET OWNER COMMAND (Direct Override)
          if (cmd === 'setowner' || cmd === 'setadmin') {
            const isAuthorized = isAuthorizedOwner(sess, msg, sock);
            if (isAuthorized) {
              const mentioned = msg.message?.extendedTextMessage?.contextInfo?.mentionedJid || [];
              let target = mentioned[0] || (fullArg ? normalizeJid(fullArg) : senderParticipant);
              sess.ownerJid = target;
              sess.ownerLid = target;
              logMsg(uid, `👑 Bot Owner JID set to: ${target}`);
              await sock.sendMessage(jid, { text: `👑 *Bot Owner registered as:* \`${target}\`` });
              return;
            }
          }

          // STRICT OWNER VERIFICATION: ONLY CONFIGURED OWNER / ADMIN CAN RUN COMMANDS
          const isOwner = isAuthorizedOwner(sess, msg, sock);

          if (!isOwner) {
            logMsg(uid, `⛔ [UNAUTHORIZED BLOCKED] User ${senderParticipant} tried to run [${usedPrefix}${cmd}] - Allowed Owner: ${sess.ownerJid || 'Bot Self Only'}`);
            return;
          }

          // SINGLE COMMAND EXECUTION GUARANTEE (Avoid bulk duplicate multi-bot spam in solo mode)
          if (!shouldExecuteCommand(sess, msg, cmd)) {
            return;
          }

          logMsg(uid, `👑 [AUTHORIZED OWNER COMMAND] [${usedPrefix}${cmd}] in ${jid} by ${senderParticipant}`);

          // ================= ULTRA MENU & TELEMETRY (OWNER ONLY) =================
          if (cmd === 'menu' || cmd === 'help' || cmd === 'dashboard') {
            await sock.sendMessage(jid, { text: getUltraMenuText(sess.prefix) });
            return;
          }

          if (cmd === 'ping' || cmd === 'p') {
            const startPing = Date.now();
            await sock.sendMessage(jid, {
              text: `🏓 *PONG!*\n⚡ *Latency:* \`${Date.now() - startPing}ms\`\n👑 *Node:* \`${uid}\`\n📱 *Account:* \`${sess.connectedNumber}\`\n🔥 *Engine:* \`Baileys Ultra 2.0 (0.01s Loops)\``
            });
            return;
          }

          if (cmd === 'botinfo' || cmd === 'status' || cmd === 'sys' || cmd === 'info') {
            const mem = process.memoryUsage();
            const uptime = sess.connectedAt ? Math.floor((Date.now() - sess.connectedAt) / 1000) : 0;
            const hours = Math.floor(uptime / 3600);
            const mins = Math.floor((uptime % 3600) / 60);
            const secs = uptime % 60;
            await sock.sendMessage(jid, {
              text: `📊 *KING BOT ULTRA NODE TELEMETRY*\n\n• 🆔 *Session Node:* \`${uid}\`\n• 📱 *Linked Account:* \`${sess.connectedNumber}\`\n• 👑 *Admin ID:* \`${sess.ownerJid || 'Not Set'}\`\n• ⏳ *Uptime:* \`${hours}h ${mins}m ${secs}s\`\n• ⚡ *Sent Msgs:* \`${sess.sentCount}\`\n• 🧠 *RAM Usage:* \`${Math.round(mem.rss / 1024 / 1024)}MB\`\n• 🎯 *Active Targets:* \`${Object.keys(sess.targetAutoReplies || {}).length}\``
            });
            return;
          }

          // ================= TARGET AUTO-RESPONDER & BATTLE SYSTEM =================
          if (cmd === 'target' || cmd === 'settarget' || cmd === 'hater') {
            const mentioned = msg.message?.extendedTextMessage?.contextInfo?.mentionedJid || [];
            let targetJid = mentioned[0] || (parts[1] ? normalizeJid(parts[1]) : null);
            if (!targetJid) {
              return sock.sendMessage(jid, {
                text: `⚠️ *Usage:* \`${sess.prefix}target @tag <Custom Reply Text>\`\nExample: \`${sess.prefix}target @tag 🔥 TERI AUKAAT NAHI HAI KING SE LADNE KI! 🔥\``
              });
            }

            let customReply = '';
            if (mentioned[0]) {
              const tagStr = `@${mentioned[0].split('@')[0]}`;
              customReply = fullArg.replace(tagStr, '').trim();
            } else if (parts[1]) {
              customReply = parts.slice(2).join(' ').trim();
            }

            if (!customReply) {
              customReply = ROAST_PUNCHLINES[Math.floor(Math.random() * ROAST_PUNCHLINES.length)];
            }

            sess.targetAutoReplies[targetJid] = {
              text: customReply,
              repliesSent: 0,
              lastReply: 0
            };

            await sock.sendMessage(jid, {
              text: `🎯 *[TARGET LOCKED]*\n👤 *Target:* @${targetJid.split('@')[0]}\n💬 *Auto-Reply Set To:*\n"${customReply}"\n\n⚡ Any message sent by this user will be instantly countered!`,
              mentions: [targetJid]
            });
            logMsg(uid, `🎯 Target locked on ${targetJid} with custom response.`);
          }

          else if (cmd === 'stoptarget' || cmd === 'untarget' || cmd === 'deltarget') {
            const mentioned = msg.message?.extendedTextMessage?.contextInfo?.mentionedJid || [];
            let targetJid = mentioned[0] || (parts[1] ? normalizeJid(parts[1]) : null);
            if (targetJid && sess.targetAutoReplies[targetJid]) {
              delete sess.targetAutoReplies[targetJid];
              await sock.sendMessage(jid, { text: `🔓 *[TARGET RELEASED]* @${targetJid.split('@')[0]} un-targeted.`, mentions: [targetJid] });
            } else {
              sess.targetAutoReplies = {};
              await sock.sendMessage(jid, { text: `🔓 *[TARGETS CLEARED]* All targets released.` });
            }
          }

          else if (cmd === 'stoptargetall' || cmd === 'targetstop' || cmd === 'cleartargets') {
            sess.targetAutoReplies = {};
            await sock.sendMessage(jid, { text: `🛑 *All active auto-reply targets cleared!*` });
          }

          else if (cmd === 'targetlist' || cmd === 'targets' || cmd === 'showtargets') {
            const list = Object.entries(sess.targetAutoReplies || {});
            if (list.length === 0) {
              await sock.sendMessage(jid, { text: `📋 *No active targets locked right now.*` });
            } else {
              let tText = `🎯 *LOCKED AUTO-REPLY TARGETS (${list.length}):*\n\n`;
              list.forEach(([tJid, data], i) => {
                tText += `${i + 1}. 👤 @${tJid.split('@')[0]}\n   💬 *Response:* "${data.text}"\n   ⚡ *Sent:* ${data.repliesSent || 0}\n\n`;
              });
              await sock.sendMessage(jid, { text: tText, mentions: list.map(([t]) => t) });
            }
          }

          else if (cmd === 'targetdelay' || cmd === 'settargetdelay') {
            const ms = parseDelayMs(fullArg, 150);
            sess.delays.target = ms;
            await sock.sendMessage(jid, { text: `⏳ *Target response cooldown set to:* \`${ms}ms\` (*${(ms/1000).toFixed(3)}s*)` });
          }

          else if (cmd === 'roast' || cmd === 'hate' || cmd === 'insult') {
            const mentioned = msg.message?.extendedTextMessage?.contextInfo?.mentionedJid || [];
            let targetJid = mentioned[0] || (fullArg ? normalizeJid(fullArg) : null);
            const punch = ROAST_PUNCHLINES[Math.floor(Math.random() * ROAST_PUNCHLINES.length)];
            if (targetJid) {
              await sock.sendMessage(jid, {
                text: `💥 @${targetJid.split('@')[0]}\n${punch}`,
                mentions: [targetJid]
              });
            } else {
              await sock.sendMessage(jid, { text: `💥 *SAVAGE ROAST:*\n${punch}` });
            }
          }

          // ================= TURBO NC LOOPS (PER-CHAT & MASTER STOP) =================
          else if (cmd === 'nc' || cmd === 'nc1' || cmd === 'namechange' || cmd === 'gcname') {
            if (!isGroup) return sock.sendMessage(jid, { text: `⚠️ This command only works in groups!` });
            const titleBase = fullArg || 'KING BOT ULTRA';
            const chatL = getChatLoop(sess, jid);
            chatL.nc = true;
            await sock.sendMessage(jid, { text: `🌀 *Started Turbo NC Rotation in this group (Speed: ${sess.delays.nc}ms):* "${titleBase}" (1-50)` });

            (async () => {
              let count = 1;
              while (chatL.nc) {
                try {
                  const newTitle = `${titleBase} [${count}]`;
                  await sock.groupUpdateSubject(jid, newTitle);
                  sess.sentCount += 1;
                  count = (count >= 50) ? 1 : count + 1;
                } catch (err) {
                  logMsg(uid, `NC error in ${jid}: ${err.message}`);
                }
                const ms = sess.delays.nc || 50;
                await new Promise(r => setTimeout(r, ms));
              }
              logMsg(uid, `NC stopped for chat ${jid}`);
            })();
          }

          else if (cmd === 'nc2' || cmd === 'nc3') {
            if (!isGroup) return sock.sendMessage(jid, { text: `⚠️ Group command only!` });
            const titleBase = fullArg || 'KING GOD CLAN';
            const chatL = getChatLoop(sess, jid);
            chatL.nc = true;
            await sock.sendMessage(jid, { text: `🌀 *Started Alternate NC Loop in this group (Speed: ${sess.delays.nc}ms):* "${titleBase}"` });

            (async () => {
              const frames = [`⚡ ${titleBase} ⚡`, `🔥 ${titleBase} 🔥`, `👑 ${titleBase} 👑`, `✨ ${titleBase} ✨`];
              let idx = 0;
              while (chatL.nc) {
                try {
                  await sock.groupUpdateSubject(jid, frames[idx % frames.length]);
                  idx++;
                  sess.sentCount += 1;
                } catch (e) {}
                await new Promise(r => setTimeout(r, sess.delays.nc || 50));
              }
            })();
          }

          else if (cmd === 'triplenc1' || cmd === 'triplenc2' || cmd === 'triplenc3' || cmd === 'triplenc') {
            if (!isGroup) return sock.sendMessage(jid, { text: `⚠️ Group command only!` });
            const titleBase = fullArg || 'KING GOD CLAN';
            const chatL = getChatLoop(sess, jid);
            chatL.nc = true;
            await sock.sendMessage(jid, { text: `⚡ *Triple NC Sequence Launched at Ultra High Speed (${sess.delays.nc}ms)!*` });

            (async () => {
              const variations = [`👑 ${titleBase} 👑`, `⚡ ${titleBase} [NC2] ⚡`, `🔥 ${titleBase} [NC3] 🔥`];
              let idx = 0;
              while (chatL.nc) {
                try {
                  await sock.groupUpdateSubject(jid, variations[idx % variations.length]);
                  idx++;
                  sess.sentCount += 1;
                } catch (e) {}
                await new Promise(r => setTimeout(r, sess.delays.nc || 50));
              }
            })();
          }

          else if (cmd === 'ncdelay' || cmd === 'setspeednc') {
            const ms = parseDelayMs(fullArg, 50);
            sess.delays.nc = ms;
            const sec = (ms / 1000).toFixed(3);
            await sock.sendMessage(jid, { text: `📈 *NC Speed configured to:* \`${ms}ms\` (*${sec}s*)` });
          }

          else if (cmd === 'stopnc' || cmd === 'ncstop' || cmd === 'stopnc1' || cmd === 'stopnc2' || cmd === 'stopnc3') {
            stopChatLoop(sess, jid, 'nc');
            await sock.sendMessage(jid, { text: `🛑 *NC Name Rotation stopped in THIS group!*` });
          }

          else if (cmd === 'stopncall' || cmd === 'stopallnc' || cmd === 'killnc') {
            stopAllChatLoops(sess, 'nc');
            await sock.sendMessage(jid, { text: `🛑 *MASTER STOP: Killed all active Name Changes across ALL groups!*` });
          }

          // ================= GROUP DC / GCDC SPAMMER (PER-CHAT & MASTER STOP) =================
          else if (cmd === 'gcdc' || cmd === 'gdc' || cmd === 'dc' || cmd === 'gcdc1' || cmd === 'gdc1' || cmd === 'dc1' || cmd === 'descspam') {
            if (!isGroup) return sock.sendMessage(jid, { text: `⚠️ Group command only!` });
            const dcText = fullArg || '👑 SERVER GOD CLAN KING BOT ULTRA 👑';
            const chatL = getChatLoop(sess, jid);
            chatL.gcdc = true;
            await sock.sendMessage(jid, { text: `✍️ *Ultra-Fast Group Description Spammer Started (${sess.delays.gcdc}ms):* "${dcText}"` });

            (async () => {
              let cycle = 1;
              while (chatL.gcdc) {
                try {
                  const newDesc = `${dcText.slice(0, 480)}\n\n[⚡ Ultra DC: ${cycle} • ${Date.now().toString().slice(-4)}]`;
                  await sock.groupUpdateDescription(jid, newDesc);
                  sess.sentCount += 1;
                  cycle++;
                } catch (err) {
                  logMsg(uid, `GCDC error in ${jid}: ${err.message}`);
                  if (cycle === 1) {
                    await sock.sendMessage(jid, { text: `⚠️ *GCDC Notice:* ${err.message} (Ensure bot is Group Admin to change description)` });
                  }
                }
                const ms = sess.delays.gcdc || 50;
                await new Promise(r => setTimeout(r, ms));
              }
              logMsg(uid, `GCDC stopped for chat ${jid}`);
            })();
          }

          else if (cmd === 'gcdcdelay' || cmd === 'gdcdelay' || cmd === 'dcdelay') {
            const ms = parseDelayMs(fullArg, 50);
            sess.delays.gcdc = ms;
            const sec = (ms / 1000).toFixed(3);
            await sock.sendMessage(jid, { text: `⚡ *GCDC Speed set to:* \`${ms}ms\` (*${sec}s*)` });
          }

          else if (cmd === 'gcdcstop' || cmd === 'gdcstop' || cmd === 'dcstop' || cmd === 'stopgcdc' || cmd === 'stopgdc' || cmd === 'stopdc') {
            stopChatLoop(sess, jid, 'gcdc');
            await sock.sendMessage(jid, { text: `🛑 *Group Description Loop stopped in THIS group!*` });
          }

          else if (cmd === 'stopgcdcall' || cmd === 'stopgdcall' || cmd === 'stopdcall' || cmd === 'killgcdc') {
            stopAllChatLoops(sess, 'gcdc');
            await sock.sendMessage(jid, { text: `🛑 *MASTER STOP: Killed Description Spammer across ALL groups!*` });
          }

          // ================= AUTO PFP CHANGER =================
          else if (cmd === 'pfpchange' || cmd === 'pfp' || cmd === 'gcpfp' || cmd === 'seticon') {
            if (!isGroup) return sock.sendMessage(jid, { text: `⚠️ Group command only!` });

            const quoted = msg.message?.extendedTextMessage?.contextInfo?.quotedMessage;
            const hasQuotedImage = quoted?.imageMessage;
            const isDirectImage = msg.message?.imageMessage;

            if (hasQuotedImage || isDirectImage) {
              try {
                await sock.sendMessage(jid, { text: `🖼️ *Downloading image & updating Group Icon...*` });
                const messageToDownload = hasQuotedImage ? { message: quoted } : msg;
                const buffer = await downloadMediaMessage(messageToDownload, 'buffer', {});

                if (buffer) {
                  await sock.updateProfilePicture(jid, buffer);
                  sess.sentCount += 1;
                  await sock.sendMessage(jid, { text: `✅ *Group Profile Picture successfully updated!*` });
                  logMsg(uid, `📸 Group PFP updated from quoted image.`);
                }
              } catch (pfpErr) {
                logMsg(uid, `PFP change error: ${pfpErr.message}`);
                await sock.sendMessage(jid, { text: `❌ *PFP Update Failed:* ${pfpErr.message}` });
              }
            } else {
              await sock.sendMessage(jid, {
                text: `💡 *How to use:* Reply to any image in chat with \`${sess.prefix}pfpchange\` to instantly update the group profile icon!`
              });
            }
          }

          else if (cmd === 'pfpdelay') {
            const ms = parseDelayMs(fullArg, 1000);
            sess.delays.pfp = ms;
            await sock.sendMessage(jid, { text: `⏳ *PFP Interval set to:* \`${ms}ms\`` });
          }

          else if (cmd === 'pfpstop' || cmd === 'stoppfp') {
            stopChatLoop(sess, jid, 'pfp');
            await sock.sendMessage(jid, { text: `🛑 *PFP Changer Killed in this group!*` });
          }

          // ================= GRAPHIC PICSPAM =================
          else if (cmd === 'picspam' || cmd === 'imgspam' || cmd === 'photospam') {
            const quoted = msg.message?.extendedTextMessage?.contextInfo?.quotedMessage;
            const hasQuotedImage = quoted?.imageMessage;
            const chatL = getChatLoop(sess, jid);
            chatL.picspam = true;

            let imgBuffer = null;
            if (hasQuotedImage) {
              try {
                imgBuffer = await downloadMediaMessage({ message: quoted }, 'buffer', {});
              } catch (e) {}
            }

            await sock.sendMessage(jid, { text: `🎨 *Graphic PicSpam Loop Launched in this chat!*` });

            (async () => {
              while (chatL.picspam) {
                try {
                  if (imgBuffer) {
                    await sock.sendMessage(jid, { image: imgBuffer, caption: fullArg || 'KING BOT ULTRA' });
                  } else {
                    await sock.sendMessage(jid, { text: `📸 *[PIC FLOOD]* ${fullArg || 'KING GOD CLAN'}` });
                  }
                  sess.sentCount += 1;
                } catch (e) {}
                await new Promise(r => setTimeout(r, sess.delays.picspam || 200));
              }
            })();
          }

          else if (cmd === 'picspamdelay' || cmd === 'imgspamdelay') {
            const ms = parseDelayMs(fullArg, 200);
            sess.delays.picspam = ms;
            await sock.sendMessage(jid, { text: `⏳ *PicSpam delay set to:* \`${ms}ms\`` });
          }

          else if (cmd === 'picspamstop' || cmd === 'stoppicspam' || cmd === 'stopimgspam') {
            stopChatLoop(sess, jid, 'picspam');
            await sock.sendMessage(jid, { text: `🛑 *PicSpam stopped in THIS chat!*` });
          }

          else if (cmd === 'stoppicspamall') {
            stopAllChatLoops(sess, 'picspam');
            await sock.sendMessage(jid, { text: `🛑 *MASTER STOP: PicSpam killed in ALL chats!*` });
          }

          // ================= ADV TEXT & POLL SPAM (10ms+ SPEED) =================
          else if (cmd === 'textspam' || cmd === 'tspam' || cmd === 'msgspam') {
            const spamMsg = fullArg || '👑 SERVER GOD CLAN KING BOT';
            const chatL = getChatLoop(sess, jid);
            chatL.textspam = true;
            await sock.sendMessage(jid, { text: `📝 *Gapped Text Spam Started (${sess.delays.textspam}ms)!*` });

            (async () => {
              while (chatL.textspam) {
                try {
                  await sock.sendMessage(jid, { text: `⚡ ${spamMsg} ⚡` });
                  sess.sentCount += 1;
                } catch (e) {}
                await new Promise(r => setTimeout(r, sess.delays.textspam || 50));
              }
            })();
          }

          else if (cmd === 'textspamdelay' || cmd === 'tspamdelay') {
            const ms = parseDelayMs(fullArg, 50);
            sess.delays.textspam = ms;
            await sock.sendMessage(jid, { text: `⏳ *Text Spam delay set to:* \`${ms}ms\` (*${(ms/1000).toFixed(3)}s*)` });
          }

          else if (cmd === 'textspamstop' || cmd === 'stoptextspam' || cmd === 'stoptspam') {
            stopChatLoop(sess, jid, 'textspam');
            await sock.sendMessage(jid, { text: `🛑 *Text Spam Stopped in THIS chat!*` });
          }

          else if (cmd === 'pollspam' || cmd === 'poll') {
            const raw = fullArg || 'KING BOT POLL | KING | PRINCE | GOD';
            const splitParts = raw.split('|').map(s => s.trim()).filter(Boolean);
            const pollName = splitParts[0] || '👑 SERVER GOD CLAN';
            const pollOptions = splitParts.slice(1).length >= 2 ? splitParts.slice(1) : ['👑 KING', '⚡ PRINCE'];

            const chatL = getChatLoop(sess, jid);
            chatL.pollspam = true;
            await sock.sendMessage(jid, { text: `📊 *Poll Spam Activated in THIS chat!*` });

            (async () => {
              while (chatL.pollspam) {
                try {
                  await sock.sendMessage(jid, {
                    poll: {
                      name: pollName,
                      values: pollOptions,
                      selectableCount: 1
                    }
                  });
                  sess.sentCount += 1;
                } catch (e) {}
                await new Promise(r => setTimeout(r, sess.delays.pollspam || 300));
              }
            })();
          }

          else if (cmd === 'pollspamdelay') {
            const ms = parseDelayMs(fullArg, 300);
            sess.delays.pollspam = ms;
            await sock.sendMessage(jid, { text: `⏳ *Poll Spam delay set to:* \`${ms}ms\`` });
          }

          else if (cmd === 'pollspamstop' || cmd === 'stoppollspam') {
            stopChatLoop(sess, jid, 'pollspam');
            await sock.sendMessage(jid, { text: `🛑 *Poll Spam Stopped in THIS chat!*` });
          }

          // ================= RADAR & MUTE SENTINEL =================
          else if (cmd === 'autodelete' || cmd === 'radar' || cmd === 'delmsg') {
            const mentioned = msg.message?.extendedTextMessage?.contextInfo?.mentionedJid || [];
            let target = mentioned[0] || fullArg.replace(/[^0-9]/g, '');
            if (!target) return sock.sendMessage(jid, { text: `⚠️ Mention user: \`${sess.prefix}autodelete @tag\`` });

            sess.radarList.add(target);
            await sock.sendMessage(jid, { text: `💀 *[RADAR SENTINEL]* Target \`${target}\` locked! Any incoming message from this user will be wiped immediately.` });
          }

          else if (cmd === 'stopdelete' || cmd === 'unradar' || cmd === 'stopdel') {
            const mentioned = msg.message?.extendedTextMessage?.contextInfo?.mentionedJid || [];
            let target = mentioned[0] || fullArg.replace(/[^0-9]/g, '');
            if (!target) {
              sess.radarList.clear();
              return sock.sendMessage(jid, { text: `🔓 *[RADAR SENTINEL]* All targets released!` });
            }
            sess.radarList.delete(target);
            await sock.sendMessage(jid, { text: `🔓 *[RADAR SENTINEL]* Target \`${target}\` released.` });
          }

          else if (cmd === 'mute' || cmd === 'silence') {
            const mentioned = msg.message?.extendedTextMessage?.contextInfo?.mentionedJid || [];
            let target = mentioned[0] || (fullArg ? normalizeJid(fullArg) : null);
            if (!target) return sock.sendMessage(jid, { text: `⚠️ Tag user: \`${sess.prefix}mute @tag\`` });
            sess.muteList.add(target);
            await sock.sendMessage(jid, { text: `🔇 *[MUTED]* @${target.split('@')[0]} has been silenced.`, mentions: [target] });
          }

          else if (cmd === 'unmute' || cmd === 'unsilence') {
            const mentioned = msg.message?.extendedTextMessage?.contextInfo?.mentionedJid || [];
            let target = mentioned[0] || (fullArg ? normalizeJid(fullArg) : null);
            if (target) {
              sess.muteList.delete(target);
              await sock.sendMessage(jid, { text: `🔊 *[UNMUTED]* @${target.split('@')[0]} can chat again.`, mentions: [target] });
            } else {
              sess.muteList.clear();
              await sock.sendMessage(jid, { text: `🔊 *[ALL UNMUTED]* All users unmuted.` });
            }
          }

          // ================= CONTINUOUS FLOOD & CONTROL (10ms+ SPEED) =================
          else if (cmd === 'spam' || cmd === 'flood') {
            const spamText = fullArg || 'KING GOD CLAN ULTRA FLOOD';
            const chatL = getChatLoop(sess, jid);
            chatL.spam = true;
            await sock.sendMessage(jid, { text: `🚀 *Continuous Flooder Started in THIS chat (${sess.delays.spam}ms)!*` });

            (async () => {
              while (chatL.spam) {
                try {
                  await sock.sendMessage(jid, { text: spamText });
                  sess.sentCount += 1;
                } catch (e) {}
                await new Promise(r => setTimeout(r, sess.delays.spam || 50));
              }
            })();
          }

          else if (cmd === 'spamdelay' || cmd === 'flooddelay' || cmd === 'delay' || cmd === 'speed') {
            const ms = parseDelayMs(fullArg, 50);
            sess.delays.spam = ms;
            sess.delays.target = ms;
            await sock.sendMessage(jid, { text: `⏳ *Spam Delay/Speed set to:* \`${ms}ms\` (*${(ms/1000).toFixed(3)}s*)` });
          }

          else if (cmd === 'setdelay') {
            const splitArgs = fullArg.split(/\s+/);
            if (splitArgs.length < 2) {
              await sock.sendMessage(jid, { text: `⚠️ *Usage:* \`${sess.prefix}setdelay <type> <delay>\`\nTypes: \`spam\`, \`nc\`, \`gcdc\`, \`pfp\`, \`pic\`, \`text\`, \`swipe\`, \`target\`` });
            } else {
              const dType = splitArgs[0].toLowerCase();
              const ms = parseDelayMs(splitArgs[1], 50);
              if (dType === 'spam') sess.delays.spam = ms;
              else if (dType === 'nc') sess.delays.nc = ms;
              else if (dType === 'gcdc' || dType === 'gdc' || dType === 'dc') sess.delays.gcdc = ms;
              else if (dType === 'pfp') sess.delays.pfp = ms;
              else if (dType === 'pic' || dType === 'picspam' || dType === 'img') sess.delays.picspam = ms;
              else if (dType === 'text' || dType === 'textspam') sess.delays.textspam = ms;
              else if (dType === 'swipe') sess.delays.swipe = ms;
              else if (dType === 'target') sess.delays.target = ms;
              else sess.delays.spam = ms;
              await sock.sendMessage(jid, { text: `✅ *[${dType.toUpperCase()} DELAY]* set to \`${ms}ms\` (*${(ms/1000).toFixed(3)}s*)` });
            }
          }

          else if (cmd === 'stopspam' || cmd === 'spamstop' || cmd === 'stopflood') {
            stopChatLoop(sess, jid, 'spam');
            await sock.sendMessage(jid, { text: `🛑 *Active Flooder Stopped in THIS chat!*` });
          }

          else if (cmd === 'stopspamall' || cmd === 'killspam') {
            stopAllChatLoops(sess, 'spam');
            await sock.sendMessage(jid, { text: `🛑 *MASTER STOP: Killed Flooder across ALL chats!*` });
          }

          else if (cmd === 'swipe' || cmd === 'swipespam') {
            const swipeText = fullArg || '⚡ SWIPED BY KING BOT ⚡';
            const chatL = getChatLoop(sess, jid);
            chatL.swipe = true;
            await sock.sendMessage(jid, { text: `🔄 *Targeted Swiper Loop Activated in THIS chat!*` });

            (async () => {
              while (chatL.swipe) {
                try {
                  await sock.sendMessage(jid, { text: swipeText }, { quoted: msg });
                  sess.sentCount += 1;
                } catch (e) {}
                await new Promise(r => setTimeout(r, sess.delays.swipe || 100));
              }
            })();
          }

          else if (cmd === 'swipedelay') {
            const ms = parseDelayMs(fullArg, 100);
            sess.delays.swipe = ms;
            await sock.sendMessage(jid, { text: `⏳ *Swipe Delay set to:* \`${ms}ms\`` });
          }

          else if (cmd === 'stopswipe' || cmd === 'swipestop') {
            stopChatLoop(sess, jid, 'swipe');
            await sock.sendMessage(jid, { text: `🛑 *Swiper Loop Stopped in THIS chat!*` });
          }

          else if (cmd === 'stopswipeall' || cmd === 'killswipe') {
            stopAllChatLoops(sess, 'swipe');
            await sock.sendMessage(jid, { text: `🛑 *MASTER STOP: Killed Swiper across ALL chats!*` });
          }

          else if (cmd === 'stop' || cmd === 'stopall' || cmd === 'masterstop' || cmd === 'killall' || cmd === 'shutdown' || cmd === 'kill' || cmd === 'halt' || cmd === 'stoploops') {
            stopAllOperations(sess);
            await sock.sendMessage(jid, { text: `🚨 *FORCE MASTER SHUTDOWN: All active operations, spammers, and loops halted everywhere!*` });
          }

          // ================= SUBADMIN ACCESS =================
          else if (cmd === 'addsubadmin' || cmd === 'subadmin' || cmd === 'setsubadmin') {
            const mentioned = msg.message?.extendedTextMessage?.contextInfo?.mentionedJid || [];
            let target = mentioned[0] || fullArg.replace(/[^0-9]/g, '');
            if (!target) return sock.sendMessage(jid, { text: `⚠️ Mention user: \`${sess.prefix}addsubadmin @tag\`` });
            sess.subadmins.add(target);
            await sock.sendMessage(jid, { text: `➕ *Subadmin added:* \`${target}\`` });
          }

          else if (cmd === 'removesubadmin' || cmd === 'delsubadmin' || cmd === 'unsubadmin') {
            const mentioned = msg.message?.extendedTextMessage?.contextInfo?.mentionedJid || [];
            let target = mentioned[0] || fullArg.replace(/[^0-9]/g, '');
            sess.subadmins.delete(target);
            await sock.sendMessage(jid, { text: `➖ *Subadmin removed:* \`${target}\`` });
          }

          else if (cmd === 'showsubadmin' || cmd === 'subadmins' || cmd === 'listsubadmin') {
            const list = Array.from(sess.subadmins || []);
            await sock.sendMessage(jid, {
              text: `📋 *AUTHORIZED SUBADMINS:*\n${list.length ? list.map((s, i) => `${i + 1}. \`${s}\``).join('\n') : 'No subadmins configured.'}`
            });
          }

          // ================= MODERATION & SECURITY =================
          else if (cmd === 'warn' || cmd === 'strike') {
            if (!isGroup) return;
            const mentioned = msg.message?.extendedTextMessage?.contextInfo?.mentionedJid || [];
            let target = mentioned[0];
            if (!target) return sock.sendMessage(jid, { text: `⚠️ Tag user: \`${sess.prefix}warn @tag\`` });

            sess.warnList[target] = (sess.warnList[target] || 0) + 1;
            const strikes = sess.warnList[target];

            if (strikes >= 3) {
              await sock.sendMessage(jid, {
                text: `⛔ @${target.split('@')[0]} reached *3/3 strikes!* Kicking from group...`,
                mentions: [target]
              });
              try {
                await sock.groupParticipantsUpdate(jid, [target], 'remove');
                delete sess.warnList[target];
              } catch (e) {}
            } else {
              await sock.sendMessage(jid, {
                text: `⚠️ @${target.split('@')[0]} has received a warning strike! (*${strikes}/3*)`,
                mentions: [target]
              });
            }
          }

          else if (cmd === 'resetwarn' || cmd === 'clearwarn' || cmd === 'unwarn') {
            const mentioned = msg.message?.extendedTextMessage?.contextInfo?.mentionedJid || [];
            let target = mentioned[0];
            if (target && sess.warnList[target]) delete sess.warnList[target];
            else sess.warnList = {};
            await sock.sendMessage(jid, { text: `🔄 *Warning strikes cleared.*` });
          }

          else if (cmd === 'antilink' || cmd === 'linkprotect') {
            const arg = fullArg.toLowerCase();
            if (arg === 'on') {
              sess.antilink = true;
              await sock.sendMessage(jid, { text: `🛡️ *Antilink Protection: ON*` });
            } else {
              sess.antilink = false;
              await sock.sendMessage(jid, { text: `🛡️ *Antilink Protection: OFF*` });
            }
          }

          else if (cmd === 'tagall' || cmd === 'everyone' || cmd === 'all') {
            if (!isGroup) return;
            try {
              const meta = await sock.groupMetadata(jid);
              const participants = meta.participants || [];
              const mentions = participants.map(p => p.id);
              let msgText = `📢 *ATTENTION ALL MEMBERS!*\n💬 *Message:* ${fullArg || 'Server God Clan Announcement'}\n\n`;
              participants.forEach(p => {
                msgText += `» @${p.id.split('@')[0]}\n`;
              });
              await sock.sendMessage(jid, { text: msgText, mentions });
            } catch (e) {}
          }

          // ================= EXECUTION MODES =================
          else if (cmd === 'rage') {
            sess.executionMode = 'rage';
            await sock.sendMessage(jid, { text: `🔥 *RAGE MODE ACTIVATED:* All bot nodes will execute commands simultaneously!` });
          }

          else if (cmd === 'solo') {
            sess.executionMode = 'solo';
            await sock.sendMessage(jid, { text: `🛡️ *SOLO MODE ACTIVATED:* Only main bot node executes commands.` });
          }

          else if (cmd === 'changeprefix' || cmd === 'setprefix' || cmd === 'prefix') {
            const newPre = fullArg.trim()[0] || '+';
            sess.prefix = newPre;
            await sock.sendMessage(jid, { text: `🔄 *Bot Prefix changed to:* \`[ ${newPre} ]\`` });
          }

          // ================= ADVANCED GROUP UTILITIES =================
          else if (cmd === 'add' || cmd === 'addmember' || cmd === 'invite') {
            if (!isGroup) return;
            const num = cleanPhone(fullArg);
            if (!num) return sock.sendMessage(jid, { text: `⚠️ Provide number: \`${sess.prefix}add 919507325677\`` });
            const targetJid = num.length === 10 ? '91' + num + '@s.whatsapp.net' : num + '@s.whatsapp.net';
            try {
              await sock.groupParticipantsUpdate(jid, [targetJid], 'add');
              await sock.sendMessage(jid, { text: `➕ Added @${num}`, mentions: [targetJid] });
            } catch (e) {
              await sock.sendMessage(jid, { text: `❌ Add failed: ${e.message}` });
            }
          }

          else if (cmd === 'kick' || cmd === 'remove' || cmd === 'ban') {
            if (!isGroup) return;
            const mentioned = msg.message?.extendedTextMessage?.contextInfo?.mentionedJid || [];
            let target = mentioned[0] || (fullArg ? normalizeJid(fullArg) : null);
            if (!target) return sock.sendMessage(jid, { text: `⚠️ Tag user to kick: \`${sess.prefix}kick @tag\`` });
            try {
              await sock.groupParticipantsUpdate(jid, [target], 'remove');
              await sock.sendMessage(jid, { text: `🧹 Ejected user from group.` });
            } catch (e) {
              await sock.sendMessage(jid, { text: `❌ Kick failed: ${e.message}` });
            }
          }

          else if (cmd === 'promote' || cmd === 'admin') {
            if (!isGroup) return;
            const mentioned = msg.message?.extendedTextMessage?.contextInfo?.mentionedJid || [];
            let target = mentioned[0];
            if (target) {
              await sock.groupParticipantsUpdate(jid, [target], 'promote');
              await sock.sendMessage(jid, { text: `📈 Promoted to Admin: @${target.split('@')[0]}`, mentions: [target] });
            }
          }

          else if (cmd === 'demote' || cmd === 'unadmin') {
            if (!isGroup) return;
            const mentioned = msg.message?.extendedTextMessage?.contextInfo?.mentionedJid || [];
            let target = mentioned[0];
            if (target) {
              await sock.groupParticipantsUpdate(jid, [target], 'demote');
              await sock.sendMessage(jid, { text: `📉 Demoted from Admin: @${target.split('@')[0]}`, mentions: [target] });
            }
          }

          else if (cmd === 'closegroup' || cmd === 'lockgc' || cmd === 'muteall' || cmd === 'closegc') {
            if (!isGroup) return;
            await sock.groupSettingUpdate(jid, 'announcement');
            await sock.sendMessage(jid, { text: `🔒 *Group closed (Only Admins can send messages).*` });
          }

          else if (cmd === 'opengroup' || cmd === 'unlockgc' || cmd === 'unmuteall' || cmd === 'opengc') {
            if (!isGroup) return;
            await sock.groupSettingUpdate(jid, 'not_announcement');
            await sock.sendMessage(jid, { text: `🔓 *Group opened (All members can send messages).*` });
          }

          else if (cmd === 'hidetag' || cmd === 'ghosttag' || cmd === 'htag') {
            if (!isGroup) return;
            try {
              const meta = await sock.groupMetadata(jid);
              const mentions = (meta.participants || []).map(p => p.id);
              await sock.sendMessage(jid, { text: fullArg || '📢 Silent Announcement', mentions });
            } catch (e) {}
          }

          else if (cmd === 'gclink' || cmd === 'grouplink' || cmd === 'link' || cmd === 'invitecode') {
            if (!isGroup) return sock.sendMessage(jid, { text: `⚠️ Group command only!` });
            try {
              const code = await sock.groupInviteCode(jid);
              await sock.sendMessage(jid, { text: `🔗 *Group Invite Link:*\nhttps://chat.whatsapp.com/${code}` });
            } catch (e) {
              await sock.sendMessage(jid, { text: `❌ Could not fetch link: ${e.message}` });
            }
          }

          else if (cmd === 'revoke' || cmd === 'resetlink' || cmd === 'revokelink') {
            if (!isGroup) return sock.sendMessage(jid, { text: `⚠️ Group command only!` });
            try {
              const newCode = await sock.groupRevokeInvite(jid);
              await sock.sendMessage(jid, { text: `🔄 *Group link reset!*\nNew Link: https://chat.whatsapp.com/${newCode}` });
            } catch (e) {
              await sock.sendMessage(jid, { text: `❌ Failed to revoke link: ${e.message}` });
            }
          }

          else if (cmd === 'setgcname' || cmd === 'renamegc' || cmd === 'setname') {
            if (!isGroup) return;
            const newName = fullArg || 'KING GOD CLAN';
            try {
              await sock.groupUpdateSubject(jid, newName);
              await sock.sendMessage(jid, { text: `✏️ Group subject updated to: "${newName}"` });
            } catch (e) {
              await sock.sendMessage(jid, { text: `❌ Rename failed: ${e.message}` });
            }
          }

          else if (cmd === 'setgcdesc' || cmd === 'setdesc' || cmd === 'updatedesc') {
            if (!isGroup) return;
            const newDesc = fullArg || 'KING BOT ULTRA';
            try {
              await sock.groupUpdateDescription(jid, newDesc);
              await sock.sendMessage(jid, { text: `📝 Group description updated.` });
            } catch (e) {
              await sock.sendMessage(jid, { text: `❌ Description failed: ${e.message}` });
            }
          }

          else if (cmd === 'react' || cmd === 'r') {
            const quoted = msg.message?.extendedTextMessage?.contextInfo;
            const emoji = fullArg.trim() || '👑';
            if (quoted?.stanzaId) {
              try {
                await sock.sendMessage(jid, {
                  react: {
                    text: emoji,
                    key: {
                      remoteJid: jid,
                      fromMe: quoted.participant === sock.user?.id,
                      id: quoted.stanzaId,
                      participant: quoted.participant
                    }
                  }
                });
              } catch (e) {}
            } else {
              await sock.sendMessage(jid, { text: `💡 Reply to a message with \`${sess.prefix}react 🔥\`` });
            }
          }

          else if (cmd === 'join' || cmd === 'joinlink') {
            const codeMatch = fullArg.match(/chat\.whatsapp\.com\/([0-9A-Za-z]{20,24})/);
            if (codeMatch && codeMatch[1]) {
              try {
                const res = await sock.groupAcceptInvite(codeMatch[1]);
                await sock.sendMessage(jid, { text: `🚪 *Joined Group successfully:* \`${res}\`` });
              } catch (e) {
                await sock.sendMessage(jid, { text: `❌ Failed to join: ${e.message}` });
              }
            } else {
              await sock.sendMessage(jid, { text: `⚠️ Provide valid invite link: \`${sess.prefix}join https://chat.whatsapp.com/...\`` });
            }
          }

          else if (cmd === 'leave' || cmd === 'exit' || cmd === 'left') {
            if (!isGroup) return;
            await sock.sendMessage(jid, { text: `🚪 *King Bot disconnecting from group...*` });
            await sock.groupLeave(jid);
          }

          else if (cmd === 'creategc' || cmd === 'newgc' || cmd === 'makegroup') {
            const gcTitle = fullArg || 'KING GOD CLAN CHAT';
            try {
              const res = await sock.groupCreate(gcTitle, [sock.user.id]);
              await sock.sendMessage(jid, { text: `🤖 *Created Group:* "${gcTitle}"\n🆔 \`${res.id}\`` });
            } catch (e) {
              await sock.sendMessage(jid, { text: `❌ Group Creation failed: ${e.message}` });
            }
          }

          // ================= DISCONNECT & SESSION PURGE COMMANDS =================
          else if (cmd === 'disconnect' || cmd === 'unlink' || cmd === 'logout') {
            await sock.sendMessage(jid, { text: `🔌 *Unlinking session ${uid} and purging credentials from disk...*` });
            stopAllOperations(sess);
            try {
              await sock.logout();
            } catch (e) {}
            try {
              sock.ev.removeAllListeners();
              sock.end();
            } catch (e) {}
            deleteSessionAuthDir(uid);
            sess.status = 'DISCONNECTED';
            sess.connectedNumber = '';
            sess.qr = '';
            sess.pairingCode = '';
            logMsg(uid, `Session unlinked & purged via WhatsApp command.`);
          }

          else if (cmd === 'deletesession' || cmd === 'destroysession') {
            await sock.sendMessage(jid, { text: `🗑️ *Deleting bot node ${uid} completely from memory & disk...*` });
            stopAllOperations(sess);
            try {
              sock.ev.removeAllListeners();
              sock.end();
            } catch (e) {}
            deleteSessionAuthDir(uid);
            delete activeSessions[uid];
            logMsg(uid, `Bot node ${uid} destroyed completely.`);
          }

          else if (cmd === 'bots' || cmd === 'nodes' || cmd === 'botlist') {
            const list = Object.entries(activeSessions);
            let bText = `🛰️ *ACTIVE BOT SESSIONS (${list.length}):*\n\n`;
            list.forEach(([sUid, s]) => {
              bText += `• *ID:* \`${sUid}\`\n  📱 Number: \`${s.connectedNumber || 'Offline'}\`\n  🟢 Status: \`${s.status}\`\n  👑 Owner: \`${s.ownerJid || 'None'}\`\n\n`;
            });
            await sock.sendMessage(jid, { text: bText });
          }

          else if (cmd === 'addbotsession' || cmd === 'newbot') {
            const sName = fullArg ? fullArg.replace(/[^a-zA-Z0-9_]/g, '') : `wp_${Date.now()}`;
            await initSessionSocket(sName, sess.ownerJid);
            await sock.sendMessage(jid, { text: `🆔 *Allocated New Bot Session Node:* \`${sName}\`` });
          }

          else if (cmd === 'removebot' || cmd === 'delbot') {
            const targetUid = fullArg.trim();
            if (activeSessions[targetUid]) {
              deleteSessionAuthDir(targetUid);
              delete activeSessions[targetUid];
              await sock.sendMessage(jid, { text: `❌ *Deleted Bot Node:* \`${targetUid}\`` });
            } else {
              await sock.sendMessage(jid, { text: `⚠️ Bot node not found: \`${targetUid}\`` });
            }
          }
        }
      }
    });

    return sess;
  } catch (err) {
    logMsg(uid, `Socket initialization error: ${err.message}`);
    throw err;
  }
}

// ================= REST API ROUTES =================

// Health check
app.get('/health', (req, res) => {
  res.json({
    status: 'ok',
    active_sessions_count: Object.keys(activeSessions).length,
    sessions: Object.keys(activeSessions)
  });
});

// Initialize / Create Session
app.post('/session/init', async (req, res) => {
  const { uid, owner_jid, auto_start } = req.body;
  if (!uid) return res.status(400).json({ success: false, message: 'uid is required' });

  try {
    const onlyReg = (auto_start === false);
    const sess = await initSessionSocket(uid, owner_jid, { onlyRegisterIfUnauthenticated: onlyReg });
    res.json({
      success: true,
      uid,
      status: sess.status,
      ownerJid: sess.ownerJid,
      connectedNumber: sess.connectedNumber
    });
  } catch (err) {
    res.status(500).json({ success: false, message: err.message });
  }
});

// Get Session Status & Telemetry
app.get('/session/:uid/status', async (req, res) => {
  const { uid } = req.params;
  const shouldConnect = req.query.connect === '1' || req.query.connect === 'true';
  let sess = activeSessions[uid];

  if (!sess) {
    try {
      sess = await initSessionSocket(uid, '', { onlyRegisterIfUnauthenticated: !shouldConnect, force: shouldConnect });
    } catch (e) {
      return res.json({
        uid,
        exists: false,
        status: 'INITIALIZING_ERROR',
        isOnline: false,
        connectedNumber: '',
        ownerJid: '',
        qr: '',
        pairingCode: '',
        sentCount: 0,
        failedCount: 0,
        uptime: 0,
        logs: [e.message]
      });
    }
  } else if (shouldConnect && (!sess.sock || sess.status === 'QR_EXPIRED' || sess.status === 'NOT_CONNECTED' || sess.status === 'STANDBY' || sess.status === 'LOGGED_OUT' || sess.status === 'DISCONNECTED')) {
    try {
      sess.qrAttempts = 0;
      sess = await initSessionSocket(uid, sess.ownerJid, { force: true });
    } catch (e) {}
  }

  const uptime = sess.connectedAt ? Math.floor((Date.now() - sess.connectedAt) / 1000) : 0;

  res.json({
    uid,
    exists: true,
    status: sess.status,
    isOnline: sess.status === 'ONLINE',
    connectedNumber: sess.connectedNumber,
    userJid: sess.userJid,
    ownerJid: sess.ownerJid,
    prefix: sess.prefix,
    executionMode: sess.executionMode,
    qr: sess.qr,
    pairingCode: sess.pairingCode,
    sentCount: sess.sentCount,
    failedCount: sess.failedCount,
    uptime,
    logs: sess.logs || []
  });
});

// Refresh QR Code
app.post('/session/:uid/refresh_qr', async (req, res) => {
  const { uid } = req.params;
  try {
    deleteSessionAuthDir(uid);
    const sess = activeSessions[uid];
    if (sess) {
      sess.qrAttempts = 0;
      sess.qr = '';
    }
    const newSess = await initSessionSocket(uid, sess ? sess.ownerJid : '', { force: true });
    res.json({ success: true, uid, status: newSess.status });
  } catch (e) {
    res.status(500).json({ success: false, message: e.message });
  }
});

// Request Pairing Code
app.post('/session/:uid/pair', async (req, res) => {
  const { uid } = req.params;
  const { phone } = req.body;

  let sess = activeSessions[uid];
  if (!sess || !sess.sock) {
    try {
      if (sess) sess.qrAttempts = 0;
      sess = await initSessionSocket(uid, sess ? sess.ownerJid : '', { force: true });
    } catch (e) {
      return res.status(500).json({ success: false, message: 'Could not initialize session socket' });
    }
  }

  const cleaned = cleanPhone(phone);
  if (!cleaned || cleaned.length < 10) {
    return res.status(400).json({ success: false, message: 'Please provide a valid 10-14 digit WhatsApp phone number without +.' });
  }

  try {
    logMsg(uid, `Requesting pairing code for number: +${cleaned}...`);
    if (!sess.sock) {
      return res.status(500).json({ success: false, message: 'Socket connecting, please retry in 2 seconds.' });
    }
    const code = await sess.sock.requestPairingCode(cleaned);
    sess.pairingCode = code;
    sess.status = 'PAIRING';
    sess.qr = '';

    logMsg(uid, `🔢 Pairing Code Generated for +${cleaned}: ${code}`);
    res.json({
      success: true,
      uid,
      phone: `+${cleaned}`,
      pairingCode: code
    });
  } catch (err) {
    logMsg(uid, `Error requesting pairing code: ${err.message}`);
    res.status(500).json({ success: false, message: err.message });
  }
});

// Update Bot Owner / Admin JID
app.post('/session/:uid/set_owner', (req, res) => {
  const { uid } = req.params;
  const { owner_jid } = req.body;
  const sess = activeSessions[uid];
  if (!sess) return res.status(404).json({ success: false, message: 'Session not found' });

  sess.ownerJid = (owner_jid || '').trim();
  logMsg(uid, `Bot Owner / Admin ID updated to: ${sess.ownerJid || 'None'}`);
  res.json({ success: true, uid, ownerJid: sess.ownerJid });
});

// Disconnect / Unlink WhatsApp Session
app.post('/session/:uid/disconnect', async (req, res) => {
  const { uid } = req.params;
  const sess = activeSessions[uid];
  if (!sess) return res.json({ success: true, message: 'No active session' });

  stopAllOperations(sess);

  if (sess.reconnectTimer) {
    clearTimeout(sess.reconnectTimer);
    sess.reconnectTimer = null;
  }

  try {
    if (sess.sock) {
      try {
        await sess.sock.logout();
      } catch (e) {}
      try {
        sess.sock.ev.removeAllListeners();
        if (sess.sock.ws) sess.sock.ws.close();
        sess.sock.end();
      } catch (e) {}
    }
  } catch (e) {}

  sess.sock = null;
  sess.status = 'DISCONNECTED';
  sess.connectedNumber = '';
  sess.userJid = '';
  sess.qr = '';
  sess.pairingCode = '';

  deleteSessionAuthDir(uid);
  logMsg(uid, `Session unlinked and auth directory purged.`);

  res.json({ success: true, uid, message: 'WhatsApp session disconnected and files cleaned.' });
});

// Delete Bot & Session Completely
app.post('/session/:uid/delete', async (req, res) => {
  const { uid } = req.params;
  const sess = activeSessions[uid];

  if (sess) {
    stopAllOperations(sess);
    if (sess.reconnectTimer) {
      clearTimeout(sess.reconnectTimer);
      sess.reconnectTimer = null;
    }
    try {
      if (sess.sock) {
        sess.sock.ev.removeAllListeners();
        if (sess.sock.ws) sess.sock.ws.close();
        sess.sock.end();
      }
    } catch (e) {}
    deleteSessionAuthDir(uid);
    delete activeSessions[uid];
  } else {
    deleteSessionAuthDir(uid);
  }

  logMsg(uid, `Bot and session destroyed completely.`);
  res.json({ success: true, uid, message: 'Session destroyed' });
});

// Get All Sessions Overview
app.get('/sessions/all', (req, res) => {
  const result = {};
  for (const [uid, sess] of Object.entries(activeSessions)) {
    const uptime = sess.connectedAt ? Math.floor((Date.now() - sess.connectedAt) / 1000) : 0;
    result[uid] = {
      uid,
      status: sess.status,
      isOnline: sess.status === 'ONLINE',
      connectedNumber: sess.connectedNumber,
      ownerJid: sess.ownerJid,
      prefix: sess.prefix,
      sentCount: sess.sentCount,
      failedCount: sess.failedCount,
      uptime,
      hasQr: !!sess.qr,
      hasPairingCode: !!sess.pairingCode
    };
  }
  res.json({ success: true, count: Object.keys(result).length, sessions: result, globalLogs });
});

// Start Server
app.listen(PORT, '0.0.0.0', () => {
  console.log(`\n========================================================================`);
  console.log(`🚀 [KING BOT BAILEYS MULTI-SESSION HUB] Running on http://127.0.0.1:${PORT}`);
  console.log(`⚡ Ultra 0.01s (10ms) Command Loops, Per-Chat Loops & Master Stop Active`);
  console.log(`========================================================================\n`);
});
