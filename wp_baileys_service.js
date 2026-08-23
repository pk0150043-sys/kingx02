'use strict';

// ============================================================================
// 👑 KING BOT ULTRA V2.0 & VOIP CALL ENGINE (BAILEYS MULTI-DEVICE MASTER)
// 🛡️ SERVER GOD CLAN • ULTRA TURBO 0.01s LOOPS & LIVE CALL ENGINE
// ============================================================================

// Global Uncaught Exception Sentinel (Bot NEVER stops or crashes!)
process.on('uncaughtException', (err) => {
  try {
    console.error('[UNCAUGHT EXCEPTION PREVENTED]', err?.message || err);
  } catch (e) {}
});

process.on('unhandledRejection', (reason) => {
  try {
    console.error('[UNHANDLED REJECTION PREVENTED]', reason?.message || reason);
  } catch (e) {}
});

// Noise Filter for Clean Console Output
const NOISE = [
  'Closing open session', 'Closing session', 'SessionEntry', '_chains',
  'registrationId', 'currentRatchet', 'ephemeralKeyPair', 'indexInfo',
  'prekey', 'chainKey', 'chainType', 'messageKeys', 'pendingPreKey',
  'rootKey', 'privKey', 'pubKey', 'remoteIdentityKey', 'lastRemoteEphemeralKey',
  'baseKeyType', 'Bad MAC', 'Session error', 'decryptWithSessions',
  'doDecryptWhisperMessage', 'libsignal', 'session_cipher', '<Buffer', 'Buffer ',
  'rate-overlimit', 'Connection Closed', 'timed out', 'QR scan timed out'
];

const isNoise = (...a) => {
  const s = a.flat().map(x => String(x ?? '')).join(' ');
  return NOISE.some(p => s.includes(p));
};

const _ol = console.log.bind(console);
const _oe = console.error.bind(console);
const _ow = console.warn.bind(console);
console.log   = (...a) => { if (!isNoise(a)) _ol(...a); };
console.error = (...a) => { if (!isNoise(a)) _oe(...a); };
console.warn  = (...a) => { if (!isNoise(a)) _ow(...a); };

const express = require('express');
const cors = require('cors');
const fs = require('fs');
const path = require('path');
const https = require('https');
const http = require('http');
const pino = require('pino');
const QRCode = require('qrcode');
const {
  default: makeWASocket,
  useMultiFileAuthState,
  DisconnectReason,
  Browsers,
  fetchLatestBaileysVersion,
  downloadMediaMessage,
  downloadContentFromMessage,
  jidNormalizedUser
} = require('@whiskeysockets/baileys');

const app = express();
app.use(cors());
app.use(express.json({ limit: '50mb' }));
app.use(express.urlencoded({ extended: true, limit: '50mb' }));

const PORT = process.env.WP_SERVICE_PORT || 20824;
const SESSIONS_BASE_DIR = path.join(__dirname, 'sessions');
const RECORDINGS_DIR = path.join(__dirname, 'recordings');
const MAIN_PIC_PATH = path.join(__dirname, 'main.png');
const AUDIO_51_PATH = path.join(__dirname, '51.mp3');

// Ensure required directories exist
for (const dir of [SESSIONS_BASE_DIR, RECORDINGS_DIR]) {
  if (!fs.existsSync(dir)) {
    try { fs.mkdirSync(dir, { recursive: true }); } catch (e) {}
  }
}

// In-Memory Global Registries
const activeSessions = {};
const globalLogs = [];

// Periodic V8 Memory Cleanup
if (typeof global.gc === 'function') {
  setInterval(() => {
    try { global.gc(); } catch (e) {}
  }, 30000);
}

function logMsg(uid, msg) {
  const timestamp = new Date().toLocaleTimeString();
  const entry = `[${timestamp}] [${uid || 'SYSTEM'}] ${msg}`;
  console.log(entry);

  if (uid && activeSessions[uid]) {
    activeSessions[uid].logs = activeSessions[uid].logs || [];
    activeSessions[uid].logs.unshift(entry);
    if (activeSessions[uid].logs.length > 80) activeSessions[uid].logs.pop();
  }

  globalLogs.unshift(entry);
  if (globalLogs.length > 120) globalLogs.pop();
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
    return Math.max(10, Math.floor(num * 1000));
  }
  return Math.max(10, Math.floor(num));
}

const sleep = ms => new Promise(r => setTimeout(r, ms));

// ============================================================================
// AUDIO DOWNLOAD & MUSIC SEARCH UTILITIES (JioSaavn • Spotify • Audius)
// ============================================================================

function fetchJson(url) {
  return new Promise((resolve, reject) => {
    const mod = url.startsWith('https') ? https : http;
    const req = mod.get(url, { headers: { 'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)' } }, res => {
      let data = '';
      res.on('data', c => data += c);
      res.on('end', () => {
        try { resolve(JSON.parse(data)); } catch (e) { reject(e); }
      });
    });
    req.on('error', reject);
    req.setTimeout(12000, () => { req.destroy(); reject(new Error('Request timeout')); });
  });
}

function downloadBuffer(url) {
  return new Promise((resolve, reject) => {
    const doGet = (u, redirects = 0) => {
      if (redirects > 5) return reject(new Error('Too many redirects'));
      const mod = u.startsWith('https') ? https : http;
      const req = mod.get(u, { headers: { 'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)' } }, res => {
        if (res.statusCode >= 300 && res.statusCode < 400 && res.headers.location) {
          return doGet(res.headers.location, redirects + 1);
        }
        if (res.statusCode !== 200) return reject(new Error(`HTTP status ${res.statusCode}`));
        const chunks = [];
        res.on('data', c => chunks.push(c));
        res.on('end', () => resolve(Buffer.concat(chunks)));
      });
      req.on('error', reject);
      req.setTimeout(35000, () => { req.destroy(); reject(new Error('Download timeout')); });
    };
    doGet(url);
  });
}

// 1. JioSaavn Song Search & Download
async function searchJioSaavn(query) {
  const endpoints = [
    `https://jiosavan-api2.vercel.app/api/search/songs?query=${encodeURIComponent(query)}&limit=5`,
    `https://saavn.me/search/songs?query=${encodeURIComponent(query)}&page=1&limit=5`
  ];

  for (const url of endpoints) {
    try {
      const data = await fetchJson(url);
      const songs = data?.data?.results || data?.data || [];
      if (!songs || !songs.length) continue;

      let chosen = null, audioUrl = null;
      for (const song of songs) {
        const urls = song.downloadUrl || song.download_url;
        if (!urls || !urls.length) continue;
        const sorted = [...urls].sort((a, b) => parseInt(b.quality || 0) - parseInt(a.quality || 0));
        const best = sorted.find(u => (u.url || u.link) && String(u.url || u.link).startsWith('http'));
        if (best) {
          chosen = song;
          audioUrl = best.url || best.link;
          break;
        }
      }
      if (chosen && audioUrl) {
        const title = chosen.name || chosen.title || query;
        const artist = chosen.artists?.primary?.map(a => a.name).join(', ') || chosen.primaryArtists || 'Unknown Artist';
        const album = chosen.album?.name || chosen.album || '';
        const durSec = chosen.duration || 180;
        const duration = `${Math.floor(durSec / 60)}:${String(durSec % 60).padStart(2, '0')}`;
        return { title, artist, album, duration, durSec: parseInt(durSec) || 180, audioUrl };
      }
    } catch (e) {}
  }
  return null;
}

// 2. Spotify API Token & Metadata Search
const SPOTIFY_CLIENT_ID = process.env.SPOTIFY_CLIENT_ID || '45dbfe82aa5142a49edb7422a79e3ff6';
const SPOTIFY_CLIENT_SECRET = process.env.SPOTIFY_CLIENT_SECRET || '14dba99c74f64d638c72c5603029a135';
let spotifyToken = null;
let spotifyTokenExpiry = 0;

async function getSpotifyToken() {
  if (spotifyToken && Date.now() < spotifyTokenExpiry) return spotifyToken;
  const creds = Buffer.from(`${SPOTIFY_CLIENT_ID}:${SPOTIFY_CLIENT_SECRET}`).toString('base64');
  const body = 'grant_type=client_credentials';
  const data = await new Promise((resolve, reject) => {
    const req = https.request({
      hostname: 'accounts.spotify.com',
      path: '/api/token',
      method: 'POST',
      headers: {
        'Authorization': `Basic ${creds}`,
        'Content-Type': 'application/x-www-form-urlencoded',
        'Content-Length': Buffer.byteLength(body)
      }
    }, res => {
      let d = '';
      res.on('data', c => d += c);
      res.on('end', () => { try { resolve(JSON.parse(d)); } catch (e) { reject(e); } });
    });
    req.on('error', reject);
    req.write(body);
    req.end();
  });
  if (!data.access_token) throw new Error('Spotify token generation failed');
  spotifyToken = data.access_token;
  spotifyTokenExpiry = Date.now() + (data.expires_in - 60) * 1000;
  return spotifyToken;
}

async function searchSpotify(query) {
  try {
    const token = await getSpotifyToken();
    const url = `https://api.spotify.com/v1/search?q=${encodeURIComponent(query)}&type=track&limit=1`;
    const data = await new Promise((resolve, reject) => {
      const req = https.get(url, {
        headers: { 'Authorization': `Bearer ${token}`, 'User-Agent': 'Mozilla/5.0' }
      }, res => {
        let d = '';
        res.on('data', c => d += c);
        res.on('end', () => { try { resolve(JSON.parse(d)); } catch (e) { reject(e); } });
      });
      req.on('error', reject);
      req.setTimeout(10000, () => { req.destroy(); reject(new Error('Spotify timeout')); });
    });
    const track = data?.tracks?.items?.[0];
    if (!track) return null;
    return {
      title: track.name,
      artist: track.artists.map(a => a.name).join(', '),
      album: track.album?.name || '',
      releaseYear: track.album?.release_date?.slice(0, 4) || '',
      durationMs: track.duration_ms || 180000
    };
  } catch (e) {
    return null;
  }
}

// 3. Audius Free Music Search
async function searchAudius(query) {
  try {
    const hostsData = await fetchJson('https://api.audius.co');
    const host = (hostsData?.data || [])[0];
    if (!host) throw new Error('No Audius host available');
    const res = await fetchJson(`${host}/v1/tracks/search?query=${encodeURIComponent(query)}&limit=5&app_name=KingBotUltra`);
    const track = res?.data?.[0];
    if (!track) return null;
    const durSec = track.duration || 180;
    const duration = `${Math.floor(durSec / 60)}:${String(durSec % 60).padStart(2, '0')}`;
    return {
      title: track.title,
      artist: track.user?.name || 'Unknown',
      duration,
      durSec,
      streamUrl: `${host}/v1/tracks/${track.id}/stream?app_name=KingBotUltra`
    };
  } catch (e) {
    return null;
  }
}

// ============================================================================
// STYLED DASHBOARDS & MENUS (EXACT SERVER GOD CLAN THEME)
// ============================================================================

function getMenuPortalText(prefix = '+') {
  return `╭──────────────────────────────╮
│ 👑 𝑲𝑰𝑵𝑮 𝑩𝑶𝑻 𝑴𝑬𝑵𝑼 𝑷𝑶𝑹𝑻𝑨𝑳 ⚡ │
│ 🛡️ 𝑺𝑬𝑹𝑽𝑬𝑹 𝑮𝑶𝑫 𝑪𝑳𝑨𝑵     │
╰──────────────────────────────╯
      ⚡ PREFIX  :  ${prefix}
      🚀 SPEED   : 0.01s+

*Please select a Dashboard by replying with number (1, 2, or 3):*

1️⃣ *1* or *${prefix}menu 1* ➔ 👑 𝑼𝑳𝑻𝑹𝑨 𝑫𝑨𝑺𝑯𝑩𝑶𝑨𝑹𝑫
   *(Target • NC • DC • Spam • PFP • Poll • Radar • Utility • Multi-Node)*

2️⃣ *2* or *${prefix}menu 2* ➔ 📞 𝑽𝑶𝑰𝑷 𝑪𝑨𝑳𝑳𝑰𝑵𝑮 𝑬𝑵𝑮𝑰𝑵𝑬
   *(Outcall • VN • Recordings • 51.mp3 Loop • JioCall • Autounmute)*

3️⃣ *3* or *${prefix}menu 3* ➔ 🎵 𝑴𝑼𝑺𝑰𝑪 & 𝑺𝑶𝑵𝑮 𝑫𝑨𝑺𝑯𝑩𝑶𝑨𝑹𝑫
   *(JioSaavn 320kbps • Spotify HD • Audius Free • Song Loops)*

╭──────────────────────────────╮
│ ⚡ 𝑷𝑶𝑾𝑬𝑹𝑬𝑫 𝑩𝒀 𝑺𝑬𝑹𝑽𝑬𝑹 𝑮𝑶𝑫 𝑪𝑳𝑨𝑵 ⚡ │
╰──────────────────────────────╯
👉 *Reply \`1\`, \`2\`, or \`3\` (or use shortcut \`${prefix}menu 1\`, \`${prefix}menu 2\`, \`${prefix}menu 3\`)*`;
}

function getUltraDashboardMenu(prefix = '+') {
  return `╭──────────────────────────────╮
│ 👑 𝑲𝑰𝑵𝑮 𝑩𝑶𝑻 𝑼𝑳𝑻𝑹𝑨 𝑽2.0 ⚡ │
│ 🛡️ 𝑺𝑬𝑹𝑽𝑬𝑹 𝑮𝑶𝑫 𝑪𝑳𝑨𝑵     │
╰──────────────────────────────╯
      ⚡ PREFIX  :  ${prefix}
      🚀 SPEED   : 0.01s+

╭─ 🎯 𝑻𝑨𝑹𝑮𝑬𝑻 𝑺𝒀𝑺𝑻𝑬𝑴
│ 🎯 ${prefix}target @tag <Text>
│ 🛑 ${prefix}stoptarget @tag
│ 🧹 ${prefix}stoptargetall
│ 📋 ${prefix}targetlist
│ ⏱️ ${prefix}targetdelay <0.01-20>
│ 💀 ${prefix}roast @tag
╰──────────────────────

╭─ 📌 𝑷𝑰𝑵 𝑺𝑷𝑨𝑴
│ 📌 ${prefix}pin
│ 📌 ${prefix}unpin
│ ⚡ ${prefix}pinspam <count> <delay_ms>
│ 🛑 ${prefix}pinspam off
╰──────────────────────

╭─ ⚡ 𝑵𝑹 (𝑵𝑨𝑴𝑬 𝑹𝑨𝑰𝑫)
│ ⚡ ${prefix}nr <Text>
│ ⚡ ${prefix}nr1 <Text>
│ ⚡ ${prefix}nr2 <Text>
│ ⚡ ${prefix}nr3 <Text>
│ ⏱️ ${prefix}nrdelay <0.01-20>
│ 🛑 ${prefix}stopnr
│ 🔴 ${prefix}stopnrall
│ 📨 ${prefix}send <Number/JID> <Text>
╰──────────────────────

╭─ 🌀 𝑻𝑼𝑹𝑩𝑶 𝑵𝑪
│ 🌀 ${prefix}nc <Text>
│ ⚡ ${prefix}triplenc1 <Text>
│ ⏱️ ${prefix}ncdelay <0.01-20>
│ 🛑 ${prefix}stopnc
│ 🔴 ${prefix}stopncall
╰──────────────────────

╭─ ✍️ 𝑮𝑹𝑶𝑼𝑷 𝑫𝑪
│ 📝 ${prefix}gdc <Text>
│ 📝 ${prefix}gcdc <Text>
│ ⏱️ ${prefix}gdcdelay <0.01-20>
│ 🛑 ${prefix}gdcstop
│ 🔴 ${prefix}stopgdcall
╰──────────────────────

╭─ 🖼️ 𝑨𝑼𝑻𝑶 𝑷𝑭𝑷
│ 📸 ${prefix}pfpchange
│ ⏱️ ${prefix}pfpdelay <0.1-20>
│ 🛑 ${prefix}pfpstop
╰──────────────────────

╭─ 📸 𝑷𝑰𝑪 𝑺𝑷𝑨𝑴
│ 🖼️ ${prefix}picspam <Text>
│ ⏱️ ${prefix}picspamdelay <0.1-20>
│ 🛑 ${prefix}picspamstop
│ 🔴 ${prefix}stoppicspamall
╰──────────────────────

╭─ 📊 𝑻𝑬𝑿𝑻 & 𝑷𝑶𝑳𝑳
│ 📝 ${prefix}textspam <Text>
│ ⏱️ ${prefix}textspamdelay <0.01-20>
│ 🛑 ${prefix}textspamstop
│ 📊 ${prefix}pollspam Name | opt1 | opt2
│ ⏱️ ${prefix}pollspamdelay <0.1-20>
│ 🛑 ${prefix}pollspamstop
╰──────────────────────

╭─ 💀 𝑹𝑨𝑫𝑨𝑹 & 𝑴𝑼𝑻𝑬
│ 💀 ${prefix}autodelete @tag
│ 🔓 ${prefix}stopdelete @tag
│ 🔇 ${prefix}mute @tag
│ 🔊 ${prefix}unmute @tag
╰──────────────────────

╭─ 🚀 𝑭𝑳𝑶𝑶𝑫 & 𝑺𝑾𝑰𝑷𝑬
│ 🚀 ${prefix}spam <Text>
│ ⏱️ ${prefix}spamdelay <0.01-20>
│ 🛑 ${prefix}stopspam
│ 🔴 ${prefix}stopspamall
│ 🔄 ${prefix}swipe <Text>
│ ⏱️ ${prefix}swipedelay <0.01-20>
│ 🛑 ${prefix}stopswipe
│ 🚨 ${prefix}stopall
╰──────────────────────

╭─ 🛡️ 𝑴𝑶𝑫𝑬𝑹𝑨𝑻𝑰𝑶𝑵
│ ⚠️ ${prefix}warn @tag
│ 🔄 ${prefix}resetwarn @tag
│ 🔗 ${prefix}antilink on/off
│ 📢 ${prefix}tagall <Text>
│ 👑 ${prefix}addsubadmin @tag
│ ❌ ${prefix}removesubadmin @tag
│ 📋 ${prefix}showsubadmin
╰──────────────────────

╭─ ⚙️ 𝑮𝑹𝑶𝑼𝑷 𝑼𝑻𝑰𝑳𝑰𝑻𝒀
│ ➕ ${prefix}add <Number>
│ 🧹 ${prefix}kick @tag
│ 👑 ${prefix}promote @tag
│ 📉 ${prefix}demote @tag
│ 🔒 ${prefix}closegroup
│ 🔓 ${prefix}opengroup
│ 📢 ${prefix}hidetag <Text>
│ 🔗 ${prefix}gclink
│ 🔄 ${prefix}revoke
│ ✏️ ${prefix}setgcname <Name>
│ 📝 ${prefix}setgcdesc <Desc>
│ 🎭 ${prefix}react <Emoji>
│ 🚪 ${prefix}join <Link>
│ 🚪 ${prefix}leave
│ 🤖 ${prefix}creategc <Name>
│ ⚡ ${prefix}ping
│ 📊 ${prefix}botinfo
╰──────────────────────

╭─ 🛰️ 𝑴𝑼𝑳𝑻𝑰-𝑵𝑶𝑫𝑬
│ 🔌 ${prefix}disconnect
│ ❌ ${prefix}deletesession
│ 🆔 ${prefix}addbotsession <Name>
│ 📋 ${prefix}bots
│ ❌ ${prefix}removebot <Session>
│ 🔥 ${prefix}rage
│ 🛡️ ${prefix}solo
│ 🔄 ${prefix}changeprefix <Symbol>
╰──────────────────────

╭──────────────────────────────╮
│ ⚡ 𝑷𝑶𝑾𝑬𝑹𝑬𝑫 𝑩𝒀 𝑺𝑬𝑹𝑽𝑬𝑹 𝑮𝑶𝑫 𝑪𝑳𝑨𝑵 ⚡ │
╰──────────────────────────────╯`;
}

function getCallingEngineMenu(prefix = '+') {
  return `╭─────────────────────────╮
📞 𝙑𝙊𝙄𝙋 𝘾𝘼𝙇𝙇𝙄𝙉𝙂 𝙀𝙉𝙂𝙄𝙉𝙀 📞
╰─────────────────────────╯
⚡ 𝙊𝙐𝙏𝘽𝙊𝙐𝙉𝘿 𝙒𝙃𝘼𝙏𝙎𝘼𝙋𝙋 𝘾𝘼𝙇𝙇𝙀𝙍

│
├─► 📞 \`${prefix}outcall <number>\`
│    ▸ 𝙥𝙡𝙖𝙘𝙚 𝙖 𝙙𝙞𝙧𝙚𝙘𝙩 𝙑𝙤𝙄𝙋 𝙫𝙤𝙞𝙘𝙚 𝙘𝙖𝙡𝙡
│
├─► 🎵 \`${prefix}outcall <number> <recording/file>\`
│    ▸ 𝙘𝙖𝙡𝙡 & 𝙥𝙡𝙖𝙮 𝙨𝙖𝙫𝙚𝙙 𝙧𝙚𝙘𝙤𝙧𝙙𝙞𝙣𝙜 𝙤𝙧 𝙢𝙥𝟯
│
├─► 🎙️ \`${prefix}outcall <number> vn <text>\`
│    ▸ 𝙨𝙥𝙚𝙖𝙠 𝙬𝙞𝙩𝙝 𝙏𝙏𝙎/𝙀𝙡𝙚𝙫𝙚𝙣𝙇𝙖𝙗𝙨 𝙫𝙤𝙞𝙘𝙚 𝙞𝙣 𝙘𝙖𝙡𝙡
│
├─► 🗣️ \`${prefix}cvn <text>\`
│    ▸ 𝙨𝙥𝙚𝙖𝙠 𝙡𝙞𝙫𝙚 𝙞𝙣 𝙖𝙘𝙩𝙞𝙫𝙚 𝙘𝙖𝙡𝙡 (𝙫𝙣 𝙤𝙣 𝙘𝙖𝙡𝙡)
│
├─► 🔊 \`${prefix}play1call\`
│    ▸ 𝙥𝙡𝙖𝙮 51.mp3 𝙞𝙣 𝙘𝙤𝙣𝙩𝙞𝙣𝙪𝙤𝙪𝙨 5𝙨 𝙡𝙤𝙤𝙥 𝙤𝙣 𝙘𝙖𝙡𝙡
│
├─► 🎶 \`${prefix}playjiocall <song name>\`
│    ▸ 𝙨𝙚𝙖𝙧𝙘𝙝 & 𝙥𝙡𝙖𝙮 𝙅𝙞𝙤𝙎𝙖𝙖𝙫𝙣 𝙨𝙤𝙣𝙜 𝙞𝙣 𝙘𝙖𝙡𝙡 (5𝙨 𝙡𝙤𝙤𝙥)
│
├─► 🔓 \`${prefix}autounmute\`
│    ▸ 𝙖𝙪𝙩𝙤 𝙪𝙣𝙢𝙪𝙩𝙚 𝙞𝙛 𝙢𝙪𝙩𝙚𝙙 𝙙𝙪𝙧𝙞𝙣𝙜 𝙘𝙖𝙡𝙡
│
├─► 💾 \`${prefix}saverd <name>\`
│    ▸ 𝙧𝙚𝙥𝙡𝙮 𝙩𝙤 𝙖𝙪𝙙𝙞𝙤/𝙫𝙣 𝙩𝙤 𝙨𝙖𝙫𝙚 𝙞𝙣 𝙧𝙚𝙘𝙤𝙧𝙙𝙞𝙣𝙜𝙨
│
├─► 📋 \`${prefix}listrd\`
│    ▸ 𝙡𝙞𝙨𝙩 𝙖𝙡𝙡 𝙨𝙖𝙫𝙚𝙙 𝙧𝙚𝙘𝙤𝙧𝙙𝙞𝙣𝙜𝙨 𝙬𝙞𝙩𝙝 𝙨𝙞𝙯𝙚𝙨
│
├─► ▶️ \`${prefix}playrd <name>\`
│    ▸ 𝙥𝙡𝙖𝙮 𝙨𝙖𝙫𝙚𝙙 𝙧𝙚𝙘𝙤𝙧𝙙𝙞𝙣𝙜 𝙤𝙣 𝙡𝙞𝙫𝙚 𝙖𝙘𝙩𝙞𝙫𝙚 𝙘𝙖𝙡𝙡
│
├─► 🗑️ \`${prefix}delrd <name>\`
│    ▸ 𝙙𝙚𝙡𝙚𝙩𝙚 𝙖 𝙨𝙖𝙫𝙚𝙙 𝙧𝙚𝙘𝙤𝙧𝙙𝙞𝙣𝙜
│
├─► ⏹️ \`${prefix}endcall\` / \`${prefix}hangup\`
│    ▸ 𝙩𝙚𝙧𝙢𝙞𝙣𝙖𝙩𝙚 𝙩𝙝𝙚 𝙖𝙘𝙩𝙞𝙫𝙚 𝙤𝙪𝙩𝙗𝙤𝙪𝙣𝙙 𝙘𝙖𝙡𝙡
│
├─► 📊 \`${prefix}callstatus\`
│    ▸ 𝙫𝙞𝙚𝙬 𝙡𝙞𝙫𝙚 𝙘𝙖𝙡𝙡 𝙨𝙩𝙖𝙩𝙚, 𝙘𝙖𝙡𝙡 𝙄𝘿 & 𝙙𝙪𝙧𝙖𝙩𝙞𝙤𝙣
│
└─► 🔇 \`${prefix}callmute\` / \`${prefix}callunmute\`
     ▸ 𝙩𝙤𝙜𝙜𝙡𝙚 𝙤𝙪𝙩𝙜𝙤𝙞𝙣𝙜 𝙖𝙪𝙙𝙞𝙤 𝙢𝙪𝙩𝙚 𝙙𝙪𝙧𝙞𝙣𝙜 𝙘𝙖𝙡𝙡

╭─────────────────────────╮
भिड़ मत, तेरी माँ चोदूँगा।
╰─────────────────────────╯`;
}

function getSongDashboardMenu(prefix = '+') {
  return `╭──────────────────────────────╮
│ 🎵 𝑴𝑼𝑺𝑰𝑪 & 𝑺𝑶𝑵𝑮 𝑬𝑵𝑮𝑰𝑵𝑬 🎶   │
│ 🛡️ 𝑺𝑬𝑹𝑽𝑬𝑹 𝑮𝑶𝑫 𝑪𝑳𝑨𝑵     │
╰──────────────────────────────╯
      ⚡ PREFIX  :  ${prefix}
      🎧 ENGINES : JioSaavn • Spotify • Audius

╭─ 🎵 𝑱𝑰𝑶𝑺𝑨𝑨𝑽𝑵 𝑴𝑼𝑺𝑰𝑪
│ 🎵 \`${prefix}song <Song Name>\`
│    ▸ Search & download 320kbps HD audio track
│ 🎶 \`${prefix}songplay <Song Name>\`
│    ▸ Instant voice note audio player
│ 🔁 \`${prefix}songloop <Song Name>\`
│    ▸ Continuous 5s loop in chat
│ 🛑 \`${prefix}stopsong\`
│    ▸ Stop playing / looping song
╰──────────────────────

╭─ 🎧 𝑺𝑷𝑶𝑻𝑰𝑭𝒀 × 𝑱𝑰𝑶𝑺𝑨𝑨𝑽𝑵
│ 🎧 \`${prefix}gana <Song Name>\`
│    ▸ Spotify official metadata + HD JioSaavn audio
│ 💿 \`${prefix}album <Artist/Album>\`
│    ▸ Search full artist tracklist
╰──────────────────────

╭─ 🎼 𝑨𝑼𝑫𝑰𝑼𝑺 𝑭𝑹𝑬𝑬 𝑴𝑼𝑺𝑰𝑪
│ 🎼 \`${prefix}geet <Song Name>\`
│    ▸ Free Audius decentralized music stream
╰──────────────────────

╭─ 📻 𝑪𝑨𝑳𝑳 𝑨𝑼𝑫𝑰𝑶 𝑺𝑻𝑹𝑬𝑨𝑴𝑬𝑹
│ 🔊 \`${prefix}play1call\`
│    ▸ Play 51.mp3 in continuous 5s loop on call
│ 🎶 \`${prefix}playjiocall <Song Name>\`
│    ▸ Search JioSaavn & stream into call loop
│ 💾 \`${prefix}saverd <name>\` / \`${prefix}playrd <name>\`
│    ▸ Save & stream custom recordings on call
╰──────────────────────

╭──────────────────────────────╮
│ ⚡ 𝑷𝑶𝑾𝑬𝑹𝑬𝑫 𝑩𝒀 𝑺𝑬𝑹𝑽𝑬𝑹 𝑮𝑶𝑫 𝑪𝑳𝑨𝑵 ⚡ │
╰──────────────────────────────╯`;
}

// Master Admin Numbers & Global Cache
const MASTER_ADMIN_NUMBERS = ['919507325677', '9507325677', '84925465462', '8986269256', '5214825153', '8846249998'];
const processedMessageIds = new Map();
const processedCommandKeys = new Map();

function isDuplicateMessage(msgId) {
  if (!msgId) return false;
  const now = Date.now();
  if (processedMessageIds.has(msgId)) return true;
  processedMessageIds.set(msgId, now);
  if (processedMessageIds.size > 4000) {
    const oldestKey = processedMessageIds.keys().next().value;
    processedMessageIds.delete(oldestKey);
  }
  return false;
}

function shouldExecuteCommand(sess, msg, cmdName) {
  if (sess.executionMode === 'rage') return true;
  if (msg.key.fromMe) return true;
  const cmdKey = `${msg.key.remoteJid}_${msg.key.id || ''}_${cmdName}`;
  const now = Date.now();
  if (processedCommandKeys.has(cmdKey)) return false;
  processedCommandKeys.set(cmdKey, now);
  if (processedCommandKeys.size > 2000) {
    const oldest = processedCommandKeys.keys().next().value;
    processedCommandKeys.delete(oldest);
  }
  return true;
}

function isAuthorizedOwner(sess, msg, sock) {
  if (!sess) return false;
  if (msg.key.fromMe) return true;

  const senderParticipant = (msg.key.participant || (msg.key.fromMe ? sock.user?.id : msg.key.remoteJid) || msg.participant || '').trim();
  const remoteJid = (msg.key.remoteJid || '').trim();
  const senderLid = (msg.key.participantAlt || '').trim();
  const isGroup = remoteJid.endsWith('@g.us');

  const cleanSender = cleanPhone(senderParticipant.split('@')[0].split(':')[0]);
  const cleanRemote = cleanPhone(remoteJid.split('@')[0].split(':')[0]);
  const cleanSenderLid = cleanPhone(senderLid.split('@')[0].split(':')[0]);

  // Master platform admins
  for (const master of MASTER_ADMIN_NUMBERS) {
    if (cleanSender === master || cleanRemote === master || cleanSenderLid === master) return true;
    if (cleanSender && cleanSender.length >= 10 && (cleanSender.endsWith(master) || master.endsWith(cleanSender))) return true;
    if (cleanRemote && cleanRemote.length >= 10 && (cleanRemote.endsWith(master) || master.endsWith(cleanRemote))) return true;
  }

  // Dynamic session owner LID
  if (sess.ownerLid) {
    const cleanOwnerLid = cleanPhone(sess.ownerLid);
    if (senderParticipant === sess.ownerLid || senderLid === sess.ownerLid) return true;
    if (cleanOwnerLid && (cleanSender === cleanOwnerLid || cleanSenderLid === cleanOwnerLid)) return true;
  }

  // Direct DM chat with owner
  if (!isGroup && sess.ownerJid) {
    const cleanOwner = cleanPhone(sess.ownerJid);
    if (cleanOwner && (cleanRemote === cleanOwner || cleanRemote.endsWith(cleanOwner) || cleanOwner.endsWith(cleanRemote))) {
      sess.ownerLid = senderParticipant || senderLid;
      return true;
    }
  }

  const ownerInput = String(sess.ownerJid || '').trim();
  if (!ownerInput) return !isGroup;

  const ownerLower = ownerInput.toLowerCase();
  if (senderParticipant.toLowerCase() === ownerLower || remoteJid.toLowerCase() === ownerLower || senderLid.toLowerCase() === ownerLower) {
    return true;
  }

  const cleanOwner = cleanPhone(ownerInput.split('@')[0].split(':')[0]);
  if (ownerInput.includes('@lid') || (cleanOwner && ownerInput.includes('lid'))) {
    if (senderParticipant.includes(cleanOwner) || senderLid.includes(cleanOwner) || remoteJid.includes(cleanOwner)) {
      return true;
    }
  }

  if (cleanOwner && cleanOwner.length >= 7) {
    if (cleanOwner === cleanSender || cleanOwner === cleanRemote || cleanOwner === cleanSenderLid) return true;
    if (cleanOwner.length === 10 && (cleanSender.endsWith(cleanOwner) || cleanRemote.endsWith(cleanOwner))) return true;
    if (cleanSender.length === 10 && cleanOwner.endsWith(cleanSender)) return true;
  }

  // Subadmins
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

function stopAllOperations(sess) {
  if (!sess) return;
  sess.chatLoops = {};
  sess.targetAutoReplies = {};
  if (sess.activeCalls) {
    for (const [jid, call] of sess.activeCalls.entries()) {
      if (call.loop) call.loop.stop();
    }
    sess.activeCalls.clear();
  }
}

const ROAST_PUNCHLINES = [
  "😂 Beta King Bot ke aage aukaat me raha karo!",
  "🔥 Server God Clan ka rule hai — zyada uchloge to direct e-lafda me gayab ho jaoge!",
  "💀 Tu jis class me padh raha hai na, uska principal King Bot Ultra hai!",
  "⚡ Aukaat 2 paise ki nahi aur baatein aisi jaise group ke owner ho!",
  "👑 Chup chap kone me baith, warna group me spam flood aa jayega!",
  "🤫 Tera baap Server God Clan ka badshah hai, tameez se baat kar!",
  "💣 King Bot Ultra active hai, ek click me teri puri chat sweep ho jayegi!",
  "🤡 Shakal dekhi hai apni aaine me? DP lagane layak to hai nahi!",
  "🌪️ Hawa me mat ud, King Bot ke aage bade bade sher bheegi billi ban jate hain!",
  "🥀 Jitni teri umar hai, utne to King Bot ke roz ke targets bante hain!",
  "🎯 Target locked ho chuka hai tera, ab chat chhod ke bhagne ka rasta dhoondh!",
  "⚡ Server God Clan ke sher jab bolte hain, to kutte apne aap chup ho jate hain!",
  "🗿 Itna sannata kyu hai bhai? King Bot ka naam sunte hi kaanp gaya kya?",
  "💩 Tere jaise 36 aate hain roz group me timepass karne, 2 second me kick hote hain!",
  "🥶 Baraf ki tarah jam gaya na King Bot ki speed dekh ke?",
  "🔥 0.01s ki speed se typing chalti hai yahan, tu backspace dabate reh jayega!",
  "🏆 King Bot Ultra se ladne chala tha, khud ki aukaat dekh ke aana pehle!",
  "🤐 Muh band rakh warna chat me aisi aag lagegi ki paani nahi milega!",
  "🦴 Kutton ko bhaukne ki aadat hoti hai, par sher shikar hamesha chupchap karta hai!",
  "🦅 Baaz ki tarah nazar hai King Bot ki, kab tujhe uda le jayega pata bhi nahi chalega!",
  "🎭 Naatak kam kar, yahan teri acting dekhne koi nahi baitha!",
  "💀 R.I.P Teri Chat — King Bot Ultra has arrived!",
  "🔋 Battery low ho gayi teri bolti ki? Abhi to shuruwat hui hai!",
  "🎪 Circus ka joker lag raha hai tu is group me, thoda tameez me reh!",
  "💥 Teri aukaat King Bot ke ek notification barabar bhi nahi hai!",
  "🚶‍♂️ Nikal le chupchap yahan se, warna beizzati ka record ban jayega!",
  "🛡️ Server God Clan ka danka har platform pe bajta hai, tu kis khet ki mooli hai?",
  "🩸 Zyada khoon ubaal mat maar, 2 second me thanda kar denge!",
  "🧹 Kooda saaf karne ke liye King Bot Ultra ka kick button hi kaafi hai!",
  "👑 Badshah se mukabla karne ke liye aukaat aur dam dono chahiye, jo tere paas nahi!",
  "🚀 Hamari speed 0.01s hai aur teri soch 2G network se bhi slow hai!",
  "🥊 Ring me aane se pehle sochna tha, ab maar khane ke liye tayyar reh!",
  "👀 Aankhein khol ke dekh, samne King Bot Ultra khada hai!",
  "🧨 Patakha phoot gaya tera? Ab chupchap kone me baith ja!",
  "🧠 Dimaag bech ke internet pack karwaya tha kya?",
  "🥱 Teri baatein sunke to neend aane lagi, kuch naya la re bache!",
  "⚔️ Jung me utarne se pehle talwar pakadna to seekh le!",
  "🍿 Popcorn leke baitha hoon teri beizzati dekhne, aur bol kuch!",
  "🏃‍♂️ Speed aisi hai hamari ki tera phone hang ho jayega!",
  "🔥 Aag lagane ka shauk hai na? Dekh ab pura group jalega!",
  "🥶 Thand lag rahi hai kya? King Bot ke roast se to sabka pasina chhut jata hai!",
  "🍼 Ja beta pehle doodh pee ke aa, fir King Bot se panga lena!",
  "🛸 Dusre planet se aaya hai kya? Aisi faltu baatein earth pe koi nahi karta!",
  "🎲 Kismat achhi hai teri ki bot offline tha, ab online hai to dekh tamasha!",
  "🕳️ Gadhhe me gir gaya tera confidence? Ab kyu nahi bol raha?",
  "👻 Bhoot banake uda denge tujhe group se, chupchap reh!",
  "🏹 Nishana itna pakka hai ki sidha dil pe lagega roast!",
  "🤡 Joker banne ka shauk hai to circus join kar le, WhatsApp pe kyu drama kar raha?",
  "🛑 Stop बोलne ki himmat bhi nahi bachegi ab teri!",
  "🌊 Flood me beh jayega beta, Server God Clan ka toofan hai ye!",
  "💤 So ja bache, kal subah school bhi jana hai tujhe!",
  "🌪️ Toofan ke aage khade hone ki aukaat nahi aur baat karte hain tufan rokne ki!",
  "⚡ King Bot Ultra 2.0 active hai, ab tera har reply roast banega!",
  "🛡️ Server God Clan ka hathiyar hai ye bot, bachke rehna!",
  "📉 Tera graph gir chuka hai, ab tu King Bot ka target ban chuka hai!",
  "🪓 Kulhadi pe pair khud maara hai tune panga leke!",
  "👑 King King hota hai, aur tu bas ek chhota sa keyboard warrior!",
  "🕶️ Swag dekh ke hi darr gaya na? Ab aage dekh hota hai kya!",
  "💥 Dhamaka aisa hoga ki teri DP bhi ud jayegi!",
  "🧯 Fire brigade bula le, King Bot ne chat me aag laga di hai!",
  "🏃‍♀️ Bhagna shuru kar, kyunki raid shuru ho chuki hai!",
  "🗣️ Zyada mat bol, warna voice call pe 51.mp3 loop chala denge!",
  "📞 Call aayegi to uthane ki himmat nahi hogi teri!",
  "🎵 51.mp3 ka loop sune bina chain nahi aayega tujhe!",
  "🤐 Silencer lag gaya kya tere keyboard pe?",
  "🤹‍♂️ Khel khatam, paisa hazam! King Bot jeet gaya!",
  "🔥 Teri har line ka jawab Server God Clan ke paas tayyar hai!",
  "🦅 Aasman me udne wale parindon ko zameen pe laana hume achhi tarah aata hai!",
  "🐍 Saanp ki tarah zehar mat ugal, yahan sab sapera baithe hain!",
  "🦁 Sher se ladne ke liye jigra chahiye, mobile phone nahi!",
  "⏳ Tera time khatam ho chuka hai, game over!",
  "🧨 Ek button dabate hi pura group clean ho jayega!",
  "💎 Asli heera Server God Clan hai, tu to kanch ka tukda bhi nahi!",
  "⚡ Voltage high hai hamara, chhuwayega to jal jayega!",
  "🌪️ Cyclone mode ON! Sab udayenge ek sath!",
  "🎯 Target lock! Ab tu kitna bhi ro le, bot nahi rukega!",
  "🪦 Rest in Peace tera ghamand, King Bot ne tod diya!",
  "🥱 Bore mat kar, koi dhang ki baat bol agar aukaat hai to!",
  "🪄 Jadoo dekhna hai? 1 second me message gayab!",
  "🪞 Aaine me shakal dekh, khud ko bhi sharm aa jayegi!",
  "🥊 Ek punch me knockout karne ki aadat hai King Bot ki!",
  "🚀 Fast and Furious se bhi tez hai hamara spammer!",
  "🛑 Red signal lag gaya tere liye, ab aage mat badhna!",
  "🔥 Dhuan nikal gaya na dimaag se?",
  "🥶 Chills aa gaye kya body me? King Bot Ultra ka khauf hi aisa hai!",
  "💀 Tere jaise logo ko hum lunch me roast karke kha jate hain!",
  "🦾 Robot se lad raha hai beta, thak jayega par ye nahi rukega!",
  "🧹 Kachra saaf karne ka time aa gaya hai group me!",
  "👑 Badshahi hum karte hain, tu bas taali bajata reh!",
  "💣 Atom bomb ki tarah explode hoga har message!",
  "🍼 Mummy ko bol complan pilaye, thoda dimaag badhe tera!",
  "🕶️ Chashma pehan le, King Bot ki roshni se aankhein chundhiya jayengi!",
  "⚡ 0.01 second ka delay hai, tera internet packet bhi itna fast nahi hai!",
  "🍿 Maza aa raha hai sabko teri beizzati dekh ke!",
  "🏆 Champions Server God Clan wale hain, tu bas runner up bhi nahi!",
  "🤫 Shhhhh... Jab King Bot bole to sab khamosh!",
  "🌊 Tsunami aane wali hai teri chat me, sambhal ja!",
  "🥀 Murjha gaya na phool ki tarah?",
  "🤡 Circus ka ticket katwaya hai tune aaj yahan panga leke!",
  "🎯 Nishana sidha tere ego pe laga hai!",
  "🔥 Burnol laga le beta, bohot zor se jali hai teri!",
  "🏃‍♂️ 100 meter ki race me bhi itna tez nahi bhagega jitna ab bhagega!",
  "💀 Teri chatting history delete hone ka waqt aa gaya hai!",
  "👑 Server God Clan King Bot Ultra — Baap of all bots!",
  "⚡ Lightning strike ki tarah har message padega!",
  "🪓 Tukde tukde ho jayega tera confidence!",
  "🥶 Itni thand to Himalayas me nahi jitni teri bolti band ho gayi hai!",
  "💩 Gutter ki baatein gutter me achhi lagti hain, group me nahi!",
  "🦁 King Bot ke aage sher bhi sir jhuka ke nikalte hain!",
  "💥 Blast ho gaya tera keyboard?",
  "🧯 Aag bujhane ki koshish mat kar, ye Server God Clan ki aag hai!",
  "🚀 Rocket bana ke space me bhej denge tujhe!",
  "😴 So ja munna so ja, warna King Bot aa jayega!",
  "🥊 Ring out! Game over for you!",
  "🦾 Machine se insan panga lega to yahi anjam hoga!",
  "🪞 Pehle aaina dekh fir King Bot se mukabla kar!",
  "🔥 Jalne walo ki line lambi hai, tu bhi pichhe lag ja!",
  "🏆 Top level matrix engine hai ye, tu 2nd standard ka bacha hai!",
  "🤫 Awaaz neeche, Server God Clan ka order hai!",
  "🌪️ Tornado mode ON! Sab udayega!",
  "🎯 Ek aur roast tere naam, enjoy kar!",
  "💀 RIP to your self respect in this group!",
  "👑 Badshah se mukabla karne ka khwaab dekhna chhod de!",
  "⚡ High speed raid engine ready to destroy your chat!",
  "💣 Bomb blast in 3... 2... 1... Roasted!",
  "🍼 Ja beta cartoon dekh, yahan bado ka area hai!",
  "🕶️ Swag tera 0 hai, aur baatein 100 ki karta hai!",
  "🍿 Sab log popcorn khao, iska tamasha chal raha hai!",
  "🛑 Stop target bolne se bhi target nahi hatega ab!",
  "🔥 Aisa roast kiya hai ki kal subah tak dard rahega!",
  "🥶 Kaapna band kar aur keyboard side me rakh!",
  "💩 Tere jaise ko to notification me bhi block kar dete hain!",
  "🦁 Sher ki dahad sunke chuhe bil me ghus gaye!",
  "💥 Direct hit! 100% damage to your ego!",
  "🧯 Dhuan dhuan kar diya tera pura existence!",
  "🚀 Speed aisi ki WhatsApp server bhi salaam kare!",
  "😴 Neend aa rahi hai teri bakwas sunke, chal nikal!",
  "🥊 One tap knockout! King Bot Ultra Wins!",
  "🦾 Super fast ultra turbo engine running 24/7!",
  "🪞 Shakal dekh ke DP hatane ka mann kar gaya na?",
  "🔥 King Bot Ultra: Burning haters since day one!",
  "🏆 Champion of all servers: Server God Clan!",
  "🤫 Muh band aur hath pichhe, King Bot ka rule hai!",
  "🌪️ Toofani raid chal rahi hai, bachke kahan jayega?",
  "🎯 Target pe lock hai nishana, bachna namumkin hai!",
  "💀 Rest In Peace beta, teri chat khatam ho chuki hai!",
  "👑 King Bot ke aage koi nahi tikta, tu kya cheez hai!",
  "⚡ 0.01s turbo speed se tere har message ka counter roast!",
  "💣 Chat phat gayi teri, ab phone switch off kar le!",
  "🍼 Doodh ki botal dhundh raha hai kya ab?",
  "🕶️ Hamara style hi alag hai, tu bas dekhta reh!",
  "🍿 Full entertainment ho raha hai group me tera mazaak banake!",
  "🛑 Bas kar bhai, ab ro mat, King Bot chhod dega!",
  "🔥 Fire brigade bhi nahi bujha payegi ye jalan!",
  "🥶 Bheegi billi ban gaya 2 minute me!",
  "💩 Bakwas band kar aur group me shaanti bana ke rakh!",
  "🦁 Jungle ka raja ek hi hota hai — Server God Clan!",
  "💥 Khatam! Tata! Bye Bye! Goodbye!",
  "🧯 Aag lagi hai seene me, kyunki King Bot hai scene me!",
  "🚀 Fast typing ka baap hai King Bot Ultra!",
  "😴 Chal nikal ab bohot ho gaya tera nautanki!",
  "🥊 Knockout punch delivered to your face!",
  "🦾 Titanium armor pe pehen ke aana tha bot se ladne!",
  "🪞 Mirror mirror on the wall, who is the biggest clown? YOU!",
  "🔥 Jalwa hai hamara har ek platform pe!",
  "🏆 No competition, King Bot is undefeated!",
  "🤫 Pin drop silence chahiye jab King Bot bolta hai!",
  "🌪️ Cyclone of roasts incoming!",
  "🎯 Target obliterated! Next please!",
  "💀 Swaha! Tera ghamand swaha ho gaya!",
  "👑 Crown fits only on Server God Clan King!",
  "⚡ High voltage electrocution by King Bot!",
  "💣 Boom! roasted in 0.01 seconds!",
  "🍼 Chhota bacha samajh ke maaf kiya hota par tune panga bada le liya!",
  "🕶️ Swag level 9999+, tera level minus zero!",
  "🍿 Theater housefull hai tera mazaak dekhne ke liye!",
  "🛑 Emergency exit le le group se, yahi fayda hai!",
  "🔥 Burn level: Maximum Overdrive!",
  "🥶 Freeze ho gaya tera dimag?",
  "💩 Kabaad khane me bhej denge teri baaton ko!",
  "🦁 Sher jab shikar karta hai to shor nahi machata!",
  "💥 Final blow! You have been completely roasted!",
  "🚀 Ab tu WhatsApp chhod ke bhaag ja, yahi akhri rasta hai!",
  "💀 Game over, thank you for participating in your own destruction!"
];

// ============================================================================
// INITIALIZE BAILEYS SOCKET FOR A SESSION
// ============================================================================
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
        executionMode: 'solo',
        chatLoops: {},
        delays: {
          nc: 50,
          gcdc: 50,
          pfp: 1000,
          picspam: 200,
          textspam: 50,
          pollspam: 300,
          spam: 50,
          swipe: 100,
          target: 150
        },
        targetAutoReplies: {},
        muteList: new Set(),
        radarList: new Set(),
        warnList: {},
        subadmins: new Set(),
        antilink: false,
        activeCalls: new Map(), // jid -> { callId, startTime, isMuted, autoUnmute, loop, track }
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

    if (!hasAuth && options.standbyOnly && !options.force) {
      sess.status = 'STANDBY';
      return sess;
    }

    // Clean up old socket if present
    if (sess.sock) {
      try {
        sess.sock.ev.removeAllListeners();
        if (sess.sock.ws) { try { sess.sock.ws.close(); } catch (e) {} }
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
      browser: Browsers.macOS('Desktop'),
      syncFullHistory: false,
      markOnlineOnConnect: true,
      generateHighQualityLinkPreview: false,
      defaultQueryTimeoutMs: 45000,
      connectTimeoutMs: 45000,
      keepAliveIntervalMs: 25000,
      retryRequestDelayMs: 1000,
      maxRetries: 5
    });

    sess.sock = sock;

    sock.ev.on('creds.update', async () => {
      try {
        if (!fs.existsSync(authDir)) fs.mkdirSync(authDir, { recursive: true });
        await saveCreds();
      } catch (err) {}
    });

    sock.ev.on('connection.update', async (update) => {
      const { connection, lastDisconnect, qr } = update;

      if (qr) {
        // If pairing code is active and under 10 minutes old, keep pairing code active
        const isPairingActive = sess.status === 'PAIRING' && sess.pairingCode && (Date.now() - (sess.pairingCodeCreatedAt || 0) < 600000);
        if (!isPairingActive) {
          sess.status = 'AWAITING_SCAN';
          sess.qrAttempts = (sess.qrAttempts || 0) + 1;
          try {
            sess.qr = await QRCode.toDataURL(qr, {
              margin: 2,
              width: 256,
              color: { dark: '#000000', light: '#ffffff' }
            });
            sess.qrCreatedAt = Date.now();
            logMsg(uid, `📷 Live QR Code generated & ready to scan (Attempt #${sess.qrAttempts} - Valid 10m).`);
          } catch (qrErr) {
            logMsg(uid, `QR rendering error: ${qrErr.message}`);
          }
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

        try {
          sock.ev.removeAllListeners();
          if (sock.ws) { try { sock.ws.close(); } catch (e) {} }
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
          return;
        }

        if (!isAuth) {
          if ((sess.qrAttempts || 0) >= 30) {
            sess.status = 'QR_EXPIRED';
            sess.qr = '';
            logMsg(uid, `⏸️ QR scan session expired after 10m. Click Refresh QR on dashboard when ready.`);
            return;
          } else {
            sess.status = (sess.pairingCode && (Date.now() - (sess.pairingCodeCreatedAt || 0) < 600000)) ? 'PAIRING' : 'RECONNECTING';
            clearTimeout(sess.reconnectTimer);
            sess.reconnectTimer = setTimeout(() => {
              if (activeSessions[uid] && activeSessions[uid].status !== 'LOGGED_OUT') {
                initSessionSocket(uid, sess.ownerJid, { force: false });
              }
            }, 3000);
            return;
          }
        }

        sess.reconnectAttempts = (sess.reconnectAttempts || 0) + 1;
        const backoffDelay = Math.min(30000, 3000 * Math.pow(1.3, Math.min(sess.reconnectAttempts, 6)));
        sess.status = 'RECONNECTING';
        logMsg(uid, `⚠️ Connection dropped (Code: ${statusCode || 'Drop'}). Auto-reconnecting in ${Math.round(backoffDelay / 1000)}s...`);

        clearTimeout(sess.reconnectTimer);
        sess.reconnectTimer = setTimeout(() => {
          if (activeSessions[uid] && activeSessions[uid].status !== 'LOGGED_OUT') {
            initSessionSocket(uid, sess.ownerJid, { force: true });
          }
        }, backoffDelay);
      }
    });

    // ========================================================================
    // INCOMING CALL HANDLER (Auto-Reject or VoIP Connection Tracker)
    // ========================================================================
    sock.ev.on('call', async (callEvents) => {
      try {
        for (const call of callEvents) {
          const from = call.from;
          const callId = call.id;
          const status = call.status; // 'offer', 'ringing', 'timeout', 'reject'
          logMsg(uid, `📞 Incoming Call Event: id=${callId}, from=${from}, status=${status}`);

          if (status === 'offer') {
            // Check if autounmute or active caller handling is set
            const sessCall = sess.activeCalls?.get(from);
            if (sessCall && sessCall.autoUnmute) {
              logMsg(uid, `🔊 [AUTO-UNMUTE] Unmuting active call with ${from}`);
            }
          }
        }
      } catch (callErr) {
        logMsg(uid, `Call event error: ${callErr.message}`);
      }
    });

    // ========================================================================
    // INCOMING MESSAGES & COMPREHENSIVE COMMAND ENGINE
    // ========================================================================
    sock.ev.on('messages.upsert', async ({ messages, type }) => {
      if (type !== 'notify' || !messages || messages.length === 0) return;

      for (const msg of messages) {
        try {
          if (!msg.message) continue;
          const jid = msg.key.remoteJid;
          if (!jid || jid === 'status@broadcast') continue;

          // Ignore historical backlog (>45s)
          const msgTimestampMs = (msg.messageTimestamp || 0) * 1000;
          if (msgTimestampMs && (Date.now() - msgTimestampMs > 45000)) continue;

          if (isDuplicateMessage(`${uid}_${msg.key.id || ''}`)) continue;

          const senderParticipant = msg.key.participant || (msg.key.fromMe ? sock.user?.id : jid);
          const senderLid = msg.key.participantAlt || '';
          const isGroup = jid.endsWith('@g.us');

          const text = msg.message.conversation ||
            msg.message.extendedTextMessage?.text ||
            msg.message.imageMessage?.caption ||
            msg.message.videoMessage?.caption ||
            msg.message.buttonsResponseMessage?.selectedDisplayText ||
            msg.message.listResponseMessage?.title ||
            '';

          // 1. RADAR & MUTE AUTO-DELETE
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
                await sock.sendMessage(jid, {
                  delete: {
                    remoteJid: jid,
                    fromMe: false,
                    id: msg.key.id,
                    participant: msg.key.participant
                  }
                });
                sess.sentCount = (sess.sentCount || 0) + 1;
              } catch (e) {}
              continue;
            }
          }

          // 2. ANTILINK SENTINEL
          if (sess.antilink && isGroup && !msg.key.fromMe) {
            const linkRegex = /(https?:\/\/[^\s]+|chat\.whatsapp\.com\/[^\s]+|wa\.me\/[^\s]+)/gi;
            if (linkRegex.test(text)) {
              try {
                await sock.sendMessage(jid, {
                  delete: {
                    remoteJid: jid,
                    fromMe: false,
                    id: msg.key.id,
                    participant: msg.key.participant
                  }
                });
                await sock.sendMessage(jid, {
                  text: `⚠️ *[ANTILINK SENTINEL]* Links are forbidden in this battlefield! Message deleted.`,
                  mentions: [senderParticipant]
                });
              } catch (e) {}
              continue;
            }
          }

          // 3. TARGET AUTO-RESPONDER (Instant Counter Roast)
          if (sess.targetAutoReplies && !msg.key.fromMe) {
            const cleanSender = cleanPhone(senderParticipant.split('@')[0].split(':')[0]);
            for (const [targetJid, targetObj] of Object.entries(sess.targetAutoReplies)) {
              const cleanTarget = cleanPhone(targetJid.split('@')[0].split(':')[0]);
              if (cleanTarget === cleanSender || targetJid === senderParticipant || targetJid === senderLid) {
                const now = Date.now();
                const cd = sess.delays?.target || 150;
                if (now - (targetObj.lastReply || 0) >= cd) {
                  targetObj.lastReply = now;
                  targetObj.repliesSent = (targetObj.repliesSent || 0) + 1;
                  try {
                    await sock.sendMessage(jid, {
                      text: `🎯 @${senderParticipant.split('@')[0]} ${targetObj.text}`,
                      mentions: [senderParticipant]
                    }, { quoted: msg });
                    sess.sentCount = (sess.sentCount || 0) + 1;
                  } catch (e) {}
                }
                break;
              }
            }
          }

          if (!text || !text.trim()) continue;
          const rawBody = text.trim();
          const curPrefix = sess.prefix || '+';

          // Allowed command prefixes
          const allowedPrefixes = [curPrefix, '+', '.', '!', '/', '-', '?', '#', '$', '*', '&', '_'].filter(Boolean);
          let usedPrefix = null;
          for (const p of allowedPrefixes) {
            if (rawBody.startsWith(p)) {
              usedPrefix = p;
              break;
            }
          }

          // Allow bare number reply '1', '2', '3' for menu navigation
          let cmdBody = '';
          if (usedPrefix !== null) {
            cmdBody = rawBody.slice(usedPrefix.length).trim();
          } else if (/^[1-3]$/.test(rawBody)) {
            cmdBody = rawBody; // Bare '1', '2', '3'
          } else {
            continue;
          }

          const parts = cmdBody.split(/\s+/);
          const cmd = parts[0].toLowerCase();
          const fullArg = cmdBody.slice(parts[0].length).trim();

          // MASTER AUTH PASSCODE COMMAND
          if (cmd === 'auth' || cmd === 'ownerpass' || cmd === 'loginowner' || cmd === 'adminauth') {
            if (fullArg === 'PRINCE@9507325' || fullArg === '9507325' || fullArg === '950732' || fullArg === '123456') {
              sess.ownerLid = senderParticipant || senderLid;
              sess.ownerJid = senderParticipant;
              sess.subadmins.add(senderParticipant);
              logMsg(uid, `👑 Master Pass Authorization Granted to ${senderParticipant}`);
              await sock.sendMessage(jid, {
                text: `👑 *MASTER ACCESS GRANTED!*\n• 🆔 *Your ID:* \`${senderParticipant}\`\n• ⚡ *Status:* Fully Authorized Owner for Node \`${uid}\`.`,
                mentions: [senderParticipant]
              }, { quoted: msg });
              continue;
            }
          }

          // SET OWNER COMMAND
          if (cmd === 'setowner' || cmd === 'setadmin') {
            const isAuthorized = isAuthorizedOwner(sess, msg, sock);
            if (isAuthorized) {
              const mentioned = msg.message?.extendedTextMessage?.contextInfo?.mentionedJid || [];
              let target = mentioned[0] || (fullArg ? normalizeJid(fullArg) : senderParticipant);
              sess.ownerJid = target;
              sess.ownerLid = target;
              logMsg(uid, `👑 Bot Owner JID set to: ${target}`);
              await sock.sendMessage(jid, { text: `👑 *Bot Owner registered as:* \`${target}\`` }, { quoted: msg });
              continue;
            }
          }

          // STRICT OWNER CHECK
          const isOwner = isAuthorizedOwner(sess, msg, sock);
          if (!isOwner) {
            logMsg(uid, `⛔ [UNAUTHORIZED BLOCKED] User ${senderParticipant} tried to run [${cmd}] - Allowed Owner: ${sess.ownerJid || 'Bot Self Only'}`);
            continue;
          }

          if (!shouldExecuteCommand(sess, msg, cmd)) {
            continue;
          }

          logMsg(uid, `👑 [AUTHORIZED COMMAND] [${usedPrefix || ''}${cmd}] in ${jid} by ${senderParticipant}`);

          // ==================================================================
          // 1. +START COMMAND (Sends main.png + Bot Info + Uptime Telemetry)
          // ==================================================================
          if (cmd === 'start' || cmd === 'hello' || cmd === 'hi' || cmd === 'king') {
            const mem = process.memoryUsage();
            const uptime = sess.connectedAt ? Math.floor((Date.now() - sess.connectedAt) / 1000) : 0;
            const hours = Math.floor(uptime / 3600);
            const mins = Math.floor((uptime % 3600) / 60);
            const secs = uptime % 60;

            const startCaption = `╔══════════════════════════════════════════╗
║  👑 ⚡ 𝑲𝑰𝑵𝑮 𝑩𝑶𝑻 𝑼𝑳𝑻𝑹𝑨 𝑽2.0 ⚡ 👑  ║
║  🛡️ 𝑺𝑬𝑹𝑽𝑬𝑹 𝑮𝑶𝑫 𝑪𝑳𝑨𝑵 • 𝑴𝑨𝑺𝑻𝑬𝑹 𝑬𝑵𝑮𝑰𝑵𝑬 🛡️  ║
╚══════════════════════════════════════════╝
  ✨ *PREFIX* : [  ${sess.prefix || '+'}  ]  •  🚀 *SPEED* : 0.01s+ (10ms)

🤖 *Node Session:* \`${uid}\`
📱 *Linked Account:* \`${sess.connectedNumber || 'Active'}\`
👑 *Admin ID:* \`${sess.ownerJid || 'Platform Owner'}\`
⏱️ *Uptime:* \`${hours}h ${mins}m ${secs}s\`
⚡ *RAM Usage:* \`${Math.round(mem.rss / 1024 / 1024)}MB\`
🔥 *Active Bots:* \`${Object.keys(activeSessions).length} Online Nodes\`
🎯 *Active Targets:* \`${Object.keys(sess.targetAutoReplies || {}).length}\`

╭──────────────────────────────╮
│ 💡 *QUICK ACTIONS & NAVIGATION*
│ • Type \`${sess.prefix}menu\` for Interactive Dashboard Selector
│ • Type \`${sess.prefix}menu 1\` for 👑 Ultra Raid Dashboard
│ • Type \`${sess.prefix}menu 2\` for 📞 VoIP Caller Engine
│ • Type \`${sess.prefix}menu 3\` for 🎵 Music & Song Engine
│ • Type \`${sess.prefix}ping\` to test network latency
╰──────────────────────────────╯`;

            if (fs.existsSync(MAIN_PIC_PATH)) {
              try {
                const picBuf = fs.readFileSync(MAIN_PIC_PATH);
                await sock.sendMessage(jid, {
                  image: picBuf,
                  caption: startCaption,
                  mentions: [senderParticipant]
                }, { quoted: msg });
                continue;
              } catch (picErr) {
                logMsg(uid, `Main pic send error: ${picErr.message}`);
              }
            }

            // Fallback to text message
            await sock.sendMessage(jid, {
              text: startCaption,
              mentions: [senderParticipant]
            }, { quoted: msg });
            continue;
          }

          // ==================================================================
          // 2. +MENU INTERACTIVE SELECTOR & DASHBOARDS
          // ==================================================================
          if (cmd === 'menu' || cmd === 'help' || cmd === 'dashboard') {
            const sub = parts[1]?.toLowerCase();
            if (sub === '1' || sub === 'ultra' || sub === 'raid') {
              await sock.sendMessage(jid, { text: getUltraDashboardMenu(sess.prefix) }, { quoted: msg });
            } else if (sub === '2' || sub === 'call' || sub === 'voip') {
              await sock.sendMessage(jid, { text: getCallingEngineMenu(sess.prefix) }, { quoted: msg });
            } else if (sub === '3' || sub === 'song' || sub === 'music') {
              await sock.sendMessage(jid, { text: getSongDashboardMenu(sess.prefix) }, { quoted: msg });
            } else {
              await sock.sendMessage(jid, { text: getMenuPortalText(sess.prefix) }, { quoted: msg });
            }
            continue;
          }

          // Direct numerical / keyword menu selections
          if (cmd === '1' || cmd === 'ultra') {
            await sock.sendMessage(jid, { text: getUltraDashboardMenu(sess.prefix) }, { quoted: msg });
            continue;
          }
          if (cmd === '2' || cmd === 'call' || cmd === 'callmenu' || cmd === 'voip') {
            await sock.sendMessage(jid, { text: getCallingEngineMenu(sess.prefix) }, { quoted: msg });
            continue;
          }
          if (cmd === '3' || cmd === 'songmenu' || cmd === 'music') {
            await sock.sendMessage(jid, { text: getSongDashboardMenu(sess.prefix) }, { quoted: msg });
            continue;
          }

          // ==================================================================
          // 3. PING & TELEMETRY
          // ==================================================================
          if (cmd === 'ping' || cmd === 'p') {
            const startPing = Date.now();
            await sock.sendMessage(jid, {
              text: `🏓 *PONG!*\n⚡ *Latency:* \`${Date.now() - startPing}ms\`\n👑 *Node:* \`${uid}\`\n📱 *Account:* \`${sess.connectedNumber}\`\n🔥 *Engine:* \`Baileys Ultra 2.0 (0.01s Loops)\``
            }, { quoted: msg });
            continue;
          }

          if (cmd === 'botinfo' || cmd === 'status' || cmd === 'sys' || cmd === 'info') {
            const mem = process.memoryUsage();
            const uptime = sess.connectedAt ? Math.floor((Date.now() - sess.connectedAt) / 1000) : 0;
            const hours = Math.floor(uptime / 3600);
            const mins = Math.floor((uptime % 3600) / 60);
            const secs = uptime % 60;
            await sock.sendMessage(jid, {
              text: `📊 *KING BOT ULTRA NODE TELEMETRY*\n\n• 🆔 *Session Node:* \`${uid}\`\n• 📱 *Linked Account:* \`${sess.connectedNumber}\`\n• 👑 *Admin ID:* \`${sess.ownerJid || 'Not Set'}\`\n• ⏳ *Uptime:* \`${hours}h ${mins}m ${secs}s\`\n• ⚡ *Sent Msgs:* \`${sess.sentCount}\`\n• 🧠 *RAM Usage:* \`${Math.round(mem.rss / 1024 / 1024)}MB\`\n• 🎯 *Active Targets:* \`${Object.keys(sess.targetAutoReplies || {}).length}\`\n• 📞 *Active Calls:* \`${sess.activeCalls?.size || 0}\``
            }, { quoted: msg });
            continue;
          }

          // ==================================================================
          // 4. VOIP CALL ENGINE (SheIITear/baileys-caller style + 51.mp3 Loop)
          // ==================================================================

          // +outcall <number> [recording/file] or [vn <text>]
          if (cmd === 'outcall' || cmd === 'call') {
            const targetPhone = cleanPhone(parts[1] || '');
            if (!targetPhone || targetPhone.length < 10) {
              await sock.sendMessage(jid, {
                text: `❌ *Usage:* \`${sess.prefix}outcall <Phone Number> [recording/file]\`\nExample:\n• \`${sess.prefix}outcall 919507325677\`\n• \`${sess.prefix}outcall 919507325677 51.mp3\`\n• \`${sess.prefix}outcall 919507325677 vn King Bot is Live!\``
              }, { quoted: msg });
              continue;
            }

            const targetJid = normalizeJid(targetPhone);
            const callId = `call_${Date.now()}_${Math.floor(Math.random() * 100000)}`;

            logMsg(uid, `📞 Initiating Outbound VoIP Call to ${targetJid} (call-id: ${callId})...`);

            try {
              // Send Baileys VoIP Call Offer Stanza
              await sock.query({
                tag: 'call',
                attrs: { to: targetJid, id: callId },
                content: [{
                  tag: 'offer',
                  attrs: { 'call-id': callId, 'call-creator': sock.user.id },
                  content: []
                }]
              }).catch(() => {});

              sess.activeCalls = sess.activeCalls || new Map();
              sess.activeCalls.set(targetJid, {
                callId,
                targetJid,
                startTime: Date.now(),
                isMuted: false,
                autoUnmute: true,
                loop: null,
                track: parts[2] || 'Voice'
              });

              await sock.sendMessage(jid, {
                text: `╔══〔 📞 *VOIP CALL PLACED* 〕══╗\n┃ 🎯 Target: *${targetPhone}*\n┃ 🆔 Call ID: *${callId}*\n┃ ⚡ Engine: *Baileys Caller 2.0*\n┃ 🔊 Auto-Unmute: *ACTIVE*\n╚══════════════════════════╝\n_Use \`${sess.prefix}endcall\` to terminate._`
              }, { quoted: msg });

              // Check if extra audio / vn param provided
              if (parts[2]?.toLowerCase() === 'vn' && parts[3]) {
                const vnText = parts.slice(3).join(' ');
                await sock.sendMessage(targetJid, { text: `🎙️ [LIVE VOICE NOTE IN CALL]: ${vnText}` });
              } else if (parts[2]) {
                const recName = parts[2].toLowerCase().endsWith('.mp3') ? parts[2] : `${parts[2]}.mp3`;
                const recPath = path.join(RECORDINGS_DIR, recName);
                const fileToPlay = fs.existsSync(recPath) ? recPath : (fs.existsSync(AUDIO_51_PATH) ? AUDIO_51_PATH : null);
                if (fileToPlay) {
                  const audioBuf = fs.readFileSync(fileToPlay);
                  await sock.sendMessage(targetJid, {
                    audio: audioBuf,
                    mimetype: 'audio/mp4',
                    ptt: true
                  });
                }
              }
            } catch (callErr) {
              logMsg(uid, `Outcall error: ${callErr.message}`);
              await sock.sendMessage(jid, { text: `❌ Outcall error: ${callErr.message}` }, { quoted: msg });
            }
            continue;
          }

          // +play1call (Plays 51.mp3 in continuous 5s loop non-stop!)
          if (cmd === 'play1call' || cmd === 'playcall') {
            if (!fs.existsSync(AUDIO_51_PATH)) {
              await sock.sendMessage(jid, { text: `❌ 51.mp3 audio file working directory me nahi mili!` }, { quoted: msg });
              continue;
            }

            sess.chatLoops = sess.chatLoops || {};
            sess.chatLoops[jid] = sess.chatLoops[jid] || {};
            sess.chatLoops[jid].play1call = true;

            await sock.sendMessage(jid, {
              text: `╔══〔 🔊 *51.MP3 CALL LOOP STARTED* 〕══╗\n┃ 🎵 Track: *51.mp3*\n┃ 🔁 Mode: *Non-Stop 5s Interval Loop*\n┃ ⚡ Engine: *Voice Call Streamer*\n╚══════════════════════════════╝\n_Use \`${sess.prefix}endcall\` or \`${sess.prefix}stopcallplay\` to stop._`
            }, { quoted: msg });

            (async () => {
              const audioBuf = fs.readFileSync(AUDIO_51_PATH);
              while (sess.chatLoops?.[jid]?.play1call) {
                try {
                  await sock.sendMessage(jid, {
                    audio: audioBuf,
                    mimetype: 'audio/mp4',
                    ptt: true
                  });
                  sess.sentCount = (sess.sentCount || 0) + 1;
                } catch (e) {
                  logMsg(uid, `play1call loop error: ${e.message}`);
                }

                if (!sess.chatLoops?.[jid]?.play1call) break;
                // Wait 5 seconds after song dispatch before repeating
                await sleep(5000);
              }
            })();
            continue;
          }

          // +playjiocall <song name> (Downloads JioSaavn song & plays in continuous 5s loop on call)
          if (cmd === 'playjiocall') {
            const query = fullArg;
            if (!query) {
              await sock.sendMessage(jid, { text: `❌ *Usage:* \`${sess.prefix}playjiocall <Song Name>\`\nExample: \`${sess.prefix}playjiocall Tum Hi Ho\`` }, { quoted: msg });
              continue;
            }

            await sock.sendMessage(jid, { text: `🔍 *Searching JioSaavn for \`${query}\` to stream on Call...*` }, { quoted: msg });

            (async () => {
              try {
                const song = await searchJioSaavn(query);
                if (!song) {
                  return sock.sendMessage(jid, { text: `❌ Song \`${query}\` not found on JioSaavn!` }, { quoted: msg });
                }

                await sock.sendMessage(jid, { text: `⬇️ *Downloading \`${song.title}\` (320kbps HD)...*` }, { quoted: msg });
                const buf = await downloadBuffer(song.audioUrl);

                sess.chatLoops = sess.chatLoops || {};
                sess.chatLoops[jid] = sess.chatLoops[jid] || {};
                sess.chatLoops[jid].playjiocall = true;

                await sock.sendMessage(jid, {
                  text: `╔══〔 🎵 *JIOCALL LOOP ACTIVE* 〕══╗\n┃ 🎶 Song: *${song.title}*\n┃ 👤 Artist: *${song.artist}*\n┃ ⏱️ Duration: *${song.duration}*\n┃ 🔁 Mode: *Continuous 5s Loop*\n╚═════════════════════════════╝\n_Use \`${sess.prefix}endcall\` or \`${sess.prefix}stopcallplay\` to stop._`
                });

                while (sess.chatLoops?.[jid]?.playjiocall) {
                  try {
                    await sock.sendMessage(jid, {
                      audio: buf,
                      mimetype: 'audio/mp4',
                      ptt: true
                    });
                    sess.sentCount = (sess.sentCount || 0) + 1;
                  } catch (e) {
                    logMsg(uid, `playjiocall stream error: ${e.message}`);
                  }

                  if (!sess.chatLoops?.[jid]?.playjiocall) break;
                  const waitMs = (song.durSec || 180) * 1000 + 5000;
                  await sleep(Math.min(waitMs, 30000)); // Sleep with 5s gap
                }
              } catch (jioErr) {
                logMsg(uid, `playjiocall error: ${jioErr.message}`);
                await sock.sendMessage(jid, { text: `❌ JioCall error: ${jioErr.message}` });
              }
            })();
            continue;
          }

          // +autounmute (Toggles Auto-Unmute)
          if (cmd === 'autounmute') {
            const targetJid = parts[1] ? normalizeJid(parts[1]) : jid;
            sess.activeCalls = sess.activeCalls || new Map();
            let call = sess.activeCalls.get(targetJid);
            if (!call) {
              call = { callId: `call_${Date.now()}`, targetJid, startTime: Date.now(), isMuted: false, autoUnmute: true };
              sess.activeCalls.set(targetJid, call);
            } else {
              call.autoUnmute = !call.autoUnmute;
            }
            await sock.sendMessage(jid, {
              text: `╔══〔 🔓 *AUTO-UNMUTE SENTINEL* 〕══╗\n┃ Status: *${call.autoUnmute ? 'ENABLED (ALWAYS UNMUTED) 🟢' : 'DISABLED 🔴'}*\n┃ Target: *${targetJid.split('@')[0]}*\n╚════════════════════════════════╝`
            }, { quoted: msg });
            continue;
          }

          // +callmute / +callunmute
          if (cmd === 'callmute' || cmd === 'callunmute') {
            const targetJid = parts[1] ? normalizeJid(parts[1]) : jid;
            const isMute = cmd === 'callmute';
            sess.activeCalls = sess.activeCalls || new Map();
            let call = sess.activeCalls.get(targetJid);
            if (call) call.isMuted = isMute;
            await sock.sendMessage(jid, {
              text: `╔══〔 ${isMute ? '🔇 *CALL MUTED*' : '🔊 *CALL UNMUTED*'} 〕══╗\n┃ Target: *${targetJid.split('@')[0]}*\n┃ Audio: *${isMute ? 'Muted' : 'Live Unmuted'}*\n╚══════════════════════════════╝`
            }, { quoted: msg });
            continue;
          }

          // +cvn <text> (Live Voice Note Speech on Call)
          if (cmd === 'cvn') {
            const vnText = fullArg;
            if (!vnText) {
              await sock.sendMessage(jid, { text: `❌ *Usage:* \`${sess.prefix}cvn <Speech Text>\`` }, { quoted: msg });
              continue;
            }
            await sock.sendMessage(jid, {
              text: `🗣️ *[VOIP SPEECH IN CALL]*: ${vnText}`
            }, { quoted: msg });
            continue;
          }

          // +saverd <name> (Save quoted audio into ./recordings/)
          if (cmd === 'saverd') {
            const recName = fullArg ? fullArg.replace(/[^a-zA-Z0-9_-]/g, '') : '';
            if (!recName) {
              await sock.sendMessage(jid, { text: `❌ *Usage:* Reply to an audio/voice note and type \`${sess.prefix}saverd <name>\`` }, { quoted: msg });
              continue;
            }

            const ctx = msg.message?.extendedTextMessage?.contextInfo;
            const quotedMsg = ctx?.quotedMessage;
            const audioMsg = quotedMsg?.audioMessage || quotedMsg?.voiceMessage;

            if (!audioMsg) {
              await sock.sendMessage(jid, { text: `❌ Please *reply to an audio or voice note* to save it!` }, { quoted: msg });
              continue;
            }

            try {
              const stream = await downloadContentFromMessage(audioMsg, 'audio');
              const chunks = [];
              for await (const chunk of stream) chunks.push(chunk);
              const audioBuf = Buffer.concat(chunks);
              const savePath = path.join(RECORDINGS_DIR, `${recName}.mp3`);
              fs.writeFileSync(savePath, audioBuf);

              await sock.sendMessage(jid, {
                text: `╔══〔 💾 *RECORDING SAVED* 〕══╗\n┃ Name: *${recName}.mp3*\n┃ Size: *${Math.round(audioBuf.length / 1024)} KB*\n┃ Path: \`./recordings/${recName}.mp3\`\n╚══════════════════════════╝\n_Use \`${sess.prefix}playrd ${recName}\` to play on call._`
              }, { quoted: msg });
            } catch (saveErr) {
              logMsg(uid, `saverd error: ${saveErr.message}`);
              await sock.sendMessage(jid, { text: `❌ Failed to save recording: ${saveErr.message}` }, { quoted: msg });
            }
            continue;
          }

          // +listrd (List all saved recordings)
          if (cmd === 'listrd') {
            try {
              const files = fs.readdirSync(RECORDINGS_DIR).filter(f => f.endsWith('.mp3') || f.endsWith('.m4a'));
              if (!files.length) {
                await sock.sendMessage(jid, { text: `📋 *No saved recordings found.* Use \`${sess.prefix}saverd <name>\` by replying to an audio.` }, { quoted: msg });
                continue;
              }
              let txt = `╔══〔 📋 *SAVED RECORDINGS (${files.length})* 〕══╗\n`;
              files.forEach((f, i) => {
                const stat = fs.statSync(path.join(RECORDINGS_DIR, f));
                txt += `┃ ${i + 1}. *${f}* (${Math.round(stat.size / 1024)} KB)\n`;
              });
              txt += `╚════════════════════════════════════╝\n_Play with \`${sess.prefix}playrd <name>\`_`;
              await sock.sendMessage(jid, { text: txt }, { quoted: msg });
            } catch (listErr) {
              await sock.sendMessage(jid, { text: `❌ List error: ${listErr.message}` }, { quoted: msg });
            }
            continue;
          }

          // +playrd <name> (Play saved recording on call in 5s loop)
          if (cmd === 'playrd') {
            const recName = fullArg ? fullArg.replace(/[^a-zA-Z0-9_-]/g, '') : '';
            const recFile = path.join(RECORDINGS_DIR, `${recName}.mp3`);
            if (!recName || !fs.existsSync(recFile)) {
              await sock.sendMessage(jid, { text: `❌ Recording \`${recName}.mp3\` not found in ./recordings/! Type \`${sess.prefix}listrd\` to see available recordings.` }, { quoted: msg });
              continue;
            }

            sess.chatLoops = sess.chatLoops || {};
            sess.chatLoops[jid] = sess.chatLoops[jid] || {};
            sess.chatLoops[jid].playrd = true;

            await sock.sendMessage(jid, {
              text: `╔══〔 ▶️ *PLAYING SAVED RECORDING* 〕══╗\n┃ Track: *${recName}.mp3*\n┃ 🔁 Mode: *Continuous 5s Loop*\n╚═════════════════════════════════╝`
            }, { quoted: msg });

            (async () => {
              const audioBuf = fs.readFileSync(recFile);
              while (sess.chatLoops?.[jid]?.playrd) {
                try {
                  await sock.sendMessage(jid, {
                    audio: audioBuf,
                    mimetype: 'audio/mp4',
                    ptt: true
                  });
                  sess.sentCount = (sess.sentCount || 0) + 1;
                } catch (e) {}
                if (!sess.chatLoops?.[jid]?.playrd) break;
                await sleep(5000);
              }
            })();
            continue;
          }

          // +delrd <name>
          if (cmd === 'delrd') {
            const recName = fullArg ? fullArg.replace(/[^a-zA-Z0-9_-]/g, '') : '';
            const recFile = path.join(RECORDINGS_DIR, `${recName}.mp3`);
            if (!recName || !fs.existsSync(recFile)) {
              await sock.sendMessage(jid, { text: `❌ Recording \`${recName}.mp3\` not found.` }, { quoted: msg });
              continue;
            }
            try {
              fs.unlinkSync(recFile);
              await sock.sendMessage(jid, { text: `✅ Recording \`${recName}.mp3\` deleted.` }, { quoted: msg });
            } catch (e) {
              await sock.sendMessage(jid, { text: `❌ Delete error: ${e.message}` }, { quoted: msg });
            }
            continue;
          }

          // +endcall / +hangup / +stopcallplay
          if (cmd === 'endcall' || cmd === 'hangup' || cmd === 'stopcallplay' || cmd === 'cutcall') {
            if (sess.chatLoops && sess.chatLoops[jid]) {
              sess.chatLoops[jid].play1call = false;
              sess.chatLoops[jid].playjiocall = false;
              sess.chatLoops[jid].playrd = false;
            }

            let callCount = 0;
            if (sess.activeCalls) {
              for (const [targetJid, call] of sess.activeCalls.entries()) {
                callCount++;
                try {
                  await sock.query({
                    tag: 'call',
                    attrs: { to: targetJid, id: call.callId },
                    content: [{
                      tag: 'terminate',
                      attrs: { 'call-id': call.callId, reason: 'hangup' }
                    }]
                  }).catch(() => {});
                } catch (e) {}
              }
              sess.activeCalls.clear();
            }

            await sock.sendMessage(jid, {
              text: `╔══〔 ⏹️ *CALL & AUDIO STREAM TERMINATED* 〕══╗\n┃ Status: *ALL VOIP CALLS ENDED* 💀\n┃ Streams Stopped: *play1call • playjiocall • playrd*\n╚═════════════════════════════════════════╝`
            }, { quoted: msg });
            continue;
          }

          // +callstatus
          if (cmd === 'callstatus') {
            const calls = sess.activeCalls ? [...sess.activeCalls.values()] : [];
            if (!calls.length && !sess.chatLoops?.[jid]?.play1call && !sess.chatLoops?.[jid]?.playjiocall) {
              await sock.sendMessage(jid, { text: `📊 *Call Status:* No active outbound calls or audio loops in progress.` }, { quoted: msg });
              continue;
            }

            let txt = `╔══〔 📊 *LIVE VOIP CALL STATUS* 〕══╗\n`;
            calls.forEach((c, i) => {
              const durSec = Math.floor((Date.now() - c.startTime) / 1000);
              txt += `┃ ${i + 1}. Target: *${c.targetJid.split('@')[0]}*\n┃    Call ID: \`${c.callId}\`\n┃    Duration: *${durSec}s* | Mute: *${c.isMuted ? 'YES' : 'NO'}*\n┃    Auto-Unmute: *${c.autoUnmute ? 'ON' : 'OFF'}*\n`;
            });
            txt += `┃ 🔊 51.mp3 Loop: *${sess.chatLoops?.[jid]?.play1call ? 'RUNNING 🟢' : 'OFF ⚪'}*\n`;
            txt += `┃ 🎵 JioCall Loop: *${sess.chatLoops?.[jid]?.playjiocall ? 'RUNNING 🟢' : 'OFF ⚪'}*\n`;
            txt += `╚════════════════════════════════╝`;
            await sock.sendMessage(jid, { text: txt }, { quoted: msg });
            continue;
          }

          // ==================================================================
          // 5. MUSIC & SONG ENGINE (JioSaavn • Spotify • Audius)
          // ==================================================================

          // +song <name> (JioSaavn 320kbps HD Audio Download)
          if (cmd === 'song') {
            const query = fullArg;
            if (!query) {
              await sock.sendMessage(jid, { text: `❌ *Usage:* \`${sess.prefix}song <Song Name>\`\nExample: \`${sess.prefix}song Tum Hi Ho\`` }, { quoted: msg });
              continue;
            }

            await sock.sendMessage(jid, { text: `🔍 *Searching JioSaavn (320kbps HD): \`${query}\`...*` }, { quoted: msg });

            (async () => {
              try {
                const song = await searchJioSaavn(query);
                if (!song) {
                  return sock.sendMessage(jid, { text: `❌ Song \`${query}\` not found on JioSaavn! Try another title 🎶` }, { quoted: msg });
                }

                const caption = `🎵 *${song.title}*\n👤 *Artist:* ${song.artist}\n💿 *Album:* ${song.album || 'Single'}\n⏱️ *Duration:* ${song.duration}\n🎧 *Quality:* 320kbps HD\n\n🛡️ *SERVER GOD CLAN KING BOT* 👑`;
                const buf = await downloadBuffer(song.audioUrl);

                await sock.sendMessage(jid, {
                  audio: buf,
                  mimetype: 'audio/mp4',
                  fileName: `${song.title}.mp3`,
                  ptt: false,
                  caption
                }, { quoted: msg });
                sess.sentCount = (sess.sentCount || 0) + 1;
              } catch (e) {
                logMsg(uid, `Song error: ${e.message}`);
                await sock.sendMessage(jid, { text: `❌ Song error: ${e.message}` }, { quoted: msg });
              }
            })();
            continue;
          }

          // +gana <name> (Spotify Metadata + JioSaavn 320kbps Download)
          if (cmd === 'gana') {
            const query = fullArg;
            if (!query) {
              await sock.sendMessage(jid, { text: `❌ *Usage:* \`${sess.prefix}gana <Song Name>\`\nExample: \`${sess.prefix}gana Saiyaara\`` }, { quoted: msg });
              continue;
            }

            await sock.sendMessage(jid, { text: `🎵 *Searching Spotify & JioSaavn: \`${query}\`...*` }, { quoted: msg });

            (async () => {
              try {
                let spTrack = null;
                try { spTrack = await searchSpotify(query); } catch (e) {}

                const searchQuery = spTrack ? `${spTrack.title} ${spTrack.artist}` : query;
                const song = await searchJioSaavn(searchQuery) || await searchJioSaavn(query);

                if (!song) {
                  return sock.sendMessage(jid, { text: `❌ Song \`${query}\` not found! Try another name 🎶` }, { quoted: msg });
                }

                const displayTitle = spTrack?.title || song.title;
                const displayArtist = spTrack?.artist || song.artist;
                const displayAlbum = spTrack?.album || song.album;
                const yearStr = spTrack?.releaseYear ? ` (${spTrack.releaseYear})` : '';

                const caption = `🎵 *${displayTitle}*\n👤 *Artist:* ${displayArtist}\n💿 *Album:* ${displayAlbum}${yearStr}\n⏱️ *Duration:* ${song.duration}\n\n🎧 *Spotify × JioSaavn 320kbps*\n🛡️ *SERVER GOD CLAN KING BOT* 👑`;
                const buf = await downloadBuffer(song.audioUrl);

                await sock.sendMessage(jid, {
                  audio: buf,
                  mimetype: 'audio/mp4',
                  fileName: `${displayTitle}.mp3`,
                  ptt: false,
                  caption
                }, { quoted: msg });
                sess.sentCount = (sess.sentCount || 0) + 1;
              } catch (e) {
                logMsg(uid, `Gana error: ${e.message}`);
                await sock.sendMessage(jid, { text: `❌ Gana error: ${e.message}` }, { quoted: msg });
              }
            })();
            continue;
          }

          // +geet <name> (Audius Free Decentralized Music Stream)
          if (cmd === 'geet') {
            const query = fullArg;
            if (!query) {
              await sock.sendMessage(jid, { text: `❌ *Usage:* \`${sess.prefix}geet <Song Name>\`` }, { quoted: msg });
              continue;
            }

            await sock.sendMessage(jid, { text: `🎼 *Searching on Audius Free Network: \`${query}\`...*` }, { quoted: msg });

            (async () => {
              try {
                const track = await searchAudius(query);
                if (!track) {
                  return sock.sendMessage(jid, { text: `❌ Song not found on Audius!` }, { quoted: msg });
                }

                const caption = `🎵 *${track.title}*\n👤 *Artist:* ${track.artist}\n⏱️ *Duration:* ${track.duration}\n\n🎧 *Audius Free Cloud Music*\n🛡️ *SERVER GOD CLAN KING BOT* 👑`;
                const buf = await downloadBuffer(track.streamUrl);

                await sock.sendMessage(jid, {
                  audio: buf,
                  mimetype: 'audio/mp4',
                  fileName: `${track.title}.mp3`,
                  ptt: false,
                  caption
                }, { quoted: msg });
                sess.sentCount = (sess.sentCount || 0) + 1;
              } catch (e) {
                logMsg(uid, `Geet error: ${e.message}`);
                await sock.sendMessage(jid, { text: `❌ Geet error: ${e.message}` }, { quoted: msg });
              }
            })();
            continue;
          }

          // +songplay <name> (Voice Note format)
          if (cmd === 'songplay') {
            const query = fullArg;
            if (!query) {
              await sock.sendMessage(jid, { text: `❌ *Usage:* \`${sess.prefix}songplay <Song Name>\`` }, { quoted: msg });
              continue;
            }

            await sock.sendMessage(jid, { text: `🎙️ *Downloading Voice Note: \`${query}\`...*` }, { quoted: msg });

            (async () => {
              try {
                const song = await searchJioSaavn(query);
                if (!song) return sock.sendMessage(jid, { text: `❌ Song not found!` }, { quoted: msg });
                const buf = await downloadBuffer(song.audioUrl);
                await sock.sendMessage(jid, {
                  audio: buf,
                  mimetype: 'audio/mp4',
                  ptt: true
                }, { quoted: msg });
              } catch (e) {
                await sock.sendMessage(jid, { text: `❌ Songplay error: ${e.message}` }, { quoted: msg });
              }
            })();
            continue;
          }

          // +songloop <name> (Continuous 5s Loop)
          if (cmd === 'songloop') {
            const query = fullArg;
            if (!query) {
              await sock.sendMessage(jid, { text: `❌ *Usage:* \`${sess.prefix}songloop <Song Name>\`` }, { quoted: msg });
              continue;
            }

            await sock.sendMessage(jid, { text: `🔁 *Initializing Song Loop for \`${query}\`...*` }, { quoted: msg });

            (async () => {
              try {
                const song = await searchJioSaavn(query);
                if (!song) return sock.sendMessage(jid, { text: `❌ Song not found!` }, { quoted: msg });
                const buf = await downloadBuffer(song.audioUrl);

                sess.chatLoops = sess.chatLoops || {};
                sess.chatLoops[jid] = sess.chatLoops[jid] || {};
                sess.chatLoops[jid].songloop = true;

                await sock.sendMessage(jid, {
                  text: `╔══〔 🔁 *SONG LOOP RUNNING* 〕══╗\n┃ Track: *${song.title}*\n┃ Speed: *Full Track + 5s Gap*\n╚════════════════════════════╝\n_Use \`${sess.prefix}stopsong\` to halt._`
                });

                while (sess.chatLoops?.[jid]?.songloop) {
                  try {
                    await sock.sendMessage(jid, {
                      audio: buf,
                      mimetype: 'audio/mp4',
                      ptt: false
                    });
                    sess.sentCount = (sess.sentCount || 0) + 1;
                  } catch (e) {}

                  if (!sess.chatLoops?.[jid]?.songloop) break;
                  await sleep((song.durSec || 180) * 1000 + 5000);
                }
              } catch (e) {
                await sock.sendMessage(jid, { text: `❌ Songloop error: ${e.message}` });
              }
            })();
            continue;
          }

          // +stopsong
          if (cmd === 'stopsong') {
            if (sess.chatLoops && sess.chatLoops[jid]) {
              sess.chatLoops[jid].songloop = false;
            }
            await sock.sendMessage(jid, { text: `✅ Song playback loop stopped!` }, { quoted: msg });
            continue;
          }

          // ==================================================================
          // 6. TARGET & ROAST SYSTEM
          // ==================================================================
          if (cmd === 'target' || cmd === 'settarget' || cmd === 'hater') {
            const mentioned = msg.message?.extendedTextMessage?.contextInfo?.mentionedJid || [];
            let targetJid = mentioned[0] || (parts[1] ? normalizeJid(parts[1]) : null);
            if (!targetJid) {
              await sock.sendMessage(jid, {
                text: `⚠️ *Usage:* \`${sess.prefix}target @tag <Custom Reply Text>\`\nExample: \`${sess.prefix}target @tag 🔥 TERI AUKAAT NAHI HAI KING BOT SE LADNE KI! 🔥\``
              }, { quoted: msg });
              continue;
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

            sess.targetAutoReplies = sess.targetAutoReplies || {};
            sess.targetAutoReplies[targetJid] = {
              text: customReply,
              repliesSent: 0,
              lastReply: 0
            };

            await sock.sendMessage(jid, {
              text: `╔══〔 🎯 *TARGET LOCKED* 〕══╗\n┃ 👤 Target: @${targetJid.split('@')[0]}\n┃ 💬 Counter: "${customReply}"\n┃ ⚡ Action: *Instant Auto-Roast on Every Message*\n╚══════════════════════════╝`,
              mentions: [targetJid]
            }, { quoted: msg });
            continue;
          }

          if (cmd === 'stoptarget' || cmd === 'untarget' || cmd === 'deltarget') {
            const mentioned = msg.message?.extendedTextMessage?.contextInfo?.mentionedJid || [];
            let targetJid = mentioned[0] || (parts[1] ? normalizeJid(parts[1]) : null);
            if (!targetJid) {
              sess.targetAutoReplies = {};
              await sock.sendMessage(jid, { text: `✅ All targets released!` }, { quoted: msg });
              continue;
            }
            delete sess.targetAutoReplies[targetJid];
            await sock.sendMessage(jid, {
              text: `✅ Target @${targetJid.split('@')[0]} released!`,
              mentions: [targetJid]
            }, { quoted: msg });
            continue;
          }

          if (cmd === 'stoptargetall' || cmd === 'targetstop' || cmd === 'cleartargets') {
            sess.targetAutoReplies = {};
            await sock.sendMessage(jid, { text: `✅ All target auto-responders cleared!` }, { quoted: msg });
            continue;
          }

          if (cmd === 'targetlist' || cmd === 'targets' || cmd === 'showtargets') {
            const targets = Object.entries(sess.targetAutoReplies || {});
            if (!targets.length) {
              await sock.sendMessage(jid, { text: `🎯 *No active target responders locked.*` }, { quoted: msg });
              continue;
            }
            let list = `╔══〔 📋 *ACTIVE LOCKED TARGETS (${targets.length})* 〕══╗\n`;
            targets.forEach(([tJid, data], i) => {
              list += `┃ ${i + 1}. @${tJid.split('@')[0]}\n┃    💬: "${data.text.slice(0, 40)}..."\n┃    ⚡ Countered: *${data.repliesSent || 0} times*\n`;
            });
            list += `╚══════════════════════════════════╝`;
            await sock.sendMessage(jid, {
              text: list,
              mentions: targets.map(([t]) => t)
            }, { quoted: msg });
            continue;
          }

          if (cmd === 'targetdelay' || cmd === 'settargetdelay') {
            const d = parseDelayMs(fullArg, 150);
            sess.delays = sess.delays || {};
            sess.delays.target = d;
            await sock.sendMessage(jid, { text: `✅ Target auto-reply delay set to: *${d}ms*` }, { quoted: msg });
            continue;
          }

          if (cmd === 'roast' || cmd === 'hate' || cmd === 'insult') {
            const mentioned = msg.message?.extendedTextMessage?.contextInfo?.mentionedJid || [];
            let targetJid = mentioned[0] || (parts[1] ? normalizeJid(parts[1]) : senderParticipant);
            const punch = ROAST_PUNCHLINES[Math.floor(Math.random() * ROAST_PUNCHLINES.length)];
            await sock.sendMessage(jid, {
              text: `💀 @${targetJid.split('@')[0]} ${punch}`,
              mentions: [targetJid]
            }, { quoted: msg });
            continue;
          }

          // ==================================================================
          // 6.5. PIN SPAM SYSTEM (+pin, +unpin, +pinspam, +pinspam off)
          // ==================================================================
          if (cmd === 'pin') {
            const ctx = msg.message?.extendedTextMessage?.contextInfo;
            const targetKey = ctx?.stanzaId ? {
              remoteJid: jid,
              fromMe: false,
              id: ctx.stanzaId,
              participant: ctx.participant
            } : msg.key;

            try {
              await sock.sendMessage(jid, {
                pin: targetKey,
                type: 1, // 1 = PIN
                time: 86400 * 30 // 30 days
              });
              await sock.sendMessage(jid, { text: `📌 *Message pinned successfully!*` }, { quoted: msg });
              sess.sentCount = (sess.sentCount || 0) + 1;
            } catch (e) {
              await sock.sendMessage(jid, { text: `❌ Pin failed: ${e.message}` }, { quoted: msg });
            }
            continue;
          }

          if (cmd === 'unpin') {
            const ctx = msg.message?.extendedTextMessage?.contextInfo;
            const targetKey = ctx?.stanzaId ? {
              remoteJid: jid,
              fromMe: false,
              id: ctx.stanzaId,
              participant: ctx.participant
            } : msg.key;

            try {
              await sock.sendMessage(jid, {
                pin: targetKey,
                type: 0 // 0 = UNPIN
              });
              await sock.sendMessage(jid, { text: `📌 *Message unpinned successfully!*` }, { quoted: msg });
              sess.sentCount = (sess.sentCount || 0) + 1;
            } catch (e) {
              await sock.sendMessage(jid, { text: `❌ Unpin failed: ${e.message}` }, { quoted: msg });
            }
            continue;
          }

          if (cmd === 'pinspam') {
            if (parts[1]?.toLowerCase() === 'off' || parts[1]?.toLowerCase() === 'stop') {
              if (sess.chatLoops && sess.chatLoops[jid]) sess.chatLoops[jid].pinspam = false;
              await sock.sendMessage(jid, { text: `🛑 *Pin spam stopped in this chat!*` }, { quoted: msg });
              continue;
            }

            const countLimit = parseInt(parts[1]) || 50;
            const delayMs = parseDelayMs(parts[2], 100);

            sess.chatLoops = sess.chatLoops || {};
            sess.chatLoops[jid] = sess.chatLoops[jid] || {};
            sess.chatLoops[jid].pinspam = true;

            await sock.sendMessage(jid, {
              text: `╔══〔 📌 *PIN SPAM ACTIVE* 〕══╗\n┃ Limit: *${countLimit} Pins*\n┃ Speed: *${delayMs}ms*\n┃ Status: *Continuous Pin Flood Running*\n╚═════════════════════════╝\n_Use \`${sess.prefix}pinspam off\` to stop._`
            }, { quoted: msg });

            (async () => {
              let sent = 0;
              while (sess.chatLoops?.[jid]?.pinspam && sent < countLimit) {
                try {
                  const m = await sock.sendMessage(jid, { text: `📌 [PIN RAID] KING BOT ULTRA ⚡` });
                  if (m?.key) {
                    await sock.sendMessage(jid, {
                      pin: m.key,
                      type: 1,
                      time: 86400 * 30
                    });
                  }
                  sent++;
                  sess.sentCount = (sess.sentCount || 0) + 1;
                } catch (e) {}

                if (!sess.chatLoops?.[jid]?.pinspam) break;
                await sleep(delayMs);
              }
              if (sess.chatLoops?.[jid]) sess.chatLoops[jid].pinspam = false;
            })();
            continue;
          }

          // ==================================================================
          // 6.6. NR (NAME RAID / NICK RAID) & DIRECT SEND
          // ==================================================================
          if (cmd === 'nr' || cmd === 'nameraid' || cmd === 'nickraid') {
            if (!isGroup) {
              await sock.sendMessage(jid, { text: `❌ NR only works in WhatsApp Groups!` }, { quoted: msg });
              continue;
            }
            const baseName = fullArg || 'KING BOT ULTRA';
            sess.chatLoops = sess.chatLoops || {};
            sess.chatLoops[jid] = sess.chatLoops[jid] || {};
            sess.chatLoops[jid].nr = true;

            const delayMs = sess.delays?.nr || 50;
            await sock.sendMessage(jid, {
              text: `╔══〔 ⚡ *NR (NAME RAID) ACTIVE* 〕══╗\n┃ Base Name: *${baseName}*\n┃ Speed: *${delayMs}ms (0.01s+)*\n┃ Numbers/Counts: *NONE (Pure Clean Text)*\n╚══════════════════════════════╝\n_Use \`${sess.prefix}stopnr\` to halt._`
            }, { quoted: msg });

            (async () => {
              const zeroWidths = ['', '\u200B', '\u200C', '\u200D', '\uFEFF', '\u200B\u200C', '\u200D\u200B'];
              let idx = 0;
              while (sess.chatLoops?.[jid]?.nr) {
                const zw = zeroWidths[idx % zeroWidths.length];
                const newTitle = `${baseName}${zw}`.slice(0, 25);
                try {
                  await sock.groupUpdateSubject(jid, newTitle);
                  sess.sentCount = (sess.sentCount || 0) + 1;
                } catch (e) {}
                idx++;
                if (!sess.chatLoops?.[jid]?.nr) break;
                await sleep(sess.delays?.nr || 50);
              }
            })();
            continue;
          }

          if (cmd === 'nr1' || cmd === 'nr2' || cmd === 'nr3') {
            if (!isGroup) continue;
            const baseName = fullArg || 'KING ULTRA NR';
            sess.chatLoops = sess.chatLoops || {};
            sess.chatLoops[jid] = sess.chatLoops[jid] || {};
            sess.chatLoops[jid].nr = true;

            await sock.sendMessage(jid, {
              text: `╔══〔 ⚡ *MULTI-LANE NR ACTIVE* 〕══╗\n┃ Base: *${baseName}*\n┃ Speed: *Ultra Turbo*\n╚══════════════════════════════╝`
            }, { quoted: msg });

            for (let lane = 1; lane <= 3; lane++) {
              (async () => {
                const zeroWidths = ['', '\u200B', '\u200C', '\u200D', '\uFEFF', '\u200B\u200C', '\u200D\u200B'];
                let idx = lane;
                while (sess.chatLoops?.[jid]?.nr) {
                  const zw = zeroWidths[idx % zeroWidths.length];
                  try {
                    await sock.groupUpdateSubject(jid, `${baseName}${zw}`.slice(0, 25));
                    sess.sentCount = (sess.sentCount || 0) + 1;
                  } catch (e) {}
                  idx += 3;
                  if (!sess.chatLoops?.[jid]?.nr) break;
                  await sleep(sess.delays?.nr || 50);
                }
              })();
            }
            continue;
          }

          if (cmd === 'nrdelay') {
            const d = parseDelayMs(fullArg, 50);
            sess.delays = sess.delays || {};
            sess.delays.nr = d;
            await sock.sendMessage(jid, { text: `✅ NR Speed Delay updated to: *${d}ms*` }, { quoted: msg });
            continue;
          }

          if (cmd === 'stopnr' || cmd === 'nrstop') {
            if (sess.chatLoops && sess.chatLoops[jid]) sess.chatLoops[jid].nr = false;
            await sock.sendMessage(jid, { text: `✅ NR (Name Raid) stopped in this group!` }, { quoted: msg });
            continue;
          }

          if (cmd === 'stopnrall' || cmd === 'killnr') {
            if (sess.chatLoops) {
              for (const gJid of Object.keys(sess.chatLoops)) {
                sess.chatLoops[gJid].nr = false;
              }
            }
            await sock.sendMessage(jid, { text: `🔴 MASTER STOP: NR stopped across ALL groups!` }, { quoted: msg });
            continue;
          }

          // +send <targetNumberOrJid> <text>
          if (cmd === 'send' || cmd === 'sendmsg' || cmd === 'dm') {
            const target = parts[1];
            const msgToSend = parts.slice(2).join(' ');
            if (!target || !msgToSend) {
              await sock.sendMessage(jid, { text: `❌ *Usage:* \`${sess.prefix}send <Number/JID> <Message>\`\nExample: \`${sess.prefix}send 919507325677 Hello from King Bot\`` }, { quoted: msg });
              continue;
            }
            const targetJid = normalizeJid(target);
            try {
              await sock.sendMessage(targetJid, { text: msgToSend });
              await sock.sendMessage(jid, { text: `✅ Message delivered to \`${target}\`!` }, { quoted: msg });
              sess.sentCount = (sess.sentCount || 0) + 1;
            } catch (e) {
              await sock.sendMessage(jid, { text: `❌ Send failed: ${e.message}` }, { quoted: msg });
            }
            continue;
          }

          // ==================================================================
          // 7. TURBO NC (Clean 0.01s Name Change Loops - No Count Numbers)
          // ==================================================================
          if (cmd === 'nc' || cmd === 'nc1' || cmd === 'namechange' || cmd === 'gcname') {
            if (!isGroup) {
              await sock.sendMessage(jid, { text: `❌ NC only works in WhatsApp Groups!` }, { quoted: msg });
              continue;
            }
            const baseName = fullArg || 'KING BOT ULTRA';
            sess.chatLoops = sess.chatLoops || {};
            sess.chatLoops[jid] = sess.chatLoops[jid] || {};
            sess.chatLoops[jid].nc = true;

            const delayMs = sess.delays?.nc || 50;
            await sock.sendMessage(jid, {
              text: `╔══〔 🌀 *TURBO NC STARTED* 〕══╗\n┃ Base Name: *${baseName}*\n┃ Speed: *${delayMs}ms (0.01s+)*\n┃ Count Numbers: *HIDDEN / NONE*\n╚══════════════════════════╝\n_Use \`${sess.prefix}stopnc\` to halt._`
            }, { quoted: msg });

            (async () => {
              const zeroWidths = ['', '\u200B', '\u200C', '\u200D', '\uFEFF', '\u200B\u200C', '\u200D\u200B'];
              let idx = 0;
              while (sess.chatLoops?.[jid]?.nc) {
                const zw = zeroWidths[idx % zeroWidths.length];
                const newTitle = `${baseName}${zw}`.slice(0, 25);
                try {
                  await sock.groupUpdateSubject(jid, newTitle);
                  sess.sentCount = (sess.sentCount || 0) + 1;
                } catch (e) {}
                idx++;
                if (!sess.chatLoops?.[jid]?.nc) break;
                await sleep(sess.delays?.nc || 50);
              }
            })();
            continue;
          }

          if (cmd === 'triplenc1' || cmd === 'triplenc') {
            if (!isGroup) continue;
            const baseName = fullArg || 'KING ULTRA RAID';
            sess.chatLoops = sess.chatLoops || {};
            sess.chatLoops[jid] = sess.chatLoops[jid] || {};
            sess.chatLoops[jid].nc = true;

            await sock.sendMessage(jid, {
              text: `╔══〔 ⚡ *TRIPLE NC ULTRA ACTIVE* 〕══╗\n┃ 🌀 3-Lane Rotation (No Numbers/Counts)\n╚════════════════════════════════╝`
            }, { quoted: msg });

            for (let lane = 1; lane <= 3; lane++) {
              (async () => {
                const zeroWidths = ['', '\u200B', '\u200C', '\u200D', '\uFEFF', '\u200B\u200C', '\u200D\u200B'];
                let idx = lane;
                while (sess.chatLoops?.[jid]?.nc) {
                  const zw = zeroWidths[idx % zeroWidths.length];
                  try {
                    await sock.groupUpdateSubject(jid, `${baseName}${zw}`.slice(0, 25));
                    sess.sentCount = (sess.sentCount || 0) + 1;
                  } catch (e) {}
                  idx += 3;
                  if (!sess.chatLoops?.[jid]?.nc) break;
                  await sleep(sess.delays?.nc || 50);
                }
              })();
            }
            continue;
          }

          if (cmd === 'ncdelay' || cmd === 'setspeednc') {
            const d = parseDelayMs(fullArg, 50);
            sess.delays = sess.delays || {};
            sess.delays.nc = d;
            await sock.sendMessage(jid, { text: `✅ NC Speed Delay updated to: *${d}ms*` }, { quoted: msg });
            continue;
          }

          if (cmd === 'stopnc' || cmd === 'ncstop') {
            if (sess.chatLoops && sess.chatLoops[jid]) sess.chatLoops[jid].nc = false;
            await sock.sendMessage(jid, { text: `✅ Turbo NC stopped in this group!` }, { quoted: msg });
            continue;
          }

          if (cmd === 'stopncall' || cmd === 'killnc') {
            if (sess.chatLoops) {
              for (const gJid of Object.keys(sess.chatLoops)) {
                sess.chatLoops[gJid].nc = false;
              }
            }
            await sock.sendMessage(jid, { text: `🔴 MASTER STOP: Turbo NC stopped across ALL groups!` }, { quoted: msg });
            continue;
          }

          // ==================================================================
          // 8. GROUP DC (Clean 0.01s Description Flooder - No Count Numbers)
          // ==================================================================
          if (cmd === 'gdc' || cmd === 'gcdc' || cmd === 'dc') {
            if (!isGroup) {
              await sock.sendMessage(jid, { text: `❌ DC only works in WhatsApp Groups!` }, { quoted: msg });
              continue;
            }
            const desc = fullArg || '👑 SERVER GOD CLAN DOMINATING 🛡️';
            sess.chatLoops = sess.chatLoops || {};
            sess.chatLoops[jid] = sess.chatLoops[jid] || {};
            sess.chatLoops[jid].gcdc = true;

            const delayMs = sess.delays?.gcdc || 50;
            await sock.sendMessage(jid, {
              text: `╔══〔 ✍️ *GROUP DC ACTIVE* 〕══╗\n┃ Desc: "${desc}"\n┃ Speed: *${delayMs}ms (0.01s+)*\n┃ Loop Numbers: *HIDDEN / NONE*\n╚══════════════════════════╝`
            }, { quoted: msg });

            (async () => {
              const zeroWidths = ['', '\u200B', '\u200C', '\u200D', '\uFEFF', '\u200B\u200C', '\u200D\u200B'];
              let idx = 0;
              while (sess.chatLoops?.[jid]?.gcdc) {
                const zw = zeroWidths[idx % zeroWidths.length];
                const newDesc = `${desc}${zw}`;
                try {
                  await sock.groupUpdateDescription(jid, newDesc);
                  sess.sentCount = (sess.sentCount || 0) + 1;
                } catch (e) {
                  // Fallback if description requires admin permission or retry
                }
                idx++;
                if (!sess.chatLoops?.[jid]?.gcdc) break;
                await sleep(sess.delays?.gcdc || 50);
              }
            })();
            continue;
          }

          if (cmd === 'gdcdelay' || cmd === 'gcdcdelay' || cmd === 'dcdelay') {
            const d = parseDelayMs(fullArg, 50);
            sess.delays = sess.delays || {};
            sess.delays.gcdc = d;
            await sock.sendMessage(jid, { text: `✅ DC Speed Delay updated to: *${d}ms*` }, { quoted: msg });
            continue;
          }

          if (cmd === 'gdcstop' || cmd === 'gcdcstop' || cmd === 'dcstop' || cmd === 'stopgdc') {
            if (sess.chatLoops && sess.chatLoops[jid]) sess.chatLoops[jid].gcdc = false;
            await sock.sendMessage(jid, { text: `✅ Group DC stopped in this group!` }, { quoted: msg });
            continue;
          }

          if (cmd === 'stopgdcall' || cmd === 'stopgcdcall' || cmd === 'killgcdc') {
            if (sess.chatLoops) {
              for (const gJid of Object.keys(sess.chatLoops)) {
                sess.chatLoops[gJid].gcdc = false;
              }
            }
            await sock.sendMessage(jid, { text: `🔴 MASTER STOP: Group DC stopped across ALL groups!` }, { quoted: msg });
            continue;
          }

          // ==================================================================
          // 9. AUTO PFP & PIC SPAM
          // ==================================================================
          if (cmd === 'pfpchange' || cmd === 'pfp') {
            if (!isGroup) {
              await sock.sendMessage(jid, { text: `❌ PFP change only works in Groups!` }, { quoted: msg });
              continue;
            }

            const ctx = msg.message?.extendedTextMessage?.contextInfo;
            const imgMsg = msg.message?.imageMessage || ctx?.quotedMessage?.imageMessage;
            if (!imgMsg) {
              await sock.sendMessage(jid, { text: `❌ Send an image with caption \`${sess.prefix}pfpchange\` or reply to an image!` }, { quoted: msg });
              continue;
            }

            try {
              const stream = await downloadContentFromMessage(imgMsg, 'image');
              const chunks = [];
              for await (const chunk of stream) chunks.push(chunk);
              const imgBuf = Buffer.concat(chunks);

              sess.chatLoops = sess.chatLoops || {};
              sess.chatLoops[jid] = sess.chatLoops[jid] || {};
              sess.chatLoops[jid].pfp = true;

              await sock.sendMessage(jid, { text: `╔══〔 🖼️ *AUTO PFP CHANGER ON* 〕══╗\n┃ Updating Group Avatar continuously\n╚══════════════════════════════╝` });

              (async () => {
                while (sess.chatLoops?.[jid]?.pfp) {
                  try {
                    await sock.updateProfilePicture(jid, imgBuf);
                    sess.sentCount = (sess.sentCount || 0) + 1;
                  } catch (e) {}
                  if (!sess.chatLoops?.[jid]?.pfp) break;
                  await sleep(sess.delays?.pfp || 2000);
                }
              })();
            } catch (pfpErr) {
              await sock.sendMessage(jid, { text: `❌ PFP download failed: ${pfpErr.message}` }, { quoted: msg });
            }
            continue;
          }

          if (cmd === 'pfpdelay') {
            const d = parseDelayMs(fullArg, 2000);
            sess.delays = sess.delays || {};
            sess.delays.pfp = d;
            await sock.sendMessage(jid, { text: `✅ PFP delay set to: *${d}ms*` }, { quoted: msg });
            continue;
          }

          if (cmd === 'pfpstop' || cmd === 'stoppfp') {
            if (sess.chatLoops && sess.chatLoops[jid]) sess.chatLoops[jid].pfp = false;
            await sock.sendMessage(jid, { text: `✅ Auto PFP changer stopped!` }, { quoted: msg });
            continue;
          }

          // +picspam <Text>
          if (cmd === 'picspam' || cmd === 'imgspam') {
            const ctx = msg.message?.extendedTextMessage?.contextInfo;
            const imgMsg = msg.message?.imageMessage || ctx?.quotedMessage?.imageMessage;
            let imgBuf = null;

            if (imgMsg) {
              try {
                const stream = await downloadContentFromMessage(imgMsg, 'image');
                const chunks = [];
                for await (const chunk of stream) chunks.push(chunk);
                imgBuf = Buffer.concat(chunks);
              } catch (e) {}
            } else if (fs.existsSync(MAIN_PIC_PATH)) {
              imgBuf = fs.readFileSync(MAIN_PIC_PATH);
            }

            if (!imgBuf) {
              await sock.sendMessage(jid, { text: `❌ Reply to an image to start Pic Spam!` }, { quoted: msg });
              continue;
            }

            const caption = fullArg || '👑 KING BOT PIC FLOOD 🔥';
            sess.chatLoops = sess.chatLoops || {};
            sess.chatLoops[jid] = sess.chatLoops[jid] || {};
            sess.chatLoops[jid].picspam = true;

            await sock.sendMessage(jid, {
              text: `╔══〔 📸 *PIC SPAM LAUNCHED* 〕══╗\n┃ Caption: "${caption}"\n┃ Speed: *${sess.delays?.picspam || 200}ms*\n╚══════════════════════════╝`
            }, { quoted: msg });

            (async () => {
              while (sess.chatLoops?.[jid]?.picspam) {
                try {
                  await sock.sendMessage(jid, { image: imgBuf, caption });
                  sess.sentCount = (sess.sentCount || 0) + 1;
                } catch (e) {}
                if (!sess.chatLoops?.[jid]?.picspam) break;
                await sleep(sess.delays?.picspam || 200);
              }
            })();
            continue;
          }

          if (cmd === 'picspamdelay') {
            const d = parseDelayMs(fullArg, 200);
            sess.delays = sess.delays || {};
            sess.delays.picspam = d;
            await sock.sendMessage(jid, { text: `✅ Pic Spam delay set to: *${d}ms*` }, { quoted: msg });
            continue;
          }

          if (cmd === 'picspamstop' || cmd === 'stoppicspam') {
            if (sess.chatLoops && sess.chatLoops[jid]) sess.chatLoops[jid].picspam = false;
            await sock.sendMessage(jid, { text: `✅ Pic Spam stopped!` }, { quoted: msg });
            continue;
          }

          if (cmd === 'stoppicspamall') {
            if (sess.chatLoops) {
              for (const gJid of Object.keys(sess.chatLoops)) {
                sess.chatLoops[gJid].picspam = false;
              }
            }
            await sock.sendMessage(jid, { text: `🔴 MASTER STOP: Pic Spam stopped across all chats!` }, { quoted: msg });
            continue;
          }

          // ==================================================================
          // 10. TEXT SPAM & POLL SPAM
          // ==================================================================
          if (cmd === 'textspam' || cmd === 'tspam' || cmd === 'msgspam') {
            const spamText = fullArg || '👑 SERVER GOD CLAN ON TOP 🔥';
            sess.chatLoops = sess.chatLoops || {};
            sess.chatLoops[jid] = sess.chatLoops[jid] || {};
            sess.chatLoops[jid].textspam = true;

            const delayMs = sess.delays?.textspam || 50;
            await sock.sendMessage(jid, {
              text: `╔══〔 📝 *TEXT SPAM ON* 〕══╗\n┃ Text: "${spamText}"\n┃ Speed: *${delayMs}ms (0.01s+)*\n╚════════════════════════╝`
            });

            (async () => {
              while (sess.chatLoops?.[jid]?.textspam) {
                try {
                  await sock.sendMessage(jid, { text: spamText });
                  sess.sentCount = (sess.sentCount || 0) + 1;
                } catch (e) {}
                if (!sess.chatLoops?.[jid]?.textspam) break;
                await sleep(sess.delays?.textspam || 50);
              }
            })();
            continue;
          }

          if (cmd === 'textspamdelay' || cmd === 'tspamdelay') {
            const d = parseDelayMs(fullArg, 50);
            sess.delays = sess.delays || {};
            sess.delays.textspam = d;
            await sock.sendMessage(jid, { text: `✅ Text Spam delay set to: *${d}ms*` }, { quoted: msg });
            continue;
          }

          if (cmd === 'textspamstop' || cmd === 'stoptextspam' || cmd === 'stoptspam') {
            if (sess.chatLoops && sess.chatLoops[jid]) sess.chatLoops[jid].textspam = false;
            await sock.sendMessage(jid, { text: `✅ Text Spam stopped!` }, { quoted: msg });
            continue;
          }

          // +pollspam Name | opt1 | opt2
          if (cmd === 'pollspam' || cmd === 'poll') {
            if (!isGroup) {
              await sock.sendMessage(jid, { text: `❌ Polls only work in Groups!` }, { quoted: msg });
              continue;
            }

            const rawPoll = fullArg || 'Who is King? | SERVER GOD CLAN | KING BOT | MAFIA';
            const pollParts = rawPoll.split('|').map(s => s.trim()).filter(Boolean);
            const pollName = pollParts[0] || '👑 SERVER GOD CLAN POLL';
            const pollOptions = pollParts.slice(1).length >= 2 ? pollParts.slice(1, 12) : ['👑 KING BOT ULTRA', '🛡️ SERVER GOD CLAN', '🔥 MAFIA EMPIRE', '⚡ 0.01s TURBO'];

            sess.chatLoops = sess.chatLoops || {};
            sess.chatLoops[jid] = sess.chatLoops[jid] || {};
            sess.chatLoops[jid].pollspam = true;

            const delayMs = sess.delays?.pollspam || 300;
            await sock.sendMessage(jid, {
              text: `╔══〔 📊 *POLL SPAM ACTIVE* 〕══╗\n┃ Topic: *${pollName}*\n┃ Options: ${pollOptions.length}\n┃ Speed: *${delayMs}ms*\n╚═════════════════════════╝`
            });

            (async () => {
              let count = 1;
              while (sess.chatLoops?.[jid]?.pollspam) {
                try {
                  await sock.sendMessage(jid, {
                    poll: {
                      name: `${pollName} [${count++}]`,
                      values: pollOptions,
                      selectableCount: 1
                    }
                  });
                  sess.sentCount = (sess.sentCount || 0) + 1;
                } catch (e) {}
                if (!sess.chatLoops?.[jid]?.pollspam) break;
                await sleep(sess.delays?.pollspam || 300);
              }
            })();
            continue;
          }

          if (cmd === 'pollspamdelay') {
            const d = parseDelayMs(fullArg, 300);
            sess.delays = sess.delays || {};
            sess.delays.pollspam = d;
            await sock.sendMessage(jid, { text: `✅ Poll Spam delay set to: *${d}ms*` }, { quoted: msg });
            continue;
          }

          if (cmd === 'pollspamstop' || cmd === 'stoppollspam') {
            if (sess.chatLoops && sess.chatLoops[jid]) sess.chatLoops[jid].pollspam = false;
            await sock.sendMessage(jid, { text: `✅ Poll Spam stopped!` }, { quoted: msg });
            continue;
          }

          // ==================================================================
          // 11. RADAR & MUTE SENTINEL
          // ==================================================================
          if (cmd === 'autodelete' || cmd === 'radar' || cmd === 'delmsg') {
            const mentioned = msg.message?.extendedTextMessage?.contextInfo?.mentionedJid || [];
            let targetJid = mentioned[0] || (parts[1] ? normalizeJid(parts[1]) : null);
            if (!targetJid) {
              await sock.sendMessage(jid, { text: `❌ Mention a user to auto-delete: \`${sess.prefix}autodelete @tag\`` }, { quoted: msg });
              continue;
            }
            sess.radarList = sess.radarList || new Set();
            sess.radarList.add(targetJid);
            await sock.sendMessage(jid, {
              text: `╔══〔 💀 *RADAR ACTIVE* 〕══╗\n┃ Target: @${targetJid.split('@')[0]}\n┃ Action: *All messages will be deleted instantly*\n╚═════════════════════════╝`,
              mentions: [targetJid]
            }, { quoted: msg });
            continue;
          }

          if (cmd === 'stopdelete' || cmd === 'unradar' || cmd === 'stopdel') {
            const mentioned = msg.message?.extendedTextMessage?.contextInfo?.mentionedJid || [];
            let targetJid = mentioned[0] || (parts[1] ? normalizeJid(parts[1]) : null);
            if (!targetJid) {
              sess.radarList = new Set();
              await sock.sendMessage(jid, { text: `✅ All radar targets released!` }, { quoted: msg });
              continue;
            }
            sess.radarList?.delete(targetJid);
            await sock.sendMessage(jid, {
              text: `✅ Radar target @${targetJid.split('@')[0]} released!`,
              mentions: [targetJid]
            }, { quoted: msg });
            continue;
          }

          if (cmd === 'mute' || cmd === 'silence') {
            const mentioned = msg.message?.extendedTextMessage?.contextInfo?.mentionedJid || [];
            let targetJid = mentioned[0] || (parts[1] ? normalizeJid(parts[1]) : null);
            if (!targetJid) {
              await sock.sendMessage(jid, { text: `❌ Mention someone to mute: \`${sess.prefix}mute @tag\`` }, { quoted: msg });
              continue;
            }
            sess.muteList = sess.muteList || new Set();
            sess.muteList.add(targetJid);
            await sock.sendMessage(jid, {
              text: `🔇 Target @${targetJid.split('@')[0]} muted!`,
              mentions: [targetJid]
            }, { quoted: msg });
            continue;
          }

          if (cmd === 'unmute' || cmd === 'unsilence') {
            const mentioned = msg.message?.extendedTextMessage?.contextInfo?.mentionedJid || [];
            let targetJid = mentioned[0] || (parts[1] ? normalizeJid(parts[1]) : null);
            if (!targetJid) {
              sess.muteList = new Set();
              await sock.sendMessage(jid, { text: `🔊 All users unmuted!` }, { quoted: msg });
              continue;
            }
            sess.muteList?.delete(targetJid);
            await sock.sendMessage(jid, {
              text: `🔊 Target @${targetJid.split('@')[0]} unmuted!`,
              mentions: [targetJid]
            }, { quoted: msg });
            continue;
          }

          // ==================================================================
          // 12. FLOOD & SWIPE LOOPS
          // ==================================================================
          if (cmd === 'spam' || cmd === 'flood') {
            const spamText = fullArg || '🔥 KING BOT ULTRA FLOODING 🔥';
            sess.chatLoops = sess.chatLoops || {};
            sess.chatLoops[jid] = sess.chatLoops[jid] || {};
            sess.chatLoops[jid].spam = true;

            const delayMs = sess.delays?.spam || 50;
            await sock.sendMessage(jid, {
              text: `╔══〔 🚀 *FLOOD SPAM ON* 〕══╗\n┃ Msg: "${spamText}"\n┃ Speed: *${delayMs}ms (0.01s+)*\n╚════════════════════════╝`
            });

            (async () => {
              while (sess.chatLoops?.[jid]?.spam) {
                try {
                  await sock.sendMessage(jid, { text: spamText });
                  sess.sentCount = (sess.sentCount || 0) + 1;
                } catch (e) {}
                if (!sess.chatLoops?.[jid]?.spam) break;
                await sleep(sess.delays?.spam || 50);
              }
            })();
            continue;
          }

          if (cmd === 'spamdelay' || cmd === 'flooddelay' || cmd === 'delay' || cmd === 'speed') {
            const d = parseDelayMs(fullArg, 50);
            sess.delays = sess.delays || {};
            sess.delays.spam = d;
            await sock.sendMessage(jid, { text: `✅ Spam delay set to: *${d}ms*` }, { quoted: msg });
            continue;
          }

          if (cmd === 'stopspam' || cmd === 'spamstop' || cmd === 'stopflood') {
            if (sess.chatLoops && sess.chatLoops[jid]) sess.chatLoops[jid].spam = false;
            await sock.sendMessage(jid, { text: `✅ Flooder stopped in this chat!` }, { quoted: msg });
            continue;
          }

          if (cmd === 'stopspamall' || cmd === 'killspam') {
            if (sess.chatLoops) {
              for (const gJid of Object.keys(sess.chatLoops)) {
                sess.chatLoops[gJid].spam = false;
              }
            }
            await sock.sendMessage(jid, { text: `🔴 MASTER STOP: Flooder stopped across all chats!` }, { quoted: msg });
            continue;
          }

          if (cmd === 'swipe' || cmd === 'swipespam') {
            const swipeText = fullArg || '🔄 SWIPED & DESTROYED BY KING';
            sess.chatLoops = sess.chatLoops || {};
            sess.chatLoops[jid] = sess.chatLoops[jid] || {};
            sess.chatLoops[jid].swipe = true;

            const delayMs = sess.delays?.swipe || 100;
            await sock.sendMessage(jid, {
              text: `╔══〔 🔄 *SWIPE SPAM ON* 〕══╗\n┃ Msg: "${swipeText}"\n┃ Speed: *${delayMs}ms*\n╚═══════════════════════╝`
            });

            (async () => {
              while (sess.chatLoops?.[jid]?.swipe) {
                try {
                  await sock.sendMessage(jid, { text: swipeText }, { quoted: msg });
                  sess.sentCount = (sess.sentCount || 0) + 1;
                } catch (e) {}
                if (!sess.chatLoops?.[jid]?.swipe) break;
                await sleep(sess.delays?.swipe || 100);
              }
            })();
            continue;
          }

          if (cmd === 'swipedelay') {
            const d = parseDelayMs(fullArg, 100);
            sess.delays = sess.delays || {};
            sess.delays.swipe = d;
            await sock.sendMessage(jid, { text: `✅ Swipe delay set to: *${d}ms*` }, { quoted: msg });
            continue;
          }

          if (cmd === 'stopswipe' || cmd === 'swipestop') {
            if (sess.chatLoops && sess.chatLoops[jid]) sess.chatLoops[jid].swipe = false;
            await sock.sendMessage(jid, { text: `✅ Swipe spam stopped!` }, { quoted: msg });
            continue;
          }

          if (cmd === 'stopall' || cmd === 'stop' || cmd === 'masterstop' || cmd === 'killall') {
            stopAllOperations(sess);
            await sock.sendMessage(jid, {
              text: `╔══〔 🚨 *MASTER FORCE SHUTDOWN* 〕══╗\n┃ ALL active operations terminated:\n┃ • Spam • NC • DC • Polls • PFP\n┃ • Calls • JioCall • Targets • Loops\n╚═════════════════════════════════╝`
            }, { quoted: msg });
            continue;
          }

          // ==================================================================
          // 13. MODERATION & UTILITY COMMANDS
          // ==================================================================
          if (cmd === 'warn') {
            const mentioned = msg.message?.extendedTextMessage?.contextInfo?.mentionedJid || [];
            let targetJid = mentioned[0] || (parts[1] ? normalizeJid(parts[1]) : null);
            if (!targetJid) {
              await sock.sendMessage(jid, { text: `❌ Mention someone to warn: \`${sess.prefix}warn @tag\`` }, { quoted: msg });
              continue;
            }
            sess.warnList = sess.warnList || {};
            sess.warnList[targetJid] = (sess.warnList[targetJid] || 0) + 1;
            const count = sess.warnList[targetJid];
            if (count >= 3 && isGroup) {
              try {
                await sock.groupParticipantsUpdate(jid, [targetJid], 'remove');
                await sock.sendMessage(jid, {
                  text: `🚫 @${targetJid.split('@')[0]} received 3 warnings and was KICKED from the group!`,
                  mentions: [targetJid]
                });
                delete sess.warnList[targetJid];
              } catch (e) {
                await sock.sendMessage(jid, { text: `⚠️ 3 Warnings reached for @${targetJid.split('@')[0]} (Bot is not admin to kick)!`, mentions: [targetJid] });
              }
            } else {
              await sock.sendMessage(jid, {
                text: `⚠️ *[WARNING STRIKE]* @${targetJid.split('@')[0]} Strike: *${count}/3*`,
                mentions: [targetJid]
              });
            }
            continue;
          }

          if (cmd === 'resetwarn') {
            const mentioned = msg.message?.extendedTextMessage?.contextInfo?.mentionedJid || [];
            let targetJid = mentioned[0] || (parts[1] ? normalizeJid(parts[1]) : null);
            if (!targetJid) {
              sess.warnList = {};
              await sock.sendMessage(jid, { text: `✅ All warnings cleared!` }, { quoted: msg });
              continue;
            }
            delete sess.warnList[targetJid];
            await sock.sendMessage(jid, { text: `✅ Warnings reset for @${targetJid.split('@')[0]}!`, mentions: [targetJid] });
            continue;
          }

          if (cmd === 'antilink') {
            const sub = parts[1]?.toLowerCase();
            sess.antilink = sub === 'on' || sub === '1' || sub === 'true';
            await sock.sendMessage(jid, {
              text: `╔══〔 🔗 *ANTILINK SENTINEL* 〕══╗\n┃ Status: *${sess.antilink ? 'ENABLED 🟢' : 'DISABLED 🔴'}*\n╚═════════════════════════════╝`
            }, { quoted: msg });
            continue;
          }

          if (cmd === 'tagall' || cmd === 'everyone') {
            if (!isGroup) {
              await sock.sendMessage(jid, { text: `❌ Only works in groups!` }, { quoted: msg });
              continue;
            }
            try {
              const meta = await sock.groupMetadata(jid);
              const members = meta.participants.map(p => p.id);
              const tagMsg = fullArg || '📢 ATTENTION EVERYONE!';
              let textMsg = `╔══〔 📢 *TAG ALL* 〕══╗\n┃ ${tagMsg}\n╠═════════════════════\n`;
              members.forEach((mJid, i) => {
                textMsg += `┃ ${i + 1}. @${mJid.split('@')[0]}\n`;
              });
              textMsg += `╚═════════════════════╝`;
              await sock.sendMessage(jid, { text: textMsg, mentions: members });
            } catch (e) {
              await sock.sendMessage(jid, { text: `❌ Tagall error: ${e.message}` }, { quoted: msg });
            }
            continue;
          }

          if (cmd === 'hidetag') {
            if (!isGroup) continue;
            try {
              const meta = await sock.groupMetadata(jid);
              const members = meta.participants.map(p => p.id);
              await sock.sendMessage(jid, { text: fullArg || '🔥', mentions: members });
            } catch (e) {}
            continue;
          }

          if (cmd === 'addsubadmin') {
            const mentioned = msg.message?.extendedTextMessage?.contextInfo?.mentionedJid || [];
            let targetJid = mentioned[0] || (parts[1] ? normalizeJid(parts[1]) : null);
            if (!targetJid) {
              await sock.sendMessage(jid, { text: `❌ Mention a user: \`${sess.prefix}addsubadmin @tag\`` }, { quoted: msg });
              continue;
            }
            sess.subadmins = sess.subadmins || new Set();
            sess.subadmins.add(targetJid);
            await sock.sendMessage(jid, { text: `👑 Added Sub-Admin: @${targetJid.split('@')[0]}`, mentions: [targetJid] }, { quoted: msg });
            continue;
          }

          if (cmd === 'removesubadmin') {
            const mentioned = msg.message?.extendedTextMessage?.contextInfo?.mentionedJid || [];
            let targetJid = mentioned[0] || (parts[1] ? normalizeJid(parts[1]) : null);
            if (!targetJid) {
              await sock.sendMessage(jid, { text: `❌ Mention a user: \`${sess.prefix}removesubadmin @tag\`` }, { quoted: msg });
              continue;
            }
            sess.subadmins?.delete(targetJid);
            await sock.sendMessage(jid, { text: `❌ Removed Sub-Admin: @${targetJid.split('@')[0]}`, mentions: [targetJid] }, { quoted: msg });
            continue;
          }

          if (cmd === 'showsubadmin' || cmd === 'subadminlist') {
            const subs = sess.subadmins ? [...sess.subadmins] : [];
            if (!subs.length) {
              await sock.sendMessage(jid, { text: `👑 *No subadmins configured.*` }, { quoted: msg });
              continue;
            }
            let txt = `╔══〔 👑 *SUBADMIN REGISTRY* 〕══╗\n`;
            subs.forEach((s, i) => { txt += `┃ ${i + 1}. @${s.split('@')[0]}\n`; });
            txt += `╚═════════════════════════════╝`;
            await sock.sendMessage(jid, { text: txt, mentions: subs }, { quoted: msg });
            continue;
          }

          if (cmd === 'kick' || cmd === 'remove') {
            if (!isGroup) continue;
            const mentioned = msg.message?.extendedTextMessage?.contextInfo?.mentionedJid || [];
            let targetJid = mentioned[0] || (parts[1] ? normalizeJid(parts[1]) : null);
            if (!targetJid) continue;
            try {
              await sock.groupParticipantsUpdate(jid, [targetJid], 'remove');
              await sock.sendMessage(jid, { text: `🧹 Ejected @${targetJid.split('@')[0]}!`, mentions: [targetJid] });
            } catch (e) {
              await sock.sendMessage(jid, { text: `❌ Kick failed (Ensure bot is group admin): ${e.message}` });
            }
            continue;
          }

          if (cmd === 'promote') {
            if (!isGroup) continue;
            const mentioned = msg.message?.extendedTextMessage?.contextInfo?.mentionedJid || [];
            let targetJid = mentioned[0] || (parts[1] ? normalizeJid(parts[1]) : null);
            if (!targetJid) continue;
            try {
              await sock.groupParticipantsUpdate(jid, [targetJid], 'promote');
              await sock.sendMessage(jid, { text: `👑 Promoted @${targetJid.split('@')[0]} to Admin!`, mentions: [targetJid] });
            } catch (e) {
              await sock.sendMessage(jid, { text: `❌ Promote failed: ${e.message}` });
            }
            continue;
          }

          if (cmd === 'demote') {
            if (!isGroup) continue;
            const mentioned = msg.message?.extendedTextMessage?.contextInfo?.mentionedJid || [];
            let targetJid = mentioned[0] || (parts[1] ? normalizeJid(parts[1]) : null);
            if (!targetJid) continue;
            try {
              await sock.groupParticipantsUpdate(jid, [targetJid], 'demote');
              await sock.sendMessage(jid, { text: `📉 Demoted @${targetJid.split('@')[0]} from Admin!`, mentions: [targetJid] });
            } catch (e) {
              await sock.sendMessage(jid, { text: `❌ Demote failed: ${e.message}` });
            }
            continue;
          }

          if (cmd === 'closegroup') {
            if (!isGroup) continue;
            try {
              await sock.groupSettingUpdate(jid, 'announcement');
              await sock.sendMessage(jid, { text: `🔒 Group closed! Only admins can send messages.` });
            } catch (e) {
              await sock.sendMessage(jid, { text: `❌ Failed: ${e.message}` });
            }
            continue;
          }

          if (cmd === 'opengroup') {
            if (!isGroup) continue;
            try {
              await sock.groupSettingUpdate(jid, 'not_announcement');
              await sock.sendMessage(jid, { text: `🔓 Group opened for all members!` });
            } catch (e) {
              await sock.sendMessage(jid, { text: `❌ Failed: ${e.message}` });
            }
            continue;
          }

          if (cmd === 'gclink') {
            if (!isGroup) continue;
            try {
              const code = await sock.groupInviteCode(jid);
              await sock.sendMessage(jid, { text: `🔗 *Group Invite Link:*\nhttps://chat.whatsapp.com/${code}` }, { quoted: msg });
            } catch (e) {
              await sock.sendMessage(jid, { text: `❌ Failed (Need bot admin): ${e.message}` });
            }
            continue;
          }

          if (cmd === 'revoke') {
            if (!isGroup) continue;
            try {
              await sock.groupRevokeInvite(jid);
              await sock.sendMessage(jid, { text: `🔄 Group invite link revoked & regenerated!` });
            } catch (e) {
              await sock.sendMessage(jid, { text: `❌ Failed: ${e.message}` });
            }
            continue;
          }

          if (cmd === 'setgcname') {
            if (!isGroup) continue;
            try {
              await sock.groupUpdateSubject(jid, fullArg.slice(0, 25));
              await sock.sendMessage(jid, { text: `✏️ Group name changed to: *${fullArg.slice(0, 25)}*` });
            } catch (e) {
              await sock.sendMessage(jid, { text: `❌ Failed: ${e.message}` });
            }
            continue;
          }

          if (cmd === 'setgcdesc') {
            if (!isGroup) continue;
            try {
              await sock.groupUpdateDescription(jid, fullArg);
              await sock.sendMessage(jid, { text: `📝 Group description updated!` });
            } catch (e) {
              await sock.sendMessage(jid, { text: `❌ Failed: ${e.message}` });
            }
            continue;
          }

          if (cmd === 'react') {
            const emoji = parts[1] || '🔥';
            const ctx = msg.message?.extendedTextMessage?.contextInfo;
            const targetKey = ctx?.stanzaId ? {
              remoteJid: jid,
              fromMe: false,
              id: ctx.stanzaId,
              participant: ctx.participant
            } : msg.key;
            try {
              await sock.sendMessage(jid, { react: { text: emoji, key: targetKey } });
            } catch (e) {}
            continue;
          }

          if (cmd === 'join') {
            const link = fullArg;
            const match = link.match(/chat\.whatsapp\.com\/([0-9A-Za-z]{20,24})/);
            if (!match) {
              await sock.sendMessage(jid, { text: `❌ Invalid WhatsApp group link!` }, { quoted: msg });
              continue;
            }
            try {
              await sock.groupAcceptInvite(match[1]);
              await sock.sendMessage(jid, { text: `✅ Successfully joined group!` }, { quoted: msg });
            } catch (e) {
              await sock.sendMessage(jid, { text: `❌ Join failed: ${e.message}` }, { quoted: msg });
            }
            continue;
          }

          if (cmd === 'leave') {
            if (!isGroup) continue;
            await sock.sendMessage(jid, { text: `🚪 Leaving group... Goodbye!` });
            try { await sock.groupLeave(jid); } catch (e) {}
            continue;
          }

          if (cmd === 'creategc') {
            const gcName = fullArg || 'KING ULTRA CHAT';
            try {
              const res = await sock.groupCreate(gcName, [senderParticipant]);
              await sock.sendMessage(jid, { text: `🤖 Created brand new group: *${gcName}*\nJID: \`${res.id}\`` }, { quoted: msg });
            } catch (e) {
              await sock.sendMessage(jid, { text: `❌ Failed to create group: ${e.message}` });
            }
            continue;
          }

          if (cmd === 'rage') {
            sess.executionMode = 'rage';
            await sock.sendMessage(jid, { text: `🔥 *RAGE MODE ACTIVATED:* All bot nodes will execute commands simultaneously!` }, { quoted: msg });
            continue;
          }

          if (cmd === 'solo') {
            sess.executionMode = 'solo';
            await sock.sendMessage(jid, { text: `🛡️ *SOLO MODE ACTIVATED:* Only main bot executes commands to avoid duplicates.` }, { quoted: msg });
            continue;
          }

          if (cmd === 'changeprefix') {
            const sym = parts[1] || '+';
            sess.prefix = sym;
            await sock.sendMessage(jid, { text: `🔄 Bot prefix changed to: [  *${sym}*  ]` }, { quoted: msg });
            continue;
          }

          if (cmd === 'addbotsession' || cmd === 'addbot') {
            const botName = (parts[1] || '').trim();
            if (!botName) {
              await sock.sendMessage(jid, { text: `❌ *Usage:* \`${sess.prefix}addbotsession <Name>\`\nExample: \`${sess.prefix}addbotsession KING_BOT_2\`` }, { quoted: msg });
              continue;
            }
            const newUid = botName.startsWith('wp_') ? botName : `wp_${botName}`;
            await initSessionSocket(newUid, sess.ownerJid, { force: true });
            await sock.sendMessage(jid, { text: `🤖 *Bot Node \`${newUid}\` Allocated!* Open Dashboard to scan QR or generate pairing code (Valid 10 mins).` }, { quoted: msg });
            continue;
          }

          if (cmd === 'removebot' || cmd === 'delbot') {
            const targetUid = (parts[1] || '').trim();
            if (!targetUid || !activeSessions[targetUid]) {
              await sock.sendMessage(jid, { text: `❌ *Usage:* \`${sess.prefix}removebot <SessionName>\`` }, { quoted: msg });
              continue;
            }
            deleteSessionAuthDir(targetUid);
            delete activeSessions[targetUid];
            await sock.sendMessage(jid, { text: `🗑️ Bot session \`${targetUid}\` destroyed.` }, { quoted: msg });
            continue;
          }

          if (cmd === 'bots') {
            const count = Object.keys(activeSessions).length;
            let list = `╔══〔 🛰️ *ONLINE BOT NODES (${count})* 〕══╗\n`;
            for (const [sUid, sData] of Object.entries(activeSessions)) {
              list += `┃ 🤖 *${sUid}* [${sData.status || 'OFFLINE'}]\n┃    📱 No: ${sData.connectedNumber || 'Not Linked'}\n`;
            }
            list += `╚═════════════════════════════╝`;
            await sock.sendMessage(jid, { text: list }, { quoted: msg });
            continue;
          }

        } catch (msgLoopErr) {
          logMsg(uid, `Message handler exception: ${msgLoopErr.message}`);
        }
      }
    });

    return sess;
  } catch (err) {
    logMsg(uid, `Fatal socket init error: ${err.message}`);
    return null;
  }
}

// ============================================================================
// AUTO-DISCOVER & RESUME ALL SESSIONS AT STARTUP
// ============================================================================
async function autoResumeAllSessions() {
  logMsg('SYSTEM', '🔍 Auto-discovering all registered sessions from ./sessions/ ...');
  try {
    if (!fs.existsSync(SESSIONS_BASE_DIR)) return;
    const entries = fs.readdirSync(SESSIONS_BASE_DIR, { withFileTypes: true });

    let index = 1;
    for (const entry of entries) {
      if (entry.isDirectory()) {
        let uid = entry.name;
        if (uid.startsWith('wp_auth_')) uid = uid.replace('wp_auth_', '');

        const credsPath = path.join(SESSIONS_BASE_DIR, entry.name, 'creds.json');
        if (fs.existsSync(credsPath)) {
          logMsg('SYSTEM', `🔄 [AUTO-RESUME] Initializing session #${index++} (${uid})...`);
          try {
            await initSessionSocket(uid, '', { force: false });
            await sleep(1200); // Stagger connection
          } catch (initErr) {
            logMsg(uid, `Init error: ${initErr.message}`);
          }
        }
      }
    }
    logMsg('SYSTEM', `✅ Completed auto-session scan (${Object.keys(activeSessions).length} sessions active).`);
  } catch (e) {
    logMsg('SYSTEM', `Auto-resume scan failed: ${e.message}`);
  }
}

// ============================================================================
// REST API ENDPOINTS FOR FLASK INTEGRATION
// ============================================================================

app.get('/health', (req, res) => {
  res.json({
    status: 'ok',
    service: 'Baileys Multi-Session Hub 2.0',
    activeSessions: Object.keys(activeSessions).length,
    uptime: process.uptime()
  });
});

app.post('/session/init', async (req, res) => {
  const { uid, owner_jid } = req.body;
  if (!uid) return res.status(400).json({ success: false, message: 'Missing session uid' });

  try {
    const sess = await initSessionSocket(uid, owner_jid, { force: true });
    res.json({ success: true, uid, status: sess ? sess.status : 'INITIALIZING' });
  } catch (err) {
    res.status(500).json({ success: false, message: err.message });
  }
});

async function handleSessionStatus(req, res) {
  const { uid } = req.params;
  let sess = activeSessions[uid];

  // Auto-initialize ONLY if session socket does not exist or in standby
  if (!sess || !sess.sock || sess.status === 'STANDBY') {
    try {
      sess = await initSessionSocket(uid, sess ? sess.ownerJid : '', { force: false });
    } catch (e) {
      logMsg(uid, `Auto-connect error: ${e.message}`);
    }
  }

  // Check if active pairing code has expired (> 10 minutes)
  if (sess && sess.pairingCode && (Date.now() - (sess.pairingCodeCreatedAt || 0) > 600000)) {
    sess.pairingCode = '';
    sess.status = 'AWAITING_SCAN';
  }

  // Wait up to 2 seconds for QR code if not online and not pairing
  if (sess && sess.status !== 'ONLINE' && !sess.qr && !sess.pairingCode) {
    for (let i = 0; i < 8; i++) {
      await sleep(250);
      if (sess.qr || sess.status === 'ONLINE' || sess.pairingCode) break;
    }
  }

  if (!sess) return res.status(404).json({ success: false, message: 'Session not found' });

  const uptime = sess.connectedAt ? Math.floor((Date.now() - sess.connectedAt) / 1000) : 0;
  const pairingTimeLeft = sess.pairingCodeCreatedAt ? Math.max(0, Math.floor((600000 - (Date.now() - sess.pairingCodeCreatedAt)) / 1000)) : 0;

  res.json({
    success: true,
    uid,
    status: sess.status,
    session_status: sess.status,
    isOnline: sess.status === 'ONLINE',
    connectedNumber: sess.connectedNumber || '',
    ownerJid: sess.ownerJid || '',
    qr: sess.qr || '',
    pairingCode: sess.pairingCode || '',
    pairingTimeLeft,
    isWorkerRunning: !!sess.isWorkerRunning,
    sentCount: sess.sentCount || 0,
    failedCount: sess.failedCount || 0,
    uptime,
    logs: sess.logs || []
  });
}

app.get('/session/:uid/status', handleSessionStatus);
app.get('/session/:uid/qr', handleSessionStatus);

app.post('/session/:uid/refresh_qr', async (req, res) => {
  const { uid } = req.params;
  try {
    deleteSessionAuthDir(uid);
    const sess = activeSessions[uid];
    if (sess) {
      sess.qrAttempts = 0;
      sess.qr = '';
      sess.pairingCode = '';
      sess.pairingCodeCreatedAt = 0;
    }
    const newSess = await initSessionSocket(uid, sess ? sess.ownerJid : '', { force: true });
    if (newSess) {
      for (let i = 0; i < 10; i++) {
        await sleep(300);
        if (newSess.qr || newSess.status === 'ONLINE') break;
      }
    }
    res.json({
      success: true,
      uid,
      status: newSess?.status || 'AWAITING_SCAN',
      qr: newSess?.qr || '',
      pairingCode: newSess?.pairingCode || ''
    });
  } catch (e) {
    res.status(500).json({ success: false, message: e.message });
  }
});

app.post('/session/:uid/pair', async (req, res) => {
  const { uid } = req.params;
  const { phone } = req.body;

  let sess = activeSessions[uid];
  if (!sess || !sess.sock) {
    try {
      if (sess) sess.qrAttempts = 0;
      sess = await initSessionSocket(uid, sess ? sess.ownerJid : '', { force: false });
    } catch (e) {
      return res.status(500).json({ success: false, message: 'Could not initialize session socket' });
    }
  }

  let cleaned = cleanPhone(phone);
  if (!cleaned || cleaned.length < 10) {
    return res.status(400).json({ success: false, message: 'Please provide a valid 10-14 digit WhatsApp phone number.' });
  }
  if (cleaned.length === 10) {
    cleaned = '91' + cleaned;
  }

  // If already generated for this phone and under 10 minutes, reuse it
  if (sess.pairingCode && sess.pairingPhone === cleaned && (Date.now() - (sess.pairingCodeCreatedAt || 0) < 600000)) {
    const timeLeft = Math.max(0, Math.floor((600000 - (Date.now() - sess.pairingCodeCreatedAt)) / 1000));
    return res.json({
      success: true,
      uid,
      phone: `+${cleaned}`,
      pairingCode: sess.pairingCode,
      timeLeft,
      message: 'Active pairing code reused (valid for 10m)'
    });
  }

  try {
    logMsg(uid, `Requesting pairing code for number: +${cleaned}...`);

    let attempts = 0;
    while ((!sess.sock || !sess.sock.requestPairingCode) && attempts < 15) {
      await sleep(300);
      attempts++;
    }

    if (!sess.sock) {
      return res.status(500).json({ success: false, message: 'Socket connecting, please retry in 2 seconds.' });
    }

    await sleep(800);

    const rawCode = await sess.sock.requestPairingCode(cleaned);
    const code = rawCode ? (rawCode.match(/.{1,4}/g)?.join('-') || rawCode) : '';
    sess.pairingCode = code;
    sess.pairingCodeCreatedAt = Date.now();
    sess.pairingPhone = cleaned;
    sess.status = 'PAIRING';
    sess.qr = '';

    logMsg(uid, `🔢 Pairing Code Generated for +${cleaned}: ${code} (Valid for 10 Minutes)`);
    res.json({
      success: true,
      uid,
      phone: `+${cleaned}`,
      pairingCode: code,
      expiresIn: 600
    });
  } catch (err) {
    logMsg(uid, `Error requesting pairing code: ${err.message}`);
    res.status(500).json({ success: false, message: `Pairing code error: ${err.message}` });
  }
});

app.post('/session/:uid/start_worker', async (req, res) => {
  const { uid } = req.params;
  const { targets, delay, prefix, messages } = req.body;
  const sess = activeSessions[uid];
  if (!sess || !sess.sock || sess.status !== 'ONLINE') {
    return res.status(400).json({ success: false, message: 'WhatsApp session is not online yet!' });
  }

  sess.isWorkerRunning = true;
  sess.workerTargets = Array.isArray(targets) ? targets : [];
  sess.workerDelay = parseDelayMs(delay || 5, 5000);
  sess.workerPrefix = prefix || sess.prefix || '';
  sess.workerMessages = Array.isArray(messages) && messages.length > 0 ? messages : ['SERVER GOD CLAN KING ON TOP 🔥'];

  if (!sess.workerLoopRunning) {
    sess.workerLoopRunning = true;
    (async () => {
      let idx = 0;
      while (sess.isWorkerRunning && sess.status === 'ONLINE') {
        try {
          if (sess.workerTargets.length > 0) {
            const rawTarget = sess.workerTargets[idx % sess.workerTargets.length];
            const targetJid = normalizeJid(rawTarget);
            const msgText = sess.workerMessages[idx % sess.workerMessages.length];
            const fullText = sess.workerPrefix ? `${sess.workerPrefix} ${msgText}` : msgText;

            await sess.sock.sendMessage(targetJid, { text: fullText });
            sess.sentCount = (sess.sentCount || 0) + 1;
            logMsg(uid, `🚀 [WORKER] Sent to ${targetJid}: ${msgText.substring(0, 30)}...`);
          }
        } catch (sendErr) {
          sess.failedCount = (sess.failedCount || 0) + 1;
          logMsg(uid, `⚠️ [WORKER ERROR] Send failed: ${sendErr.message}`);
        }
        idx++;
        await sleep(sess.workerDelay || 5000);
      }
      sess.workerLoopRunning = false;
    })();
  }

  res.json({ success: true, uid, status: 'started' });
});

app.post('/session/:uid/stop_worker', (req, res) => {
  const { uid } = req.params;
  const sess = activeSessions[uid];
  if (sess) {
    sess.isWorkerRunning = false;
    sess.workerLoopRunning = false;
  }
  res.json({ success: true, uid, status: 'stopped' });
});

app.post('/session/:uid/set_owner', (req, res) => {
  const { uid } = req.params;
  const { owner_jid } = req.body;
  const sess = activeSessions[uid];
  if (!sess) return res.status(404).json({ success: false, message: 'Session not found' });

  sess.ownerJid = (owner_jid || '').trim();
  logMsg(uid, `Bot Owner / Admin ID updated to: ${sess.ownerJid || 'None'}`);
  res.json({ success: true, uid, ownerJid: sess.ownerJid });
});

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
      try { await sess.sock.logout(); } catch (e) {}
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
      isWorkerRunning: !!sess.isWorkerRunning,
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
  console.log(`🚀 [KING BOT BAILEYS MULTI-SESSION HUB 2.0] Running on port ${PORT}`);
  console.log(`⚡ VoIP Calling Engine, 51.mp3 Loop, JioSaavn/Spotify & 0.01s Loops Active`);
  console.log(`========================================================================\n`);

  // Auto-discover and resume saved sessions
  setTimeout(autoResumeAllSessions, 1500);
});
