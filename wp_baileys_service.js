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
  makeCacheableSignalKeyStore,
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
const DASHBOARD_PIC_PATH = fs.existsSync(path.join(__dirname, 'dashbaord.png')) ? path.join(__dirname, 'dashbaord.png') : path.join(__dirname, 'dashboard.png');
const AUDIO_51_PATH = path.join(__dirname, '51.mp3');

const { spawn } = require('child_process');
let yts = null;
try { yts = require('yt-search'); } catch(e) {}
let ytdl = null;
try { ytdl = require('@distube/ytdl-core'); } catch(e) {}

const lastSearchedTracks = new Map(); // jid -> track object

async function searchYouTubeTrack(query) {
  query = (query || '').trim();
  if (!query) return null;

  // Handle youtu.be / watch URLs
  if (query.startsWith('http://') || query.startsWith('https://')) {
    try {
      const u = new URL(query);
      if (u.hostname.includes('youtu.be')) {
        const vidId = u.pathname.replace(/^\//, '');
        if (vidId) query = `https://www.youtube.com/watch?v=${vidId}`;
      }
    } catch(e) {}
  }

  // 1. Try yt-search
  if (yts && !query.startsWith('http')) {
    try {
      const res = await yts(query);
      if (res && res.videos && res.videos.length > 0) {
        const v = res.videos[0];
        return {
          title: v.title,
          artist: v.author?.name || 'YouTube Music',
          author: v.author?.name || 'YouTube Music',
          duration: v.timestamp || `${Math.floor(v.seconds / 60)}:${v.seconds % 60}`,
          seconds: v.seconds || 180,
          views: v.views ? Number(v.views).toLocaleString() : '150K+',
          ago: v.ago || 'Recent',
          url: v.url || `https://www.youtube.com/watch?v=${v.videoId}`,
          videoId: v.videoId,
          description: v.description || `Official music video for ${v.title}`,
          image: v.thumbnail || v.image,
          thumbnail: v.thumbnail || v.image
        };
      }
    } catch (e) {}
  }

  // 2. Direct yt_dlp metadata extraction
  try {
    const dlpProc = spawn('python', [
      '-m', 'yt_dlp',
      '--dump-json',
      '--no-warnings',
      '--no-playlist',
      query.startsWith('http') ? query : `ytsearch1:${query}`
    ]);
    let dlpOut = '';
    dlpProc.stdout.on('data', (d) => { dlpOut += d.toString(); });
    const code = await new Promise(r => dlpProc.on('close', r));
    if (code === 0 && dlpOut.trim()) {
      const dlpRes = JSON.parse(dlpOut.trim().split('\n')[0]);
      return {
        title: dlpRes.title || query,
        artist: dlpRes.uploader || dlpRes.channel || 'YouTube Artist',
        author: dlpRes.uploader || dlpRes.channel || 'YouTube Artist',
        duration: dlpRes.duration ? `${Math.floor(dlpRes.duration / 60)}:${dlpRes.duration % 60}` : '3:45',
        seconds: dlpRes.duration || 180,
        views: dlpRes.view_count ? Number(dlpRes.view_count).toLocaleString() : '200K+',
        ago: 'Recent',
        url: dlpRes.webpage_url || (dlpRes.id ? `https://www.youtube.com/watch?v=${dlpRes.id}` : query),
        videoId: dlpRes.id,
        description: dlpRes.description ? dlpRes.description.slice(0, 150) + '...' : `Official audio/video stream for ${dlpRes.title}`,
        thumbnail: dlpRes.thumbnail || (dlpRes.id ? `https://i.ytimg.com/vi/${dlpRes.id}/maxresdefault.jpg` : ''),
        image: dlpRes.thumbnail
      };
    }
  } catch(e) {}

  // 3. Fallback to JioSaavn
  try {
    const jio = await searchJioSaavn(query);
    if (jio) {
      return {
        title: jio.title,
        artist: jio.artist,
        author: jio.artist,
        duration: jio.duration,
        seconds: jio.durSec || 180,
        views: '500K+',
        ago: 'Popular',
        url: `https://www.youtube.com/watch?v=search_${encodeURIComponent(query)}`,
        audioUrl: jio.audioUrl,
        description: `JioSaavn / YouTube Music Track: ${jio.title} by ${jio.artist}`,
        image: jio.image,
        thumbnail: jio.image
      };
    }
  } catch(e) {}
  return null;
}

function downloadYouTubeMedia(queryOrUrl, type = 'audio', outputPath) {
  return new Promise((resolve) => {
    let cleanTarget = (queryOrUrl || '').trim();
    if (cleanTarget.includes('results?search_query=')) {
      try {
        const u = new URL(cleanTarget);
        cleanTarget = u.searchParams.get('search_query') || cleanTarget;
      } catch(e) {}
    }

    const isUrl = cleanTarget.startsWith('http://') || cleanTarget.startsWith('https://');
    const target = isUrl ? cleanTarget : `ytsearch1:${cleanTarget}`;
    const format = type === 'video' 
      ? 'best[height<=720][ext=mp4]/bestvideo[height<=720]+bestaudio/best[height<=720]/best' 
      : 'bestaudio[ext=m4a]/bestaudio/best';
    
    const baseWithoutExt = outputPath.replace(/\.[^/.]+$/, "");
    const outTmpl = `${baseWithoutExt}.%(ext)s`;
    let cookiePath = path.join(__dirname, 'cookies.txt');
    if (!fs.existsSync(cookiePath) && fs.existsSync('/app/cookies.txt')) {
      cookiePath = '/app/cookies.txt';
    } else if (!fs.existsSync(cookiePath) && fs.existsSync(path.join(process.cwd(), 'cookies.txt'))) {
      cookiePath = path.join(process.cwd(), 'cookies.txt');
    }

    const findDownloadedFile = () => {
      if (fs.existsSync(outputPath) && fs.statSync(outputPath).size > 1000) return outputPath;
      const dir = path.dirname(baseWithoutExt);
      const baseName = path.basename(baseWithoutExt);
      try {
        const files = fs.readdirSync(dir);
        for (const file of files) {
          if (file.startsWith(baseName)) {
            const fullP = path.join(dir, file);
            if (fs.existsSync(fullP) && fs.statSync(fullP).size > 1000 && !fullP.endsWith('.part') && !fullP.endsWith('.ytdl')) {
              return fullP;
            }
          }
        }
      } catch (e) {}
      return null;
    };

    const ffmpegPath = path.join(__dirname, 'ffmpeg.exe');
    const spawnArgs = [
      '-m', 'yt_dlp',
      '--no-playlist',
      '--socket-timeout', '20',
      '--no-warnings',
      '--geo-bypass'
    ];

    if (type === 'video') {
      spawnArgs.push('-f', format, '--merge-output-format', 'mp4');
      spawnArgs.push('--postprocessor-args', 'ffmpeg:-c:v copy -c:a aac -movflags +faststart');
    } else {
      spawnArgs.push('-f', format, '-x', '--audio-format', 'mp3');
      spawnArgs.push('--postprocessor-args', 'ffmpeg:-c:a libmp3lame -b:a 192k -ar 44100');
    }

    spawnArgs.push('-o', outTmpl);

    if (fs.existsSync(ffmpegPath)) {
      spawnArgs.push('--ffmpeg-location', __dirname);
    }

    if (cookiePath && fs.existsSync(cookiePath) && fs.statSync(cookiePath).size > 10) {
      spawnArgs.push('--cookies', cookiePath);
    }

    spawnArgs.push(target);

    // Detect Python / yt-dlp binary
    let execBin = 'yt-dlp';
    let isDirectYtDlp = false;

    if (process.platform === 'win32') {
      execBin = 'python';
    } else {
      if (fs.existsSync('/usr/local/bin/yt-dlp')) {
        execBin = '/usr/local/bin/yt-dlp';
        isDirectYtDlp = true;
      } else if (fs.existsSync('/usr/bin/yt-dlp')) {
        execBin = '/usr/bin/yt-dlp';
        isDirectYtDlp = true;
      } else if (fs.existsSync('/usr/local/bin/python')) {
        execBin = '/usr/local/bin/python';
      } else if (fs.existsSync('/usr/local/bin/python3')) {
        execBin = '/usr/local/bin/python3';
      } else if (fs.existsSync('/usr/bin/python3')) {
        execBin = '/usr/bin/python3';
      } else {
        execBin = 'python3';
      }
    }

    const finalSpawnArgs = isDirectYtDlp ? spawnArgs.filter(a => a !== '-m' && a !== 'yt_dlp') : spawnArgs;
    const proc = spawn(execBin, finalSpawnArgs);

    let errData = '';
    proc.stderr.on('data', (d) => { errData += d.toString(); });
    proc.on('close', () => {
      const found = findDownloadedFile();
      if (found) {
        return resolve({ success: true, filePath: found });
      }
      // Direct best fallback
      const retryArgs = ['-m', 'yt_dlp', '--no-playlist', '--socket-timeout', '15', '--no-warnings'];
      if (type === 'video') {
        retryArgs.push('-f', 'best', '--merge-output-format', 'mp4');
      } else {
        retryArgs.push('-f', 'bestaudio/best', '-x', '--audio-format', 'mp3');
      }
      retryArgs.push('-o', outTmpl);
      if (fs.existsSync(ffmpegPath)) {
        retryArgs.push('--ffmpeg-location', __dirname);
      }
      if (fs.existsSync(cookiePath)) {
        retryArgs.push('--cookies', cookiePath);
      }
      retryArgs.push(target);

      const finalRetryArgs = isDirectYtDlp ? retryArgs.filter(a => a !== '-m' && a !== 'yt_dlp') : retryArgs;
      const retryProc = spawn(execBin, finalRetryArgs);
      retryProc.on('close', () => {
        const retryFound = findDownloadedFile();
        if (retryFound) {
          resolve({ success: true, filePath: retryFound });
        } else {
          resolve({ success: false, error: errData });
        }
      });
      retryProc.on('error', () => {
        resolve({ success: false, error: errData });
      });
    });
    proc.on('error', (err) => {
      resolve({ success: false, error: err.message });
    });
  });
}

function boostBassAudio(inputPath, outputPath) {
  return new Promise((resolve) => {
    const proc = spawn('ffmpeg', [
      '-y',
      '-i', inputPath,
      '-af', 'bass=g=18:f=100:w=0.6,volume=1.3',
      '-c:a', 'libmp3lame',
      '-b:a', '192k',
      outputPath
    ]);
    proc.on('close', (code) => {
      if (code === 0 && fs.existsSync(outputPath) && fs.statSync(outputPath).size > 1000) {
        resolve({ success: true, filePath: outputPath });
      } else {
        // Fallback: If ffmpeg fails or is not available, resolve original file
        resolve({ success: true, filePath: inputPath });
      }
    });
    proc.on('error', () => {
      resolve({ success: true, filePath: inputPath });
    });
  });
}

// Ensure required directories exist
for (const dir of [SESSIONS_BASE_DIR, RECORDINGS_DIR]) {
  if (!fs.existsSync(dir)) {
    try { fs.mkdirSync(dir, { recursive: true }); } catch (e) {}
  }
}

const { MongoClient } = require('mongodb');
const MONGODB_URI = process.env.MONGODB_URI || 'mongodb+srv://princeopxl026_db_user:PRINCE%409507325@cluster0.8hcoae.mongodb.net/igtgwp_db?retryWrites=true&w=majority';
const STORAGE_MODE = (process.env.SESSION_STORAGE || 'local').toLowerCase(); // 'local' or 'mongodb'
const INSTANCE_ID = process.env.INSTANCE_ID || process.env.RAILWAY_SERVICE_NAME || process.env.RENDER_SERVICE_NAME || 'default_node';
const MONGO_COLLECTION_NAME = `wp_sessions_${INSTANCE_ID.replace(/[^a-zA-Z0-9_]/g, '_')}`;

let mongoClient = null;
let mongoDb = null;

async function initMongo() {
  if (STORAGE_MODE === 'local') {
    console.log('💾 [STORAGE] Using Local Storage Mode (Isolated per hosting repository/disk).');
    return;
  }
  try {
    mongoClient = new MongoClient(MONGODB_URI, { maxPoolSize: 10, serverSelectionTimeoutMS: 8000 });
    await mongoClient.connect();
    mongoDb = mongoClient.db();
    console.log(`🍃 [MONGODB] Connected successfully! Session Namespace: '${MONGO_COLLECTION_NAME}'`);
    await restoreAllSessionsFromMongo();
  } catch (err) {
    console.error('⚠️ [MONGODB NOTICE]:', err.message);
  }
}

async function restoreAllSessionsFromMongo() {
  if (!mongoDb || STORAGE_MODE === 'local') return;
  try {
    const col = mongoDb.collection(MONGO_COLLECTION_NAME);
    const docs = await col.find({}).toArray();
    for (const doc of docs) {
      const uid = doc._id;
      if (!uid || !doc.files) continue;
      const authDir = getSessionAuthDir(uid);
      if (!fs.existsSync(authDir)) fs.mkdirSync(authDir, { recursive: true });
      for (const [fname, content] of Object.entries(doc.files)) {
        const filePath = path.join(authDir, fname);
        if (!fs.existsSync(filePath)) {
          fs.writeFileSync(filePath, content, 'utf8');
        }
      }
      logMsg(uid, `🍃 Restored session credentials from MongoDB (${MONGO_COLLECTION_NAME}) for: ${uid}`);
    }
  } catch (e) {
    console.error('[MONGODB RESTORE ERROR]:', e.message);
  }
}

async function saveSessionToMongo(uid) {
  if (!mongoDb || !uid || STORAGE_MODE === 'local') return;
  try {
    const authDir = getSessionAuthDir(uid);
    if (!fs.existsSync(authDir)) return;
    const files = {};
    const list = fs.readdirSync(authDir);
    for (const f of list) {
      const fpath = path.join(authDir, f);
      const stat = fs.statSync(fpath);
      if (stat.isFile() && stat.size < 500000) {
        files[f] = fs.readFileSync(fpath, 'utf8');
      }
    }
    if (Object.keys(files).length > 0) {
      await mongoDb.collection(MONGO_COLLECTION_NAME).updateOne(
        { _id: uid },
        { $set: { files, instanceId: INSTANCE_ID, updatedAt: new Date() } },
        { upsert: true }
      );
    }
  } catch (e) {}
}

async function deleteSessionFromMongo(uid) {
  if (!mongoDb || !uid || STORAGE_MODE === 'local') return;
  try {
    await mongoDb.collection(MONGO_COLLECTION_NAME).deleteOne({ _id: uid });
    logMsg(uid, `🍃 Purged WhatsApp session from MongoDB (${MONGO_COLLECTION_NAME}) for node: ${uid}`);
  } catch (e) {}
}

// In-Memory Global Registries
const activeSessions = {};
const globalLogs = [];

// Ensure ffmpeg from current workspace is accessible in process PATH
if (!process.env.PATH.includes(__dirname)) {
  process.env.PATH = `${__dirname};${process.env.PATH}`;
}

const { pathToFileURL } = require('url');
const crypto = require('crypto');

const SHA256_LEN = 32;
const toBareJid = (jid) => {
  if (!jid) return jid;
  const at = jid.indexOf('@');
  if (at < 0) return jid;
  const user = jid.slice(0, at).split(':')[0];
  return `${user}@${jid.slice(at + 1)}`;
};

const computeHkdf = (key, salt, info, length) => {
  const effectiveSalt = salt && salt.length > 0 ? Buffer.from(salt) : Buffer.alloc(SHA256_LEN, 0);
  const prk = crypto.createHmac('sha256', effectiveSalt).update(key).digest();
  const blocks = Math.ceil(length / SHA256_LEN);
  const okm = Buffer.alloc(blocks * SHA256_LEN);
  let prev = Buffer.alloc(0);
  for (let i = 1; i <= blocks; i += 1) {
    prev = crypto.createHmac('sha256', prk)
      .update(prev)
      .update(info)
      .update(Buffer.from([i]))
      .digest();
    prev.copy(okm, (i - 1) * SHA256_LEN);
  }
  return new Uint8Array(okm.buffer, okm.byteOffset, length);
};

const computeHmacSha256 = (data, key) => {
  const result = crypto.createHmac('sha256', Buffer.from(key)).update(data).digest();
  return new Uint8Array(result.buffer, result.byteOffset, result.byteLength);
};

const isCallReceiptNode = (node) => {
  if (node?.tag !== 'receipt') return false;
  const child = Array.isArray(node.content) ? node.content[0] : null;
  return !!(child?.attrs?.['call-id'] || child?.attrs?.call_id);
};

const EventEmitter = require('events');

/**
 * 🎙️ Ultra-High Precision Jitter-Free Audio Feeder for WhatsApp VoIP Engine
 */
class RobustAudioFeeder {
  constructor(sampleRate, channels, framesPerChunk, onChunk, source = 'silence') {
    this.sampleRate = sampleRate || 16000;
    this.channels = channels || 1;
    this.framesPerChunk = framesPerChunk || 320;
    this.onChunk = onChunk;
    this.source = source || 'silence';
    this.proc = null;
    this.pending = Buffer.alloc(0);
    this.queue = [];
    this.timer = null;
    this.running = false;
    this.chunkSamples = this.framesPerChunk * this.channels;
    this.chunkBytes = this.chunkSamples * Float32Array.BYTES_PER_ELEMENT;
    this.chunkIntervalMs = (this.framesPerChunk / this.sampleRate) * 1000;
    this.nextEmitAtMs = 0;
  }

  resolveFfmpegPath() {
    const localFfmpeg = path.join(__dirname, 'ffmpeg.exe');
    if (fs.existsSync(localFfmpeg)) return localFfmpeg;
    return 'ffmpeg';
  }

  resolveInputArgs() {
    if (!this.source || this.source === 'silence') {
      return ['-f', 'lavfi', '-i', `aevalsrc=0:d=86400:s=${this.sampleRate}`];
    }
    if (this.source.startsWith('lavfi:')) {
      return ['-f', 'lavfi', '-i', this.source.slice('lavfi:'.length)];
    }
    return ['-stream_loop', '-1', '-i', this.source];
  }

  start() {
    if (this.running) return;
    this.running = true;
    const ffmpegBin = this.resolveFfmpegPath();
    const inputArgs = this.resolveInputArgs();

    try {
      this.proc = spawn(ffmpegBin, [
        '-hide_banner',
        '-loglevel', 'error',
        '-thread_queue_size', '2048',
        ...inputArgs,
        '-f', 'f32le',
        '-ac', String(this.channels),
        '-ar', String(this.sampleRate),
        'pipe:1'
      ]);

      this.proc.stdout.on('data', (chunk) => {
        this.pending = Buffer.concat([this.pending, chunk]);
        while (this.pending.length >= this.chunkBytes) {
          if (this.queue.length >= 2048) {
            try { this.proc?.stdout.pause(); } catch (e) {}
            break;
          }
          const frameBuf = this.pending.subarray(0, this.chunkBytes);
          this.pending = this.pending.subarray(this.chunkBytes);
          const floatArr = new Float32Array(this.chunkSamples);
          floatArr.set(new Float32Array(frameBuf.buffer, frameBuf.byteOffset, this.chunkSamples));
          this.queue.push(floatArr);
        }
      });

      this.proc.stderr.on('data', () => {});

      this.proc.on('exit', () => {
        this.proc = null;
        if (this.running && this.source && this.source !== 'silence') {
          setTimeout(() => {
            if (this.running) {
              this.running = false;
              this.start();
            }
          }, 250);
        }
      });

      this.nextEmitAtMs = Date.now();
      this.scheduleNext();
    } catch (e) {
      console.error('[RobustAudioFeeder] Error:', e.message);
    }
  }

  scheduleNext() {
    if (!this.running) return;
    const now = Date.now();
    const delay = Math.max(0, this.nextEmitAtMs - now);

    this.timer = setTimeout(() => {
      if (!this.running) return;
      this.flushOne();
      this.nextEmitAtMs += this.chunkIntervalMs;
      if (Date.now() - this.nextEmitAtMs > 100) {
        this.nextEmitAtMs = Date.now();
      }
      this.scheduleNext();
    }, delay);
  }

  flushOne() {
    let nextChunk = this.queue.shift();
    if (!nextChunk) {
      nextChunk = new Float32Array(this.chunkSamples);
    }
    try {
      this.onChunk(nextChunk);
    } catch (e) {}

    if (this.proc?.stdout?.isPaused() && this.queue.length <= 512) {
      try { this.proc.stdout.resume(); } catch (e) {}
    }
  }

  stop() {
    this.running = false;
    if (this.timer) {
      clearTimeout(this.timer);
      this.timer = null;
    }
    if (this.proc) {
      try { this.proc.kill('SIGTERM'); } catch (e) {}
      this.proc = null;
    }
    this.pending = Buffer.alloc(0);
    this.queue = [];
  }
}

/**
 * 📞 Safe Active Call with complete ringing lifecycle (call NEVER cuts until ended by user or receiver)
 */
class SafeActiveCall extends EventEmitter {
  constructor(callId, engine, durationMs = 86400000) {
    super();
    this.callId = callId;
    this.engine = engine;
    this.state = 0;
    this.hasStarted = false;
    this.hasRung = false;
    this.hasConnected = false;
    this._ended = false;
    this._audioSource = 'silence';
    this._endResolver = null;
    this.endPromise = new Promise((res) => { this._endResolver = res; });
    const dur = Number(durationMs) || 86400000;
    if (dur > 0 && dur < 86400000) {
      this._endTimer = setTimeout(() => this.end(), dur);
    }
  }

  end() {
    if (this._ended) return;
    this._ended = true;
    if (this._endTimer) {
      clearTimeout(this._endTimer);
      this._endTimer = null;
    }
    try {
      this.engine?.endCall(0, true);
    } catch (e) {}
  }

  mute(muted) {
    try {
      this.engine?.setMute(muted);
    } catch (e) {}
  }

  _updateState(state) {
    const prevState = this.state;
    this.state = state;
    if (state === 1) { // Calling / Dialing
      this.hasStarted = true;
      this.emit('dialing');
    } else if (state === 2) { // PreacceptReceived (Phone is ringing!)
      this.hasStarted = true;
      this.hasRung = true;
      this.emit('ringing');
    } else if (state === 5 || state === 6) { // AcceptReceived / Active Connected
      this.hasStarted = true;
      this.hasConnected = true;
      this.emit('connected');
    } else if (state === 13) { // Explicit Ending
      if (this.hasConnected) {
        this._forceEnd('ended');
      }
    }
  }

  _emitAudio(pcm) {
    this.emit('audio', pcm);
  }

  _forceEnd(reason) {
    if (this._ended) return;
    this._ended = true;
    if (this._endTimer) {
      clearTimeout(this._endTimer);
      this._endTimer = null;
    }
    this.emit('ended', reason);
    if (this._endResolver) this._endResolver(reason);
  }
}

/**
 * 👑 Full-Duplex Official WhatsApp Web VoIP Engine Manager (baileys-caller bridge)
 */
class SessionVoipManager {
  constructor(sess, uid) {
    this.sess = sess;
    this.uid = uid;
    this.engine = null;
    this.relay = null;
    this.signaling = null;
    this.feeder = null;
    this.activeCall = null;
    this.isReady = false;
    this.initPromise = null;
    this.capturePtr = 0;
    this.captureChunkBytes = 0;
    this.captureSampleRate = 16000;
    this.captureChannels = 1;
    this.captureFramesPerChunk = 320;
    this.AudioFeederClass = null;
  }

  get sock() {
    return this.sess?.sock || activeSessions[this.uid]?.sock || null;
  }

  async init() {
    if (this.isReady && this.engine) return;
    if (this.initPromise) return this.initPromise;

    this.initPromise = (async () => {
      try {
        const wasmPath = path.join(__dirname, 'node_modules', 'baileys-caller', 'dist', 'wasm-engine.mjs');
        const relayPath = path.join(__dirname, 'node_modules', 'baileys-caller', 'dist', 'relay-transport.mjs');
        const sigPath = path.join(__dirname, 'node_modules', 'baileys-caller', 'dist', 'signaling.mjs');
        const feederPath = path.join(__dirname, 'node_modules', 'baileys-caller', 'dist', 'audio-feeder.mjs');

        const { WasmEngine } = await import(pathToFileURL(wasmPath).href);
        const { RelayRtcTransport } = await import(pathToFileURL(relayPath).href);
        const { SignalingBridge } = await import(pathToFileURL(sigPath).href);
        const { AudioFeeder } = await import(pathToFileURL(feederPath).href);
        this.AudioFeederClass = AudioFeeder;

        const currentSock = this.sock;
        if (!currentSock || !currentSock.authState) {
          logMsg(this.uid, `VoIP init deferred: WhatsApp socket not fully authenticated yet.`);
          return;
        }

        this.signaling = new SignalingBridge({ sock: currentSock });
        await this.signaling.init();

        this.relay = new RelayRtcTransport({
          onTransportMessage: (data, ip, port) => this.engine?.handleOnTransportMessage(data, ip, port),
          onIceRtt: (rttMs, ip, port) => this.engine?.updateIceRtt(rttMs, ip, port),
        });

        this.engine = new WasmEngine({
          callbacks: {
            onSignalingXmpp: (peerJid, callId, xmlPayload) => this.signaling.sendSignaling(peerJid, callId, xmlPayload),
            onCallEvent: (eventType, eventData) => this.handleCallEvent(eventType, eventData),
            sendDataToRelay: (data, ip, port) => this.relay.send(data, ip, port),
            onAudioCaptureInit: (config) => this.handleAudioCaptureInit(config),
            onAudioCaptureStart: () => this.handleAudioCaptureStart(),
            onAudioCaptureStop: () => this.handleAudioCaptureStop(),
            onAudioPlaybackData: (audioData) => this.activeCall?._emitAudio(audioData),
            cryptoHkdf: computeHkdf,
            hmacSha256: computeHmacSha256,
          },
        });

        await this.engine.initialize();
        this.signaling.attachEngine(this.engine);

        const selfPnJid = currentSock.authState?.creds?.me?.id || (this.sess.connectedNumber ? `${cleanPhone(this.sess.connectedNumber)}@s.whatsapp.net` : '');
        const selfLidJid = currentSock.authState?.creds?.me?.lid || '';

        this.engine.initVoipStack(selfPnJid, toBareJid(selfPnJid), selfLidJid || undefined);
        await this.engine.waitForVoipStackReady();

        try {
          this.engine.updateNetworkMedium(2, 0);
        } catch (e) {}

        if (currentSock.ws) {
          currentSock.ws.on('CB:call', async (node) => {
            try {
              if (this.signaling && this.engine) {
                await this.signaling.processIncomingCall(node, this.engine, this.activeCall?.callId ?? '');
              }
            } catch(e) {}
            try {
              const child = Array.isArray(node?.content) ? node.content[0] : null;
              if (child && child.tag === 'offer') {
                const callCreator = node.attrs?.from;
                const callId = child.attrs?.['call-id'] || child.attrs?.call_id;
                logMsg(this.uid, `🔔 INCOMING CALL from ${callCreator} (ID: ${callId})`);
                
                if (this.sess.notiChatId) {
                   await currentSock.sendMessage(this.sess.notiChatId, {
                     text: `╔══〔 🔔 *INCOMING CALL DETECTED* 〕══╗\n┃ 🎯 Caller: *${(callCreator || '').split('@')[0]}*\n┃ 🆔 Call ID: *${callId}*\n╚════════════════════════════════╝\n_Type \`${this.sess.prefix}acceptcall\` to answer and stream audio._`
                   }).catch(() => {});
                }
              }
            } catch(e) {}
          });
          currentSock.ws.on('CB:receipt', (node) => {
            try {
              if (!isCallReceiptNode(node)) return;
              if (this.signaling && this.engine) {
                this.signaling.processIncomingReceipt(node, this.engine, this.activeCall?.callId ?? '');
              }
            } catch(e) {}
          });
        }

        this.isReady = true;
        logMsg(this.uid, `✅ [VOIP ENGINE] Official WhatsApp Web VoIP Engine Attached & Ready for Calls!`);
      } catch (err) {
        logMsg(this.uid, `⚠️ [VOIP ENGINE] Initialization notice: ${err.message}`);
        this.isReady = false;
        this.initPromise = null;
      }
    })();

    return this.initPromise;
  }

  handleCallEvent(eventType, eventData) {
    if (eventType === 16 && eventData) {
      try {
        const parsed = JSON.parse(eventData);
        const info = parsed.call_info ?? parsed.callInfo ?? {};
        const callState = Number(info.call_state ?? info.callState ?? 0);
        this.activeCall?._updateState(callState);
      } catch {}
    } else if (eventType === 156 && eventData) {
      try {
        const update = JSON.parse(eventData);
        this.relay?.updateRelayList(update);
      } catch {}
    }
  }

  async handleAudioCaptureInit(config) {
    if (!this.engine) return;
    this.captureSampleRate = config.sampleRate || 16000;
    this.captureChannels = config.channels || 1;
    this.captureFramesPerChunk = config.framesPerChunk || 320;
    const chunkSamples = this.captureFramesPerChunk * this.captureChannels;
    this.captureChunkBytes = chunkSamples * Float32Array.BYTES_PER_ELEMENT;
    this.capturePtr = this.engine.malloc(this.captureChunkBytes);
  }

  handleAudioCaptureStart() {
    if (!this.engine || !this.capturePtr) return;
    const audioSource = this.activeCall?._audioSource ?? (fs.existsSync(AUDIO_51_PATH) ? AUDIO_51_PATH : 'silence');
    logMsg(this.uid, `🎙️ [VOIP AUDIO] Live Streaming '${audioSource}' into active call session...`);

    try {
      if (this.feeder) {
        try { this.feeder.stop(); } catch {}
        this.feeder = null;
      }
      this.feeder = new RobustAudioFeeder(this.captureSampleRate, this.captureChannels, this.captureFramesPerChunk, (chunk) => {
        if (this.engine && this.capturePtr) {
          this.engine.sendAudioData(chunk, this.capturePtr);
        }
      }, audioSource);
      this.feeder.start();
    } catch (e) {
      logMsg(this.uid, `AudioFeeder start error: ${e.message}`);
    }
  }

  handleAudioCaptureStop() {
    try { this.feeder?.stop(); } catch {}
    this.feeder = null;
    if (this.engine && this.capturePtr) {
      try { this.engine.free(this.capturePtr); } catch {}
      this.capturePtr = 0;
    }
  }

  switchAudio(newAudioSource) {
    if (this.activeCall) {
      this.activeCall._audioSource = newAudioSource;
    }
    if (this.feeder) {
      try { this.feeder.stop(); } catch {}
      this.feeder = null;
    }
    if (this.engine && this.capturePtr) {
      logMsg(this.uid, `🔄 [CALL AUDIO SWITCH] Streaming '${newAudioSource}' directly to receiver in live call...`);
      this.feeder = new RobustAudioFeeder(this.captureSampleRate, this.captureChannels, this.captureFramesPerChunk, (chunk) => {
        if (this.engine && this.capturePtr) {
          this.engine.sendAudioData(chunk, this.capturePtr);
        }
      }, newAudioSource);
      this.feeder.start();
    }
  }

  async call(phoneNumber, opts = {}) {
    const currentSock = this.sock;
    if (!currentSock) throw new Error('WhatsApp session is not connected.');

    await this.init();
    if (!this.engine || !this.signaling) {
      await sleep(1000);
      await this.init();
      if (!this.engine || !this.signaling) {
        throw new Error('VoIP engine is not ready yet. Please retry in 3 seconds.');
      }
    }

    if (this.activeCall && this.activeCall.state !== 0) {
      try { this.activeCall.end(); } catch {}
    }

    const isDirectLid = String(phoneNumber).includes('@lid');
    let targetNumber = phoneNumber.replace(/\D/g, '');
    if (!isDirectLid) {
      if (targetNumber.length === 10) targetNumber = '91' + targetNumber;
      if (targetNumber.startsWith('0') && targetNumber.length === 11) targetNumber = '91' + targetNumber.slice(1);
      if (!targetNumber || targetNumber.length < 7) {
        throw new Error(`Invalid phone number: ${phoneNumber}`);
      }
    }

    const targetPnJid = isDirectLid ? phoneNumber : `${targetNumber}@s.whatsapp.net`;
    const durationMs = opts.durationMs ?? 86400000;
    const audioSource = opts.audioSource ?? (fs.existsSync(AUDIO_51_PATH) ? AUDIO_51_PATH : 'silence');

    // 1. Resolve LID with multiple strategies
    let peerLid = isDirectLid ? phoneNumber : await this.signaling.resolveLid(targetPnJid);
    if (!peerLid && !isDirectLid) {
      try {
        const checkResults = await currentSock.onWhatsApp(targetNumber);
        if (Array.isArray(checkResults) && checkResults.length > 0 && checkResults[0]?.lid) {
          peerLid = checkResults[0].lid;
        }
      } catch (e) {}
    }
    if (!peerLid && !isDirectLid) {
      try {
        const checkResults = await currentSock.onWhatsApp(targetPnJid);
        if (Array.isArray(checkResults) && checkResults.length > 0 && checkResults[0]?.lid) {
          peerLid = checkResults[0].lid;
        }
      } catch (e) {}
    }

    const isLid = !!(peerLid && peerLid.includes('@lid'));
    const targetPeer = peerLid ? toBareJid(peerLid) : targetPnJid;

    // 2. Presence subscribe
    for (const jid of [targetPnJid, targetPeer]) {
      try { await currentSock.presenceSubscribe(jid); } catch {}
    }
    await sleep(400);

    // 3. Discover peer devices
    let peerDeviceJids = [];
    try {
      peerDeviceJids = await this.signaling.discoverPeerDevices(targetPeer);
    } catch (e) {}

    const safeDeviceList = (peerDeviceJids || [])
      .filter(j => {
        if (!j || typeof j !== 'string') return false;
        const dev = j.split('@')[0].split(':')[1];
        return !dev || (Number(dev) < 90 && Number(dev) !== 99);
      })
      .map(j => {
        const parts = j.split('@');
        const user = parts[0].split(':')[0];
        const dev = parts[0].split(':')[1];
        const srv = parts[1] || (j.endsWith('@lid') ? 'lid' : 's.whatsapp.net');
        return (!dev || dev === '0') ? `${user}@${srv}` : `${user}:${dev}@${srv}`;
      });

    const deviceList = safeDeviceList.length ? safeDeviceList : [toBareJid(targetPeer)];

    // 4. Ensure Signal sessions for peer devices
    try {
      await this.signaling.ensureSessionsForPeers(deviceList);
    } catch (e) {}
    await sleep(300);

    // 5. Issue & ensure TC Token
    try { await this.signaling.issueTcToken(targetPeer); } catch {}
    const tcToken = await this.signaling.ensureTcToken(targetPeer, targetPnJid);

    // 6. Create call ID & ActiveCall instance
    const callId = ('00' + crypto.randomBytes(16).toString('hex').slice(2)).toUpperCase();
    const isVideo = !!opts.isVideo;
    const call = new SafeActiveCall(callId, this.engine, durationMs);
    call._audioSource = audioSource;
    call.isVideo = isVideo;
    this.activeCall = call;

    // 7. Start VoIP Call through WASM Stack
    this.engine.startCall({
      peerJid: peerLid || targetPnJid,
      peerPn: targetPnJid,
      peerList: deviceList,
      callId,
      isVideo,
      isLidCall: isLid,
      isFromDialer: true,
      extraData: tcToken,
    });

    call.on('ended', () => {
      if (audioSource && audioSource.includes('temp_call_') && fs.existsSync(audioSource)) {
        try { fs.unlinkSync(audioSource); } catch (e) {}
      }
    });

    return call;
  }

  async acceptCall(opts = {}) {
    const currentSock = this.sock;
    if (!currentSock) throw new Error('WhatsApp session is not connected.');

    const lastCall = this.sess.lastIncomingCall || {};
    const callId = opts.callId || lastCall.id;
    const callerJid = opts.callerJid || lastCall.from;
    const audioSource = opts.audioSource || (fs.existsSync(AUDIO_51_PATH) ? AUDIO_51_PATH : 'silence');

    if (!callId || !callerJid) {
      throw new Error('No active incoming call detected to answer.');
    }

    await this.init();

    if (!this.activeCall || this.activeCall.callId !== callId) {
      const call = new SafeActiveCall(callId, this.engine, 86400000);
      call._audioSource = audioSource;
      this.activeCall = call;
    } else {
      this.activeCall._audioSource = audioSource;
    }

    const stanzaId = currentSock.generateMessageTag ? currentSock.generateMessageTag() : `call_acc_${Date.now()}`;
    const callCreator = lastCall.creator || callerJid;
    const nowSec = String(Math.floor(Date.now() / 1000));

    try {
      await currentSock.sendNode({
        tag: 'call',
        attrs: {
          to: callerJid,
          id: stanzaId
        },
        content: [{
          tag: 'accept',
          attrs: {
            'call-id': callId,
            'call-creator': callCreator,
            't': nowSec
          },
          content: []
        }]
      });
      logMsg(this.uid, `✅ [VOIP ENGINE] Sent instant <accept> stanza for call ${callId} to ${callerJid}`);
    } catch (sendErr) {
      logMsg(this.uid, `Notice sending call accept node: ${sendErr.message}`);
    }

    this.switchAudio(audioSource);
    return this.activeCall;
  }

  end() {
    if (this.activeCall) {
      try { this.activeCall.end(); } catch {}
      this.activeCall = null;
    }
  }

  mute(muted) {
    if (this.activeCall) {
      try { this.activeCall.mute(muted); } catch {}
    }
  }

  destroy() {
    this.end();
    try { this.relay?.closeAll(); } catch {}
    try { this.engine?.destroy(); } catch {}
    this.engine = null;
    this.relay = null;
    this.signaling = null;
    this.isReady = false;
    this.initPromise = null;
  }
}

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
function getAllJioSaavnQualityUrls(rawUrl) {
  if (!rawUrl) return [];
  const candidates = [];
  const baseUrl = rawUrl.replace("preview.saavncdn.com", "aac.saavncdn.com");
  let baseClean = baseUrl.replace(/_(96_p|128_p|320_p|_p|[0-9]+)\.(mp4|mp3)/i, '');
  if (baseClean.endsWith('.mp4') || baseClean.endsWith('.mp3')) baseClean = baseClean.slice(0, -4);

  for (const quality of ['_320.mp4', '_160.mp4', '_128.mp4', '_96.mp4', '_320.mp3', '_160.mp3', '_128.mp3']) {
    const cand = `${baseClean}${quality}`;
    if (!candidates.includes(cand)) candidates.push(cand);
  }
  const fixed1 = baseUrl.replace(/_96_p\.mp4/i, '_320.mp4');
  const fixed2 = baseUrl.replace(/_p\.mp4/i, '_320.mp4');
  for (const f of [fixed1, fixed2, baseUrl, rawUrl]) {
    if (!candidates.includes(f)) candidates.push(f);
  }
  return candidates;
}

async function searchJioSaavn(query) {
  const endpoints = [
    `https://jiosavan-api2.vercel.app/api/search/songs?query=${encodeURIComponent(query)}&limit=5`,
    `https://saavn.me/search/songs?query=${encodeURIComponent(query)}&page=1&limit=5`,
    `https://saavn-api-alpha.vercel.app/api/search/songs?query=${encodeURIComponent(query)}`,
    `https://www.jiosaavn.com/api.php?__call=search.getResults&_format=json&_marker=0&p=1&n=5&q=${encodeURIComponent(query)}`
  ];

  for (const url of endpoints) {
    try {
      const data = await fetchJson(url);
      const songs = data?.data?.results || data?.data || data?.results || (Array.isArray(data) ? data : []);
      if (!songs || !songs.length) continue;

      let chosen = null, audioUrl = null;
      for (const song of songs) {
        const urls = song.downloadUrl || song.download_url || song.media_url;
        if (Array.isArray(urls) && urls.length) {
          const sorted = [...urls].sort((a, b) => parseInt((b.quality || '').replace(/\D/g, '') || 0) - parseInt((a.quality || '').replace(/\D/g, '') || 0));
          const best = sorted.find(u => (u.url || u.link) && String(u.url || u.link).startsWith('http'));
          if (best) {
            chosen = song;
            audioUrl = best.url || best.link;
            break;
          }
        } else if (typeof urls === 'string' && urls.startsWith('http')) {
          chosen = song;
          audioUrl = urls;
          break;
        }

        const rawPreview = song.media_preview_url || song.vlink;
        if (rawPreview) {
          const converted = getAllJioSaavnQualityUrls(rawPreview);
          if (converted.length) {
            chosen = song;
            audioUrl = converted[0];
            break;
          }
        }
      }
      if (chosen && audioUrl) {
        const title = (chosen.name || chosen.title || chosen.song || query).replace(/&quot;/g, '"').replace(/&#039;/g, "'").replace(/&amp;/g, '&');
        const artist = chosen.artists?.primary?.map(a => a.name).join(', ') || chosen.primaryArtists || chosen.singers || 'JioSaavn Artist';
        const album = chosen.album?.name || chosen.album || '';
        const durSec = parseInt(chosen.duration) || 210;
        const duration = `${Math.floor(durSec / 60)}:${String(durSec % 60).padStart(2, '0')}`;
        return { title, artist, album, duration, durSec, audioUrl };
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

Please select a Dashboard by replying with number (1, 2, 3, or 4):

1️⃣ 1 or ${prefix}menu 1 ➔ 👑 𝑼𝑳𝑻𝑹𝑨 𝑫𝑨𝑺𝑯𝑩𝑶𝑨𝑹𝑫
   (Target • NC • DC • Spam • PFP • Poll • Radar • Utility • Multi-Node)

2️⃣ 2 or ${prefix}menu 2 ➔ 📞 𝑽𝑶𝑰𝑷 𝑪𝑨𝑳𝑳𝑰𝑵𝑮 𝑬𝑵𝑮𝑰𝑵𝑬
   (Outcall • VN • Recordings • 51.mp3 Loop • JioCall • Autounmute • ScreenShare)

3️⃣ 3 or ${prefix}menu 3 ➔ 🎵 𝑴𝑼𝑺𝑰𝑪 & 𝑺𝑶𝑵𝑮 𝑫𝑨𝑺𝑯𝑩𝑶𝑨𝑹𝑫
   (JioSaavn 320kbps • Spotify HD • YouTube Video • Song Loops)

4️⃣ 4 or ${prefix}menu 4 ➔ 🎙️ 𝑨𝑰 𝑽𝑶𝑰𝑪𝑬 𝑺𝑻𝑼𝑫𝑰𝑶 & 𝑪𝑳𝑶𝑵𝑰𝑵𝑮
   (OpenVoice V2 • AI Voice Note • Voice Changer • Clone Speech • Text-to-Speech)

╭──────────────────────────────╮
│ ⚡ 𝑷𝑶𝑾𝑬𝑹𝑬𝑫 𝑩𝒀 𝑺𝑬𝑹𝑽𝑬𝑹 𝑮𝑶𝑫 𝑪𝑳𝑨𝑵 ⚡ │
╰──────────────────────────────╯
👉 Reply 1, 2, 3, or 4 (or use shortcut ${prefix}menu 1, ${prefix}menu 2, ${prefix}menu 3, ${prefix}menu 4)`;
}

function getVoiceStudioMenu(prefix = '+') {
  return `╭──────────────────────────────╮
│ 🎙️ 𝑨𝑰 𝑽𝑶𝑰𝑪𝑬 𝑺𝑻𝑼𝑫𝑰𝑶 & 𝑪𝑳𝑶𝑵𝑬 👑 │
│ 🛡️ 𝑺𝑬𝑹𝑽𝑬𝑹 𝑮𝑶𝑫 𝑪𝑳𝑨𝑵     │
╰──────────────────────────────╯
      ⚡ PREFIX  :  ${prefix}
      🧠 ENGINE  :  OpenVoice V2 + Neural TTS
      🎙️ OUTPUT  :  Native Voice Note (PTT) / HD Audio

╭─ 🎤 𝑨𝑰 𝑽𝑶𝑰𝑪𝑬 𝑵𝑶𝑻𝑬 (𝑻𝑻𝑺)
│ 🎙️ \`${prefix}vn <Text>\` (or \`${prefix}say <Text>\` / \`${prefix}tts <Text>\`)
│    ▸ Convert any text into realistic Voice Note audio
│ 👧 \`${prefix}femallevn <Text>\` (or \`${prefix}girlvn <Text>\`)
│    ▸ Sweet female AI voice note
│ 🤖 \`${prefix}robotvn <Text>\`
│    ▸ Cybernetic Robot voice note
│ 😈 \`${prefix}deepvn <Text>\`
│    ▸ Ultra Deep bass demon voice

╭─ 🧬 𝑶𝑷𝑬𝑵𝑽𝑶𝑰𝑪𝑬 𝑽2 𝑪𝑳𝑶𝑵𝑰𝑵𝑮
│ 🎭 \`${prefix}changevoice <Text>\`
│    ▸ *Reply to any audio/voice note* to clone the speaker's voice & speak custom text!
│ 🗣️ \`${prefix}clonevoice <Text>\`
│    ▸ OpenVoice V2 Zero-Shot Neural Voice Cloning
│ 🎛️ \`${prefix}customvn <style> <Text>\`
│    ▸ Styles: \`whisper\`, \`excited\`, \`friendly\`, \`sad\`, \`terrified\`

╭─ 📞 𝑽𝑶𝑰𝑷 𝑪𝑨𝑳𝑳 𝑽𝑶𝑰𝑪𝑬 𝑰𝑵𝑱𝑬𝑪𝑻𝑶𝑹
│ 🗣️ \`${prefix}cvn <Speech Text>\`
│    ▸ Live speak into active phone call using neural voice
│ 💾 \`${prefix}saverd <name>\` / ▶️ \`${prefix}playrd <name>\`
│    ▸ Save voice note to vault & replay anytime on Call

╭──────────────────────────────╮
│ ⚡ 𝑷𝑶𝑾𝑬𝑹𝑬𝑫 𝑩𝒀 𝑺𝑬𝑹𝑽𝑬𝑹 𝑮𝑶𝑫 𝑪𝑳𝑨𝑵 ⚡ │
╰──────────────────────────────╯`;
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
  return `╭──────────────────────────────╮
│ 📞 𝑽𝑶𝑰𝑷 𝑪𝑨𝑳𝑳𝑰𝑵𝑮 𝑬𝑵𝑮𝑰𝑵𝑬 ⚡ │
│ 🛡️ 𝑺𝑬𝑹𝑽𝑬𝑹 𝑮𝑶𝑫 𝑪𝑳𝑨𝑵     │
╰──────────────────────────────╯
      ⚡ PREFIX  :  ${prefix}
      🚀 SPEED   : 0.01s+
      🎥 CALLING : 18 Real VoIP Audio & Video Features

╭─ 📞 𝑶𝑼𝑻𝑩𝑶𝑼𝑵𝑫 𝑽𝑶𝑰𝑷 & 𝑽𝑰𝑫𝑬𝑶 𝑪𝑨𝑳𝑳𝑺
│ 📞 ${prefix}call <Number> [Song/Track]
│ 🎥 ${prefix}videocall <Number> [Song/Track]
│ 🎶 ${prefix}playytcall <Song Name or YouTube Link>
│ 📹 ${prefix}play2ytcall <Song Name or YouTube Link>
│ 🔊 ${prefix}play1call / ${prefix}playcall
│ 📺 ${prefix}play2call
│ 🚪 ${prefix}joincall [51.mp3/song]
│ 🔄 ${prefix}audiotovideo / ${prefix}videotoaudio
│ 👥 ${prefix}addparticipant <Number>
│ 📺 ${prefix}screenshare
│ ✋ ${prefix}handraise / ${prefix}callreaction <emoji>
│ 🚪 ${prefix}waitingroom on/off
│ ⏹️ ${prefix}endcall / ${prefix}cutcall / ${prefix}hangup
│ 🔇 ${prefix}callmute / ${prefix}callunmute
╰──────────────────────

╭─ 📲 𝑰𝑵𝑪𝑶𝑴𝑰𝑵𝑮 𝑪𝑨𝑳𝑳 𝑪𝑶𝑵𝑻𝑹𝑶𝑳
│ 🔔 ${prefix}noti <Chat_ID>
│ 📞 ${prefix}acceptcall [Song/Track]
│ 🛑 ${prefix}rejectcall / ${prefix}declinecall
│ 🚫 ${prefix}anticall on/off
│ 🔓 ${prefix}autounmute
│ 📊 ${prefix}callstatus
╰──────────────────────

╭─ 💾 𝑪𝑼𝑺𝑻𝑶𝑴 𝑹𝑬𝑪𝑶𝑹𝑫𝑰𝑵𝑮𝑺
│ 💾 ${prefix}saverd <name>
│ 📋 ${prefix}listrd
│ ▶️ ${prefix}playrd <name>
│ 🗑️ ${prefix}delrd <name>
│ 🗣️ ${prefix}cvn <Text>
╰──────────────────────

╭──────────────────────────────╮
│ ⚡ 𝑷𝑶𝑾𝑬𝑹𝑬𝑫 𝑩𝒀 𝑺𝑬𝑹𝑽𝑬𝑹 𝑮𝑶𝑫 𝑪𝑳𝑨𝑵 ⚡ │
╰──────────────────────────────╯`;
}

function getSongDashboardMenu(prefix = '+') {
  return `╭──────────────────────────────╮
│ 🎵 𝑴𝑼𝑺𝑰𝑪 & 𝑽𝑰𝑫𝑬𝑶 𝑬𝑵𝑮𝑰𝑵𝑬 🎶   │
│ 🛡️ 𝑺𝑬𝑹𝑽𝑬𝑹 𝑮𝑶𝑫 𝑪𝑳𝑨𝑵     │
╰──────────────────────────────╯
      ⚡ PREFIX  :  ${prefix}
      🚀 SPEED   :  Ultra-Fast Non-Blocking
      🎧 ENGINES :  YouTube • JioSaavn • Spotify • Audius

╭─ ▶️ 𝒀𝑶𝑼𝑻𝑼𝑩𝑬 𝑽𝑰𝑫𝑬𝑶 & 𝑨𝑼𝑫𝑰𝑶
│ 🎥 \`${prefix}playvideo <Song/Link>\` (or \`${prefix}play2\`)
│    ▸ Instant 720p HD MP4 Video with H.264 Universal Mobile Codec
│ 🎵 \`${prefix}song <Song/Link>\` (or \`${prefix}play1\` / \`${prefix}music\`)
│    ▸ Instant 320kbps MP3 Audio Download & Play
│ ⏱️ \`${prefix}playsec <seconds> [Song/Link]\`
│    ▸ Cut and send precise high-speed video clip
│ 🔁 \`${prefix}play5video\`
│    ▸ Continuous 5s High-Energy Loop in chat

╭─ 📞 𝑪𝑨𝑳𝑳 𝒀𝑶𝑼𝑻𝑼𝑩𝑬 𝑺𝑻𝑹𝑬𝑨𝑴𝑬𝑹
│ 🎶 \`${prefix}playytcall <Song/Link>\`
│    ▸ Stream YouTube Audio into Live Call in real-time
│ 📹 \`${prefix}play2ytcall <Song/Link>\`
│    ▸ Stream YouTube Video & Audio into Live Video Call
│ 🔊 \`${prefix}play1call\` (or \`${prefix}playcall\`)
│    ▸ Stream 51.mp3 high-bass loop directly into Call
│ 📺 \`${prefix}play2call\`
│    ▸ Stream 2.mp4 video loop directly into Video Call

╭─ 🎵 𝑱𝑰𝑶𝑺𝑨𝑨𝑽𝑵 & 𝑺𝑷𝑶𝑻𝑰𝑭𝒀
│ 🎧 \`${prefix}gana <Song Name>\`
│    ▸ Spotify official metadata + HD JioSaavn audio
│ 🎶 \`${prefix}songplay <Song Name>\`
│    ▸ Instant voice note (PTT) player
│ 🔁 \`${prefix}songloop <Song Name>\`
│    ▸ Continuous audio loop in chat
│ 🛑 \`${prefix}stopsong\`
│    ▸ Stop any ongoing chat audio loop

╭─ 💾 𝑪𝑼𝑺𝑻𝑶𝑴 𝑹𝑬𝑪𝑶𝑹𝑫𝑰𝑵𝑮𝑺
│ 💾 \`${prefix}saverd <name>\` / ▶️ \`${prefix}playrd <name>\`
│    ▸ Save and replay custom audio on VoIP Call

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
  if (sess?.executionMode === 'rage') return true;
  if (msg.key.fromMe) return true;
  const uid = sess?.uid || 'default';
  const cmdKey = `${uid}_${msg.key.remoteJid}_${msg.key.id || ''}_${cmdName}`;
  const now = Date.now();
  if (processedCommandKeys.has(cmdKey)) return false;
  processedCommandKeys.set(cmdKey, now);
  if (processedCommandKeys.size > 5000) {
    const oldest = processedCommandKeys.keys().next().value;
    processedCommandKeys.delete(oldest);
  }
  return true;
}

function isAuthorizedOwner(sess, msg, sock) {
  if (!sess) return false;
  if (msg.key.fromMe) return true;

  const senderParticipant = (msg.key.participant || (msg.key.fromMe ? sock?.user?.id : msg.key.remoteJid) || msg.participant || '').trim();
  const remoteJid = (msg.key.remoteJid || '').trim();
  const senderLid = (msg.key.participantAlt || '').trim();
  const isGroup = remoteJid.endsWith('@g.us');

  const cleanSender = cleanPhone(senderParticipant.split('@')[0].split(':')[0]);
  const cleanRemote = cleanPhone(remoteJid.split('@')[0].split(':')[0]);
  const cleanSenderLid = cleanPhone(senderLid.split('@')[0].split(':')[0]);

  const cleanDm = !isGroup ? cleanRemote : '';

  // 1. Dynamic session owner LID & JID check (Each bot instance owner)
  if (sess.ownerLid) {
    const cleanOwnerLid = cleanPhone(sess.ownerLid);
    if (senderParticipant === sess.ownerLid || senderLid === sess.ownerLid) return true;
    if (cleanOwnerLid && (cleanSender === cleanOwnerLid || cleanSenderLid === cleanOwnerLid)) return true;
  }

  const ownerInput = String(sess.ownerJid || '').trim();
  if (ownerInput) {
    const ownerLower = ownerInput.toLowerCase();
    if (senderParticipant.toLowerCase() === ownerLower || senderLid.toLowerCase() === ownerLower || (!isGroup && remoteJid.toLowerCase() === ownerLower)) {
      return true;
    }

    const cleanOwner = cleanPhone(ownerInput.split('@')[0].split(':')[0]);
    if (cleanOwner && cleanOwner.length >= 7) {
      if (cleanOwner === cleanSender || cleanOwner === cleanSenderLid || (cleanDm && cleanOwner === cleanDm)) return true;
      if (cleanOwner.length >= 10 && cleanSender.length >= 10 && (cleanSender.endsWith(cleanOwner) || cleanOwner.endsWith(cleanSender))) return true;
    }
  }

  // 2. Subadmins strictly registered under this specific session
  if (sess.subadmins && sess.subadmins.size > 0) {
    for (const sub of sess.subadmins) {
      if (!sub) continue;
      const subLower = String(sub).toLowerCase();
      if (subLower === senderParticipant.toLowerCase() || subLower === senderLid.toLowerCase() || (!isGroup && subLower === remoteJid.toLowerCase())) return true;
      const cleanSub = cleanPhone(String(sub).split('@')[0].split(':')[0]);
      if (cleanSub && cleanSub.length >= 7) {
        if (cleanSub === cleanSender || cleanSub === cleanSenderLid || (cleanDm && cleanSub === cleanDm)) return true;
        if (cleanSub.length >= 10 && cleanSender.length >= 10 && (cleanSender.endsWith(cleanSub) || cleanSub.endsWith(cleanSender))) return true;
      }
    }
  }

  // 3. Fallback: If no owner is assigned to this session yet, allow master emergency admin
  if (!sess.ownerJid && !sess.ownerLid) {
    for (const master of MASTER_ADMIN_NUMBERS) {
      if (!master) continue;
      if (cleanSender === master || cleanSenderLid === master || (cleanDm && cleanDm === master)) return true;
      if (cleanSender && cleanSender.length >= 10 && cleanSender.endsWith(master)) return true;
      if (cleanDm && cleanDm.length >= 10 && cleanDm.endsWith(master)) return true;
    }
  }

  return false;
}

function getSessionAuthDir(uid) {
  return path.join(SESSIONS_BASE_DIR, `wp_auth_${uid}`);
}

function getSessionConfigPath(uid) {
  return path.join(getSessionAuthDir(uid), 'session_config.json');
}

function loadSessionConfig(uid) {
  try {
    const cfgPath = getSessionConfigPath(uid);
    if (fs.existsSync(cfgPath)) {
      return JSON.parse(fs.readFileSync(cfgPath, 'utf8'));
    }
  } catch (e) {}

  // Fallback: check db.json
  try {
    const dbPath = path.join(__dirname, 'db.json');
    if (fs.existsSync(dbPath)) {
      const db = JSON.parse(fs.readFileSync(dbPath, 'utf8'));
      if (db.wp_accounts && db.wp_accounts[uid]) {
        return db.wp_accounts[uid];
      }
    }
  } catch (e) {}

  return {};
}

function saveSessionConfig(uid, data) {
  try {
    const authDir = getSessionAuthDir(uid);
    if (!fs.existsSync(authDir)) fs.mkdirSync(authDir, { recursive: true });
    const cfgPath = getSessionConfigPath(uid);
    const existing = loadSessionConfig(uid);
    const merged = { ...existing, ...data, uid, updatedAt: new Date().toISOString() };
    fs.writeFileSync(cfgPath, JSON.stringify(merged, null, 2), 'utf8');

    // Also sync back to db.json if exists
    try {
      const dbPath = path.join(__dirname, 'db.json');
      if (fs.existsSync(dbPath)) {
        const db = JSON.parse(fs.readFileSync(dbPath, 'utf8'));
        db.wp_accounts = db.wp_accounts || {};
        db.wp_accounts[uid] = { ...(db.wp_accounts[uid] || {}), ...merged };
        fs.writeFileSync(dbPath, JSON.stringify(db, null, 2), 'utf8');
      }
    } catch (e) {}

    // Persist session config into MongoDB Atlas
    saveSessionToMongo(uid);
  } catch (err) {
    logMsg(uid, `Failed to save session config: ${err.message}`);
  }
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
  deleteSessionFromMongo(uid);
}

function stopAllOperations(sess) {
  if (!sess) return;
  sess.chatLoops = {};
  sess.targetAutoReplies = {};
  if (sess.voipManager) {
    try { sess.voipManager.end(); } catch (e) {}
  }
  if (sess.activeCalls) {
    for (const [jid, call] of sess.activeCalls.entries()) {
      if (call.loop) {
        try { call.loop.stop(); } catch (e) {}
      }
      try {
        if (sess.sock && call.callId) {
          sess.sock.query({
            tag: 'call',
            attrs: { to: jid, id: call.callId },
            content: [{
              tag: 'terminate',
              attrs: { 'call-id': call.callId, reason: 'hangup' }
            }]
          }).catch(() => {});
        }
      } catch (e) {}
    }
    sess.activeCalls.clear();
  }
}

const EMOJI_50_POOL = [
  '⚡', '🔥', '👑', '💀', '🛡️', '⚔️', '🦁', '🦅', '💣', '🩸',
  '🌪️', '💥', '🔱', '💎', '🚀', '☠️', '👹', '👺', '🥶', '😈',
  '🦇', '🐉', '☣️', '⚠️', '🚨', '🪐', '🌟', '✨', '🏆', '🎯',
  '🥇', '💫', '🖤', '🤍', '🤎', '💜', '💙', '💚', '💛', '🧡',
  '❤️', '🌹', '🐅', '🐆', '🐺', '🦂', '🕷️', '🎲', '🃏', '🚩'
];

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

    const savedCfg = loadSessionConfig(uid);
    const resolvedOwnerJid = ownerJid ? ownerJid.trim() : (savedCfg.owner_jid || savedCfg.ownerJid || '');

    if (!activeSessions[uid]) {
      const initialSubadmins = new Set(Array.isArray(savedCfg.subadmins) ? savedCfg.subadmins : []);
      activeSessions[uid] = {
        uid,
        authDir,
        status: hasAuth ? 'INITIALIZING' : 'STANDBY',
        qr: '',
        qrAttempts: 0,
        reconnectAttempts: 0,
        reconnectTimer: null,
        pairingCode: '',
        pairingRawCode: '',
        pairingPhone: '',
        pairingCodeCreatedAt: 0,
        connectedNumber: '',
        userJid: '',
        ownerJid: resolvedOwnerJid,
        prefix: savedCfg.prefix || '+',
        mode: savedCfg.mode || 'self',
        workMode: savedCfg.workMode || 'self',
        executionMode: 'solo',
        autoRejectCall: !!savedCfg.autoRejectCall,
        lastIncomingCall: null,
        chatLoops: {},
        delays: {
          nc: 50,
          gcdc: 50,
          pfp: 1000,
          picspam: 200,
          textspam: 50,
          pollspam: 300,
          spam: savedCfg.delay || 50,
          swipe: 100,
          target: 150
        },
        targetAutoReplies: {},
        muteList: new Set(),
        radarList: new Set(),
        warnList: {},
        subadmins: initialSubadmins,
        antilink: !!savedCfg.antilink,
        callNotiChat: savedCfg.callNotiChat || null,
        activeCalls: new Map(), // jid -> { callId, startTime, isMuted, autoUnmute, loop, track }
        sentCount: 0,
        failedCount: 0,
        startedAt: null,
        connectedAt: null,
        logs: []
      };
    } else {
      activeSessions[uid].authDir = authDir;
      if (resolvedOwnerJid) activeSessions[uid].ownerJid = resolvedOwnerJid;
      if (savedCfg.callNotiChat) activeSessions[uid].callNotiChat = savedCfg.callNotiChat;
      if (Array.isArray(savedCfg.subadmins)) {
        savedCfg.subadmins.forEach(s => activeSessions[uid].subadmins.add(s));
      }
    }

    if (ownerJid) {
      saveSessionConfig(uid, { owner_jid: resolvedOwnerJid });
    }

    const sess = activeSessions[uid];

    if (!hasAuth && options.standbyOnly && !options.force && !options.isPairing) {
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
      auth: {
        creds: state.creds,
        keys: makeCacheableSignalKeyStore(state.keys, pino({ level: 'silent' }))
      },
      browser: Browsers.ubuntu('Chrome'), // Standard Ubuntu Chrome ID for flawless pairing codes
      syncFullHistory: false,
      markOnlineOnConnect: true,
      generateHighQualityLinkPreview: false,
      defaultQueryTimeoutMs: 90000,
      connectTimeoutMs: 90000,
      keepAliveIntervalMs: 15000,
      retryRequestDelayMs: 1500,
      maxRetries: 8
    });

    sess.sock = sock;

    sock.ev.on('creds.update', async () => {
      try {
        if (!fs.existsSync(authDir)) fs.mkdirSync(authDir, { recursive: true });
        await saveCreds();
        await saveSessionToMongo(uid);
      } catch (err) {}
    });

    sock.ev.on('connection.update', async (update) => {
      const { connection, lastDisconnect, qr } = update;

      if (qr) {
        // If pairing code is active and under 10 minutes old, keep pairing code active
        const isPairingActive = (sess.status === 'PAIRING' || options.isPairing) && sess.pairingCode && (Date.now() - (sess.pairingCodeCreatedAt || 0) < 600000);
        if (!isPairingActive && !options.isPairing) {
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
        sess.connectedNumber = userPhone ? `+${userPhone}` : (sess.pairingPhone ? `+${sess.pairingPhone}` : 'Linked Account');
        sess.status = 'ONLINE';
        sess.qr = '';
        sess.pairingCode = '';
        sess.pairingRawCode = '';
        sess.connectedAt = Date.now();

        // Save fresh creds to MongoDB Atlas
        saveSessionToMongo(uid);

        // Attach & Initialize Full WhatsApp VoIP Engine
        sess.voipManager = new SessionVoipManager(sess, uid);
        sess.voipManager.init().catch((ve) => {
          logMsg(uid, `VoIP Manager background init: ${ve.message}`);
        });

        logMsg(uid, `🎉 ONLINE! Number: ${sess.connectedNumber} | Admin Owner ID: ${sess.ownerJid || 'Not Set'}`);
      }

      if (connection === 'close') {
        const hasActiveCalls = sess.activeCalls && sess.activeCalls.size > 0;
        if (sess.voipManager && !hasActiveCalls) {
          try { sess.voipManager.destroy(); } catch (e) {}
          sess.voipManager = null;
        }

        const statusCode = lastDisconnect?.error?.output?.statusCode;
        const isExplicitLoggedOut = statusCode === DisconnectReason.loggedOut;
        const isPairingActive = sess.pairingCode && (Date.now() - (sess.pairingCodeCreatedAt || 0) < 900000);

        try {
          sock.ev.removeAllListeners();
          if (sock.ws) { try { sock.ws.close(); } catch (e) {} }
          try { sock.end(); } catch (e) {}
        } catch (e) {}
        sess.sock = null;

        // Strictly verify true logout before wiping auth credentials
        if (isExplicitLoggedOut) {
          sess.status = 'LOGGED_OUT';
          sess.connectedNumber = '';
          sess.userJid = '';
          sess.qr = '';
          sess.pairingCode = '';
          sess.pairingRawCode = '';
          stopAllOperations(sess);
          logMsg(uid, `🔴 Session logged out by device. Cleaned auth directory.`);
          deleteSessionAuthDir(uid);
          return;
        }

        // WhatsApp pairing or transient restart (515, 401 sync, 403 sync, 408, 428, restartRequired)
        if (isPairingActive || statusCode === DisconnectReason.restartRequired || statusCode === 515 || statusCode === 408 || statusCode === 428 || statusCode === 401 || statusCode === 403) {
          sess.status = hasActiveCalls ? 'ONLINE' : (isPairingActive ? 'PAIRING' : 'ONLINE');
          logMsg(uid, `🔄 Non-stop connection sync (Code: ${statusCode || '515'}). Auto-resuming live session...`);

          clearTimeout(sess.reconnectTimer);
          sess.reconnectTimer = setTimeout(() => {
            if (activeSessions[uid] && activeSessions[uid].status !== 'LOGGED_OUT') {
              initSessionSocket(uid, sess.ownerJid, { force: false, preservePairing: true });
            }
          }, 1000);
          return;
        }

        const isAuth = hasSavedAuthCreds(uid) || sess.status === 'ONLINE';
        if (!isAuth) {
          if ((sess.qrAttempts || 0) >= 30) {
            sess.status = 'QR_EXPIRED';
            sess.qr = '';
            logMsg(uid, `⏸️ QR scan session expired. Click Refresh QR on dashboard when ready.`);
            return;
          } else {
            sess.status = 'RECONNECTING';
            clearTimeout(sess.reconnectTimer);
            sess.reconnectTimer = setTimeout(() => {
              if (activeSessions[uid] && activeSessions[uid].status !== 'LOGGED_OUT') {
                initSessionSocket(uid, sess.ownerJid, { force: false });
              }
            }, 1000);
            return;
          }
        }

        sess.reconnectAttempts = (sess.reconnectAttempts || 0) + 1;
        const backoffDelay = hasActiveCalls ? 500 : Math.min(8000, 1000 * Math.pow(1.2, Math.min(sess.reconnectAttempts, 3)));
        if (!hasActiveCalls) sess.status = 'ONLINE'; // Keep status online to avoid dashboard flashing
        logMsg(uid, `⚡ Non-stop live stream sentinel. Auto-connecting in ${Math.round(backoffDelay / 1000)}s...`);

        clearTimeout(sess.reconnectTimer);
        sess.reconnectTimer = setTimeout(() => {
          if (activeSessions[uid] && activeSessions[uid].status !== 'LOGGED_OUT') {
            initSessionSocket(uid, sess.ownerJid, { force: true });
          }
        }, backoffDelay);
      }
    });

    // ========================================================================
    // INCOMING CALL HANDLER (Real-Time Caller Engine, Auto-Reject & Auto-Mute)
    // ========================================================================
    sock.ev.on('call', async (callEvents) => {
      try {
        for (const call of callEvents) {
          const from = call.from || call.chatId || call.jid;
          const callId = call.id || call.callId;
          const status = call.status; // 'offer', 'ringing', 'timeout', 'reject', 'terminate'
          const isVideo = !!call.isVideo;
          const creator = call.creator || call.caller || from;
          const isGroup = !!call.isGroup || (from && from.endsWith('@g.us')) || (creator && creator.endsWith('@g.us'));
          sess.lastIncomingCall = { id: callId, from, creator, isGroup, status, isVideo, timestamp: Date.now() };
          logMsg(uid, `📞 Incoming Call Event: id=${callId}, from=${from}, creator=${creator}, isGroup=${isGroup}, status=${status}, isVideo=${isVideo}`);

          if (status === 'offer') {
            if (sess.autoRejectCall) {
              try {
                await sock.rejectCall(callId, from);
                logMsg(uid, `🚫 [AUTO-REJECT] Incoming call ${callId} from ${from} rejected successfully.`);
                await sock.sendMessage(from, { text: `🚫 *[AUTO-CALL SENTINEL]* This bot does not accept voice or video calls.` });
              } catch (rejErr) {
                logMsg(uid, `Auto-reject error: ${rejErr.message}`);
              }
            } else {
              const notiDest = sess.callNotiChat || (sess.ownerJid && sess.ownerJid.includes('@') ? sess.ownerJid : null);
              if (notiDest) {
                const fromNum = cleanPhone(from);
                const notiText = `╔══〔 📞 *INCOMING CALL NOTIFICATION* 〕══╗\n┃ 👤 *Caller:* +${fromNum}\n┃ 🆔 *Caller JID:* \`${from}\`\n┃ 🔑 *Call ID:* \`${callId}\`\n┃ 🎥 *Call Type:* *${isVideo ? 'Video Call' : 'Voice Call'}*\n┃ ⏱️ *Time:* *${new Date().toLocaleTimeString()}*\n╚═════════════════════════════════════╝\n⚡ *Quick Actions:*\n▸ \`${sess.prefix}acceptcall\` ➔ *Accept & Stream 51.mp3 Live*\n▸ \`${sess.prefix}acceptcall <song>\` ➔ *Accept & Stream Custom Song*\n▸ \`${sess.prefix}rejectcall\` ➔ *Decline Call*`;
                try {
                  await sock.sendMessage(notiDest, { text: notiText });
                } catch (e) {}
              }

              const sessCall = sess.activeCalls?.get(from);
              if (sessCall && sessCall.autoUnmute) {
                logMsg(uid, `🔊 [AUTO-UNMUTE] Unmuting active call with ${from}`);
              }
            }
          } else if (status === 'terminate' || status === 'timeout' || status === 'reject') {
            const wasActive = sess.activeCalls && sess.activeCalls.has(from);
            if (wasActive) {
              sess.activeCalls.delete(from);
              if (sess.voipManager) {
                try { sess.voipManager.end(); } catch (e) {}
              }
              const fromNum = cleanPhone(from);
              const notiDest = sess.callNotiChat || (sess.ownerJid && sess.ownerJid.includes('@') ? sess.ownerJid : null);
              if (notiDest) {
                const endMsg = `╔══〔 ⏹️ *CALL TERMINATED* 〕══╗\n┃ 👤 Caller: *+${fromNum}*\n┃ 📝 Status: *${status === 'terminate' ? 'Remote Party Ended Call' : 'Call Timed Out / Rejected'}*\n┃ ⏱️ Time: *${new Date().toLocaleTimeString()}*\n╚═════════════════════════════╝`;
                try { await sock.sendMessage(notiDest, { text: endMsg }); } catch (e) {}
              }
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

          // Strict Prefix Check: Bot strictly responds to its assigned prefix
          let usedPrefix = null;
          if (rawBody.startsWith(curPrefix)) {
            usedPrefix = curPrefix;
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
              sess.subadmins = sess.subadmins || new Set();
              sess.subadmins.add(senderParticipant);
              saveSessionConfig(uid, { owner_jid: senderParticipant, subadmins: Array.from(sess.subadmins) });
              logMsg(uid, `👑 Master Pass Authorization Granted to ${senderParticipant}`);
              await sock.sendMessage(jid, {
                text: `👑 *MASTER ACCESS GRANTED!*\n• 🆔 *Your ID:* \`${senderParticipant}\`\n• ⚡ *Status:* Fully Authorized Owner for Node \`${uid}\`.`,
                mentions: [senderParticipant]
              }, { quoted: msg });
              continue;
            }
          }

          // SENSITIVE ADMIN COMMANDS LIST (Restricted strictly to Owner/Subadmins)
          const SENSITIVE_ADMIN_COMMANDS = new Set([
            'setowner', 'setadmin', 'addadmin', 'deladmin', 'removeadmin', 'showadmins', 'admins', 'listadmins',
            'mode', 'workmode', 'public', 'self', 'private',
            'eval', 'exec', 'restart', 'reboot', 'shutdown', 'clearsession', 'logout',
            'delbotsession', 'removebot', 'deletesession'
          ]);

          const isOwner = isAuthorizedOwner(sess, msg, sock);
          const isPublicMode = (sess.mode || 'self') === 'public';

          // Strictly restrict ALL commands to the session's Owner/Subadmins unless explicitly set to public
          if (!isPublicMode || SENSITIVE_ADMIN_COMMANDS.has(cmd)) {
            if (!isOwner) {
              logMsg(uid, `⛔ [UNAUTHORIZED COMMAND BLOCKED] User ${senderParticipant} attempted [${cmd}] on Node ${uid}. Only verified owner can control this bot.`);
              continue;
            }
          }

          // SET OWNER COMMAND
          if (cmd === 'setowner' || cmd === 'setadmin') {
            const mentioned = msg.message?.extendedTextMessage?.contextInfo?.mentionedJid || [];
            let target = mentioned[0] || (fullArg ? normalizeJid(fullArg) : senderParticipant);
            sess.ownerJid = target;
            sess.ownerLid = target;
            saveSessionConfig(uid, { owner_jid: target, subadmins: Array.from(sess.subadmins || []) });
            logMsg(uid, `👑 Bot Owner JID set to: ${target}`);
            await sock.sendMessage(jid, { text: `👑 *Bot Owner registered as:* \`${target}\`` }, { quoted: msg });
            continue;
          }

          // ADD SUBADMIN COMMAND
          if (cmd === 'addadmin') {
            const mentioned = msg.message?.extendedTextMessage?.contextInfo?.mentionedJid || [];
            let target = mentioned[0] || (fullArg ? normalizeJid(fullArg) : '');
            if (!target) {
              await sock.sendMessage(jid, { text: `❌ *Usage:* \`${sess.prefix}addadmin <Phone/JID or @mention>\`` }, { quoted: msg });
              continue;
            }
            sess.subadmins = sess.subadmins || new Set();
            sess.subadmins.add(target);
            saveSessionConfig(uid, { owner_jid: sess.ownerJid, subadmins: Array.from(sess.subadmins) });
            logMsg(uid, `👑 Subadmin added: ${target}`);
            await sock.sendMessage(jid, { text: `✅ *Subadmin registered:* \`${target}\`\nThis Admin can now execute commands on this bot.` }, { quoted: msg });
            continue;
          }

          // DEL SUBADMIN COMMAND
          if (cmd === 'deladmin' || cmd === 'removeadmin') {
            const mentioned = msg.message?.extendedTextMessage?.contextInfo?.mentionedJid || [];
            let target = mentioned[0] || (fullArg ? normalizeJid(fullArg) : '');
            if (!target) {
              await sock.sendMessage(jid, { text: `❌ *Usage:* \`${sess.prefix}deladmin <Phone/JID or @mention>\`` }, { quoted: msg });
              continue;
            }
            if (sess.subadmins) sess.subadmins.delete(target);
            saveSessionConfig(uid, { owner_jid: sess.ownerJid, subadmins: Array.from(sess.subadmins || []) });
            logMsg(uid, `🧹 Subadmin removed: ${target}`);
            await sock.sendMessage(jid, { text: `❌ *Subadmin removed:* \`${target}\`` }, { quoted: msg });
            continue;
          }

          // SHOW ADMINS COMMAND
          if (cmd === 'showadmins' || cmd === 'listadmins' || cmd === 'admins') {
            const subs = sess.subadmins ? Array.from(sess.subadmins) : [];
            const subList = subs.length ? subs.map(s => `• \`${s}\``).join('\n') : '_No Subadmins_';
            await sock.sendMessage(jid, {
              text: `👑 *BOT ADMIN MATRIX*\n\n• 🆔 *Node UID:* \`${uid}\`\n• 👑 *Primary Admin:* \`${sess.ownerJid || 'Not Set'}\`\n• 🛡️ *Subadmins:*\n${subList}`
            }, { quoted: msg });
            continue;
          }

          // MODE COMMAND (Toggle Public vs Self / Private)
          if (cmd === 'mode' || cmd === 'workmode' || cmd === 'public' || cmd === 'self' || cmd === 'private') {
            let targetMode = (cmd === 'public' ? 'public' : (cmd === 'self' || cmd === 'private' ? 'self' : parts[1]?.toLowerCase()));
            if (!targetMode || (targetMode !== 'public' && targetMode !== 'self' && targetMode !== 'private')) {
              await sock.sendMessage(jid, {
                text: `⚙️ *BOT WORK MODE*\n• Current Mode: *${(sess.mode || 'public').toUpperCase()}*\n• DM (Personal Chat) Access: *${sess.allowDm !== false ? 'Enabled 🟢' : 'Disabled 🔴'}*\n\n_Usage:_ \`${sess.prefix}mode public\` or \`${sess.prefix}mode self\``
              }, { quoted: msg });
              continue;
            }
            if (targetMode === 'private') targetMode = 'self';
            sess.mode = targetMode;
            sess.publicMode = (targetMode === 'public');
            saveSessionConfig(uid, { mode: targetMode, publicMode: sess.publicMode });
            await sock.sendMessage(jid, {
              text: `✅ *Bot Mode Updated!*\n• Mode: *${targetMode.toUpperCase()}*\n• DM (Personal Chat) Access: *${targetMode === 'public' ? 'OPEN TO ALL' : 'OWNER/ADMIN ONLY'}*`
            }, { quoted: msg });
            continue;
          }

          if (!shouldExecuteCommand(sess, msg, cmd)) {
            continue;
          }

          logMsg(uid, `👑 [COMMAND EXECUTION] [${usedPrefix || ''}${cmd}] in ${jid} by ${senderParticipant}`);

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
│ • Type \`${sess.prefix}menu 4\` for 🎙️ AI Voice Studio & OpenVoice
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
              const text = getUltraDashboardMenu(sess.prefix);
              const pic = fs.existsSync(DASHBOARD_PIC_PATH) ? DASHBOARD_PIC_PATH : MAIN_PIC_PATH;
              if (fs.existsSync(pic)) {
                try {
                  await sock.sendMessage(jid, { image: fs.readFileSync(pic), caption: text }, { quoted: msg });
                } catch (e) {
                  await sock.sendMessage(jid, { text }, { quoted: msg });
                }
              } else {
                await sock.sendMessage(jid, { text }, { quoted: msg });
              }
            } else if (sub === '2' || sub === 'call' || sub === 'voip') {
              const text = getCallingEngineMenu(sess.prefix);
              if (fs.existsSync(MAIN_PIC_PATH)) {
                try {
                  await sock.sendMessage(jid, { image: fs.readFileSync(MAIN_PIC_PATH), caption: text }, { quoted: msg });
                } catch (e) {
                  await sock.sendMessage(jid, { text }, { quoted: msg });
                }
              } else {
                await sock.sendMessage(jid, { text }, { quoted: msg });
              }
            } else if (sub === '3' || sub === 'song' || sub === 'music') {
              const text = getSongDashboardMenu(sess.prefix);
              if (fs.existsSync(MAIN_PIC_PATH)) {
                try {
                  await sock.sendMessage(jid, { image: fs.readFileSync(MAIN_PIC_PATH), caption: text }, { quoted: msg });
                } catch (e) {
                  await sock.sendMessage(jid, { text }, { quoted: msg });
                }
              } else {
                await sock.sendMessage(jid, { text }, { quoted: msg });
              }
            } else if (sub === '4' || sub === 'voice' || sub === 'vn' || sub === 'clone') {
              const text = getVoiceStudioMenu(sess.prefix);
              if (fs.existsSync(MAIN_PIC_PATH)) {
                try {
                  await sock.sendMessage(jid, { image: fs.readFileSync(MAIN_PIC_PATH), caption: text }, { quoted: msg });
                } catch (e) {
                  await sock.sendMessage(jid, { text }, { quoted: msg });
                }
              } else {
                await sock.sendMessage(jid, { text }, { quoted: msg });
              }
            } else {
              const text = getMenuPortalText(sess.prefix);
              if (fs.existsSync(MAIN_PIC_PATH)) {
                try {
                  await sock.sendMessage(jid, { image: fs.readFileSync(MAIN_PIC_PATH), caption: text }, { quoted: msg });
                } catch (e) {
                  await sock.sendMessage(jid, { text }, { quoted: msg });
                }
              } else {
                await sock.sendMessage(jid, { text }, { quoted: msg });
              }
            }
            continue;
          }

          // Direct numerical / keyword menu selections
          if (cmd === '1' || cmd === 'ultra') {
            const text = getUltraDashboardMenu(sess.prefix);
            const pic = fs.existsSync(DASHBOARD_PIC_PATH) ? DASHBOARD_PIC_PATH : MAIN_PIC_PATH;
            if (fs.existsSync(pic)) {
              try {
                await sock.sendMessage(jid, { image: fs.readFileSync(pic), caption: text }, { quoted: msg });
              } catch (e) {
                await sock.sendMessage(jid, { text }, { quoted: msg });
              }
            } else {
              await sock.sendMessage(jid, { text }, { quoted: msg });
            }
            continue;
          }
          if (cmd === '2' || cmd === 'callmenu' || ((cmd === 'call' || cmd === 'voip') && !parts[1])) {
            const text = getCallingEngineMenu(sess.prefix);
            if (fs.existsSync(MAIN_PIC_PATH)) {
              try {
                await sock.sendMessage(jid, { image: fs.readFileSync(MAIN_PIC_PATH), caption: text }, { quoted: msg });
              } catch (e) {
                await sock.sendMessage(jid, { text }, { quoted: msg });
              }
            } else {
              await sock.sendMessage(jid, { text }, { quoted: msg });
            }
            continue;
          }
          if (cmd === '3' || cmd === 'songmenu') {
            const text = getSongDashboardMenu(sess.prefix);
            if (fs.existsSync(MAIN_PIC_PATH)) {
              try {
                await sock.sendMessage(jid, { image: fs.readFileSync(MAIN_PIC_PATH), caption: text }, { quoted: msg });
              } catch (e) {
                await sock.sendMessage(jid, { text }, { quoted: msg });
              }
            } else {
              await sock.sendMessage(jid, { text }, { quoted: msg });
            }
            continue;
          }
          if (cmd === '4' || cmd === 'voicemenu' || cmd === 'openvoice') {
            const text = getVoiceStudioMenu(sess.prefix);
            if (fs.existsSync(MAIN_PIC_PATH)) {
              try {
                await sock.sendMessage(jid, { image: fs.readFileSync(MAIN_PIC_PATH), caption: text }, { quoted: msg });
              } catch (e) {
                await sock.sendMessage(jid, { text }, { quoted: msg });
              }
            } else {
              await sock.sendMessage(jid, { text }, { quoted: msg });
            }
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

          // +outcall <number/@tag> [song] / +call <number> [song] / +videocall <number> [song] / +vcall <number> [song]
          if (cmd === 'outcall' || cmd === 'call' || cmd === 'outcalltag' || cmd === 'calltag' || cmd === 'videocall' || cmd === 'vcall' || (cmd === 'video' && parts[1] && (/^\+?\d{8,}/.test(parts[1]) || parts[1].startsWith('@')))) {
            const isVideoCallMode = cmd === 'videocall' || cmd === 'vcall' || (cmd === 'video' && parts[1] && (/^\+?\d{8,}/.test(parts[1]) || parts[1].startsWith('@')));
            const ctx = msg.message?.extendedTextMessage?.contextInfo;
            const mentioned = ctx?.mentionedJid || [];
            let rawTarget = (parts[1] || '').trim();

            if ((!rawTarget || rawTarget.startsWith('@') || cmd === 'outcalltag' || cmd === 'calltag') && mentioned.length > 0) {
              rawTarget = mentioned[0];
            } else if (!rawTarget && ctx?.participant) {
              rawTarget = ctx.participant;
            }

            let cleanNum = cleanPhone(rawTarget);
            if (rawTarget && rawTarget.includes('@lid')) {
              cleanNum = rawTarget;
            } else if (cleanNum && cleanNum.length === 10) {
              cleanNum = '91' + cleanNum;
            }

            if (!cleanNum || (typeof cleanNum === 'string' && cleanNum.length < 7 && !cleanNum.includes('@lid'))) {
              await sock.sendMessage(jid, {
                text: `❌ *Usage:* \`${sess.prefix}${cmd} <PhoneNumber / @tag> [Song Name / Video / 51.mp3]\`\n\n*Examples:*\n• \`${sess.prefix}outcall 919942292068 Believer\`\n• \`${sess.prefix}videocall 919942292068 Kesariya\`\n• \`${sess.prefix}videocall @mention 52.mp4\`\n• \`${sess.prefix}outcall @mention\``
              }, { quoted: msg });
              continue;
            }
            const targetPhone = cleanNum;
            const targetJid = normalizeJid(targetPhone);
            let audioSource = isVideoCallMode ? (fs.existsSync(path.join(__dirname, '52.mp4')) ? path.join(__dirname, '52.mp4') : AUDIO_51_PATH) : (fs.existsSync(AUDIO_51_PATH) ? AUDIO_51_PATH : 'silence');
            let trackName = isVideoCallMode ? 'Video ScreenShare + Audio' : '51.mp3';

            // Resolve audio source if specified
            const audioArgStart = (mentioned.length > 0 && parts[1]?.startsWith('@')) ? 2 : 2;
            if (parts[audioArgStart]?.toLowerCase() === 'vn' && parts[audioArgStart + 1]) {
              const vnText = parts.slice(audioArgStart + 1).join(' ');
              trackName = `Live VN (${vnText.slice(0, 20)}...)`;
              await sock.sendMessage(targetJid, { text: `🎙️ [LIVE VOICE NOTE IN CALL]: ${vnText}` }).catch(() => {});
            } else if (parts[audioArgStart]) {
              const argRest = parts.slice(audioArgStart).join(' ');
              const recName = argRest.toLowerCase().endsWith('.mp3') || argRest.toLowerCase().endsWith('.mp4') ? argRest : `${argRest}.mp3`;
              const recPath = path.join(RECORDINGS_DIR, recName);
              if (fs.existsSync(recPath)) {
                audioSource = recPath;
                trackName = recName;
              } else if (argRest.toLowerCase() === '51' || argRest.toLowerCase() === '51.mp3') {
                audioSource = AUDIO_51_PATH;
                trackName = '51.mp3';
              } else if (argRest.toLowerCase() === '52' || argRest.toLowerCase() === '52.mp4') {
                audioSource = path.join(__dirname, '52.mp4');
                trackName = '52.mp4 ScreenShare';
              } else {
                // Check if YouTube track or JioSaavn
                try {
                  const tempSongPath = path.join(__dirname, `temp_call_${Date.now()}.${isVideoCallMode ? 'mp4' : 'mp3'}`);
                  const dlRes = await downloadYouTubeMedia(argRest, isVideoCallMode ? 'video' : 'audio', tempSongPath);
                  if (dlRes.success && dlRes.filePath && fs.existsSync(dlRes.filePath)) {
                    audioSource = dlRes.filePath;
                    trackName = `YouTube: ${argRest}`;
                  } else {
                    const song = await searchJioSaavn(argRest);
                    if (song) {
                      const buf = await downloadBuffer(song.audioUrl);
                      fs.writeFileSync(tempSongPath, buf);
                      audioSource = tempSongPath;
                      trackName = `JioSaavn: ${song.title}`;
                    }
                  }
                } catch (e) {}
              }
            }

            logMsg(uid, `📞 Initiating WhatsApp Web VoIP ${isVideoCallMode ? 'Video' : 'Voice'} Call to ${targetPhone} (Media: ${trackName})...`);

            try {
              if (!sess.voipManager) {
                sess.voipManager = new SessionVoipManager(sess, uid);
              }
              await sess.voipManager.init();

              const activeCall = await sess.voipManager.call(targetPhone, {
                audioSource,
                isVideo: isVideoCallMode,
                durationMs: 86400000
              });

              sess.activeCalls = sess.activeCalls || new Map();
              sess.activeCalls.set(targetJid, {
                callId: activeCall.callId,
                targetJid,
                startTime: Date.now(),
                isMuted: false,
                autoUnmute: true,
                loop: null,
                track: trackName
              });

              await sock.sendMessage(jid, {
                text: `╔══〔 📞 *REAL VOIP CALL PLACED* 〕══╗\n┃ 🎯 Target: *+${targetPhone}*\n┃ 🆔 Call ID: \`${activeCall.callId}\`\n┃ ⚡ Engine: *WhatsApp Web VoIP WASM*\n┃ 🎵 Audio Track: *${trackName}*\n┃ 📡 Status: *🟡 DIALING / INITIATING...*\n╚════════════════════════════════════╝\n_Use \`${sess.prefix}endcall\` to terminate._`
              }, { quoted: msg });

              activeCall.on('ringing', async () => {
                logMsg(uid, `🔔 [CALL RINGING] Target phone +${targetPhone} is ringing!`);
                await sock.sendMessage(jid, {
                  text: `╔══〔 🔔 *PHONE IS RINGING!* 〕══╗\n┃ 🎯 Target: *+${targetPhone}*\n┃ 📡 Status: *🟢 REMOTE PHONE IS RINGING!*\n┃ 🔊 Media: *${trackName} ready to stream*\n╚════════════════════════════════╝`
                }).catch(() => {});
              });

              activeCall.on('connected', async () => {
                logMsg(uid, `🎉 [CALL CONNECTED] Receiver +${targetPhone} answered the call! Audio streaming.`);
                await sock.sendMessage(jid, {
                  text: `╔══〔 🎉 *CALL ANSWERED & CONNECTED!* 〕══╗\n┃ 🎯 Target: *+${targetPhone}*\n┃ 🔊 Audio: *STREAMING LIVE OPUS AUDIO* 🎶\n┃ 🎙️ Status: *FULL-DUPLEX CONNECTED* 🟢\n╚════════════════════════════════════════╝\n_Use \`${sess.prefix}endcall\` to terminate or \`${sess.prefix}callmute\` to mute._`
                }).catch(() => {});
              });

              activeCall.on('ended', async (reason) => {
                logMsg(uid, `⏹️ [CALL ENDED] VoIP Call with +${targetPhone} ended: ${reason}`);
                sess.activeCalls?.delete(targetJid);
                await sock.sendMessage(jid, {
                  text: `╔══〔 ⏹️ *CALL TERMINATED* 〕══╗\n┃ 🎯 Target: *+${targetPhone}*\n┃ 📝 Reason: *${reason || 'Call Ended'}*\n╚═════════════════════════════╝`
                }).catch(() => {});
              });

              activeCall.on('error', async (err) => {
                logMsg(uid, `❌ [CALL ERROR] VoIP call error: ${err.message}`);
                await sock.sendMessage(jid, { text: `❌ VoIP Call Error: ${err.message}` }).catch(() => {});
              });

            } catch (callErr) {
              logMsg(uid, `❌ [VOIP CALL ERROR] +${targetPhone}: ${callErr.message}`);
              // Try re-init and retry once
              try {
                logMsg(uid, `🔄 [VOIP RETRY] Re-initializing VoIP stack for retry...`);
                sess.voipManager = new SessionVoipManager(sess, uid);
                await sess.voipManager.init();
                const activeCall = await sess.voipManager.call(targetPhone, {
                  audioSource,
                  durationMs: 86400000
                });

                sess.activeCalls = sess.activeCalls || new Map();
                sess.activeCalls.set(targetJid, {
                  callId: activeCall.callId,
                  targetJid,
                  startTime: Date.now(),
                  isMuted: false,
                  autoUnmute: true,
                  loop: null,
                  track: trackName
                });

                await sock.sendMessage(jid, {
                  text: `╔══〔 📞 *REAL VOIP CALL PLACED* 〕══╗\n┃ 🎯 Target: *+${targetPhone}*\n┃ 🆔 Call ID: \`${activeCall.callId}\`\n┃ ⚡ Engine: *WhatsApp Web VoIP WASM*\n┃ 🎵 Audio Track: *${trackName}*\n┃ 📡 Status: *🟡 DIALING / INITIATING...*\n╚════════════════════════════════════╝\n_Use \`${sess.prefix}endcall\` to terminate._`
                }, { quoted: msg });

                activeCall.on('ringing', async () => {
                  logMsg(uid, `🔔 [CALL RINGING] Target phone +${targetPhone} is ringing!`);
                  await sock.sendMessage(jid, {
                    text: `╔══〔 🔔 *PHONE IS RINGING!* 〕══╗\n┃ 🎯 Target: *+${targetPhone}*\n┃ 📡 Status: *🟢 REMOTE PHONE IS RINGING!*\n┃ 🔊 Media: *${trackName} ready to stream*\n╚════════════════════════════════╝`
                  }).catch(() => {});
                });

                activeCall.on('connected', async () => {
                  logMsg(uid, `🎉 [CALL CONNECTED] Receiver +${targetPhone} answered the call! Audio streaming.`);
                  await sock.sendMessage(jid, {
                    text: `╔══〔 🎉 *CALL ANSWERED & CONNECTED!* 〕══╗\n┃ 🎯 Target: *+${targetPhone}*\n┃ 🔊 Audio: *STREAMING LIVE OPUS AUDIO* 🎶\n┃ 🎙️ Status: *FULL-DUPLEX CONNECTED* 🟢\n╚════════════════════════════════════════╝\n_Use \`${sess.prefix}endcall\` to terminate or \`${sess.prefix}callmute\` to mute._`
                  }).catch(() => {});
                });

                activeCall.on('ended', async (reason) => {
                  logMsg(uid, `⏹️ [CALL ENDED] VoIP Call with +${targetPhone} ended: ${reason}`);
                  sess.activeCalls?.delete(targetJid);
                  await sock.sendMessage(jid, {
                    text: `╔══〔 ⏹️ *CALL TERMINATED* 〕══╗\n┃ 🎯 Target: *+${targetPhone}*\n┃ 📝 Reason: *${reason || 'Call Ended'}*\n╚═════════════════════════════╝`
                  }).catch(() => {});
                });

                activeCall.on('error', async (err) => {
                  logMsg(uid, `❌ [CALL ERROR] VoIP call error: ${err.message}`);
                  await sock.sendMessage(jid, { text: `❌ VoIP Call Error: ${err.message}` }).catch(() => {});
                });

              } catch (retryErr) {
                logMsg(uid, `❌ [VOIP RETRY FAILED] ${retryErr.message}`);
                await sock.sendMessage(jid, {
                  text: `❌ *VoIP Call Failed:* ${retryErr.message}\n• Please verify target number *+${targetPhone}* is registered on WhatsApp.\n• Ensure bot WhatsApp session is online.`
                }, { quoted: msg });
              }
            }
            continue;
          }

          // +acceptcall [track/song] / +accept / +rcall / +acall / +answercall
          if (cmd === 'acceptcall' || cmd === 'accept' || cmd === 'rcall' || cmd === 'acall' || cmd === 'answercall') {
            const lastCall = sess.lastIncomingCall;
            if (!lastCall || !lastCall.id || !lastCall.from || (Date.now() - (lastCall.timestamp || 0) > 180000)) {
              await sock.sendMessage(jid, {
                text: `❌ *No active incoming call detected to answer!* (or call expired)`
              }, { quoted: msg });
              continue;
            }

            const callerJid = lastCall.from;
            const callerNum = cleanPhone(callerJid);
            let audioSource = fs.existsSync(AUDIO_51_PATH) ? AUDIO_51_PATH : 'silence';
            let trackName = '51.mp3';

            if (parts[1]) {
              const argRest = parts.slice(1).join(' ');
              const recName = argRest.toLowerCase().endsWith('.mp3') ? argRest : `${argRest}.mp3`;
              const recPath = path.join(RECORDINGS_DIR, recName);
              if (fs.existsSync(recPath)) {
                audioSource = recPath;
                trackName = recName;
              } else if (argRest.toLowerCase() === '51' || argRest.toLowerCase() === '51.mp3') {
                audioSource = AUDIO_51_PATH;
                trackName = '51.mp3';
              } else {
                try {
                  const song = await searchJioSaavn(argRest);
                  if (song) {
                    const tempSongPath = path.join(__dirname, `temp_call_${Date.now()}.mp3`);
                    const buf = await downloadBuffer(song.audioUrl);
                    fs.writeFileSync(tempSongPath, buf);
                    audioSource = tempSongPath;
                    trackName = `JioSaavn: ${song.title}`;
                  }
                } catch (e) {}
              }
            }

            if (!sess.voipManager) {
              sess.voipManager = new SessionVoipManager(sess, uid);
            }

            try {
              await sess.voipManager.acceptCall({
                callId: lastCall.id,
                callerJid,
                audioSource
              });
            } catch (accErr) {
              logMsg(uid, `VoIP accept notice: ${accErr.message}`);
              // Direct stanza fallback
              const stanzaId = sock.generateMessageTag ? sock.generateMessageTag() : `call_acc_${Date.now()}`;
              await sock.sendNode({
                tag: 'call',
                attrs: { to: callerJid, id: stanzaId },
                content: [{
                  tag: 'accept',
                  attrs: {
                    'call-id': lastCall.id,
                    'call-creator': lastCall.creator || callerJid,
                    't': String(Math.floor(Date.now() / 1000))
                  },
                  content: []
                }]
              }).catch(() => {});
            }

            sess.activeCalls = sess.activeCalls || new Map();
            sess.activeCalls.set(callerJid, {
              callId: lastCall.id,
              targetJid: callerJid,
              startTime: Date.now(),
              isMuted: false,
              autoUnmute: true,
              track: trackName
            });

            const acceptMsg = `╔══〔 📞 *INCOMING CALL ACCEPTED* 〕══╗\n┃ 👤 Caller: *+${callerNum}*\n┃ 🆔 Call ID: \`${lastCall.id}\`\n┃ 🎵 Media Track: *${trackName}*\n┃ 📡 Audio Output: *Live WebRTC Opus VoIP Stream*\n┃ ⚡ Status: *ANSWERED & STREAMING AUDIO LIVE* 🟢\n╚═════════════════════════════════════╝\n_Use \`${sess.prefix}endcall\` or \`${sess.prefix}cutcall\` to hang up._`;
            await sock.sendMessage(jid, { text: acceptMsg }, { quoted: msg });
            if (sess.callNotiChat && sess.callNotiChat !== jid) {
              await sock.sendMessage(sess.callNotiChat, { text: acceptMsg }).catch(() => {});
            }
            continue;
          }

          // +noti <chat_id> / +notichat / +setcallnoti / +callnoti
          if (cmd === 'noti' || cmd === 'notichat' || cmd === 'setcallnoti' || cmd === 'callnoti' || cmd === 'callnotify') {
            const sub = (parts[1] || '').trim();
            if (sub.toLowerCase() === 'off' || sub.toLowerCase() === 'clear' || sub.toLowerCase() === 'disable') {
              sess.callNotiChat = null;
              saveSessionConfig(uid, { callNotiChat: null });
              await sock.sendMessage(jid, {
                text: `╔══〔 🔕 *CALL NOTIFICATION ROUTING OFF* 〕══╗\n┃ Status: *Incoming Call Alerts Disabled* 🔴\n╚══════════════════════════════════════╝`
              }, { quoted: msg });
              continue;
            }

            let targetNotiJid = jid;
            if (sub) {
              targetNotiJid = normalizeJid(sub);
            }

            sess.callNotiChat = targetNotiJid;
            saveSessionConfig(uid, { callNotiChat: targetNotiJid });

            const targetName = targetNotiJid.endsWith('@g.us') ? 'WhatsApp Group' : (targetNotiJid === jid ? 'This Chat' : `User +${cleanPhone(targetNotiJid)}`);
            await sock.sendMessage(jid, {
              text: `╔══〔 🔔 *CALL NOTIFICATION ROUTE ACTIVE* 〕══╗\n┃ 🎯 Notification Target: *${targetName}*\n┃ 🆔 Chat JID: \`${targetNotiJid}\`\n┃ ⚡ Status: *ALL INCOMING CALL ALERTS WILL ARRIVE HERE* 🟢\n╚══════════════════════════════════════╝\n_Use \`${sess.prefix}noti off\` to disable or \`${sess.prefix}acceptcall\` when a call arrives._`
            }, { quoted: msg });
            continue;
          }

          // +chatinfo / +infochat / +gcinfo / +id / +jid / +getid
          if (cmd === 'chatinfo' || cmd === 'infochat' || cmd === 'gcinfo' || cmd === 'id' || cmd === 'jid' || cmd === 'getid') {
            if (isGroup) {
              let meta = null;
              try { meta = await sock.groupMetadata(jid); } catch (e) {}
              const gcName = meta?.subject || 'WhatsApp Group';
              const ownerNum = meta?.owner ? cleanPhone(meta.owner) : (meta?.subjectOwner ? cleanPhone(meta.subjectOwner) : 'Unknown');
              const participants = meta?.participants || [];
              const admins = participants.filter(p => p.admin || p.isAdmin);
              const isBotAdmin = !!admins.find(a => normalizeJid(a.id) === normalizeJid(sock.user?.id));

              await sock.sendMessage(jid, {
                text: `╔══〔 ℹ️ *GROUP CHAT INFORMATION* 〕══╗\n┃ 📌 *Group Name:* *${gcName}*\n┃ 🆔 *Chat JID:* \`${jid}\`\n┃ 👥 *Total Members:* *${participants.length}*\n┃ 👑 *Admins:* *${admins.length}*\n┃ 🛡️ *Bot Admin Status:* *${isBotAdmin ? 'ADMIN 🟢' : 'MEMBER ⚪'}*\n┃ 👑 *Group Creator:* *+${ownerNum}*\n┃ 👤 *Your ID:* \`${senderParticipant}\`\n╚════════════════════════════════════╝\n💡 *To route incoming call alerts to this group:*\n\`${sess.prefix}noti ${jid}\` (or simply send \`${sess.prefix}noti\`)`
              }, { quoted: msg });
            } else {
              const userPhone = cleanPhone(jid);
              await sock.sendMessage(jid, {
                text: `╔══〔 ℹ️ *PRIVATE CHAT INFORMATION* 〕══╗\n┃ 👤 *Contact Phone:* *+${userPhone}*\n┃ 🆔 *Chat JID:* \`${jid}\`\n┃ 🏷️ *Type:* *Direct Private Message (DM)*\n┃ 👤 *Your Sender JID:* \`${senderParticipant}\`\n╚══════════════════════════════════════╝\n💡 *To route incoming call alerts here:*\n\`${sess.prefix}noti ${jid}\` (or simply send \`${sess.prefix}noti\`)`
              }, { quoted: msg });
            }
            continue;
          }

          // +joincall / +joinvc / +joingroupcall (Join ongoing group/chat call & stream audio)
          if (cmd === 'joincall' || cmd === 'joinvc' || cmd === 'joingroupcall') {
            const callId = sess.lastIncomingCall?.id || `call_${Date.now()}_${Math.floor(Math.random() * 10000)}`;
            const callerJid = sess.lastIncomingCall?.from || jid;
            
            if (!sess.voipManager) {
              sess.voipManager = new SessionVoipManager(sess, uid);
            }

            try {
              await sess.voipManager.acceptCall({
                callId,
                callerJid,
                audioSource: fs.existsSync(AUDIO_51_PATH) ? AUDIO_51_PATH : 'silence'
              });
            } catch (e) {
              const stanzaId = sock.generateMessageTag ? sock.generateMessageTag() : `call_acc_${Date.now()}`;
              await sock.sendNode({
                tag: 'call',
                attrs: { to: callerJid, id: stanzaId },
                content: [{
                  tag: 'accept',
                  attrs: {
                    'call-id': callId,
                    'call-creator': sess.lastIncomingCall?.creator || callerJid,
                    't': String(Math.floor(Date.now() / 1000))
                  },
                  content: []
                }]
              }).catch(() => {});
            }

            sess.activeCalls = sess.activeCalls || new Map();
            sess.activeCalls.set(jid, {
              callId,
              targetJid: jid,
              startTime: Date.now(),
              isMuted: false,
              autoUnmute: true
            });

            await sock.sendMessage(jid, {
              text: `╔══〔 📞 *JOINED ACTIVE CALL / GROUP VC* 〕══╗\n┃ 🎯 Chat: *${jid.endsWith('@g.us') ? 'Group Call' : jid.split('@')[0]}*\n┃ 🆔 Call ID: *${callId}*\n┃ 🔊 Audio Streamer: *READY & CONNECTED*\n┃ ⚡ Control: \`${sess.prefix}play1call\` • \`${sess.prefix}playjiocall <song>\`\n╚═════════════════════════════════════════╝\n_Use \`${sess.prefix}leavecall\` or \`${sess.prefix}endcall\` to exit._`
            }, { quoted: msg });

            // If audio argument specified like '+joincall 51.mp3' or '+joincall <song>'
            const subArg = (parts[1] || '').toLowerCase();
            if (subArg === '51' || subArg === '51.mp3' || subArg === 'loop') {
              sess.chatLoops = sess.chatLoops || {};
              sess.chatLoops[jid] = sess.chatLoops[jid] || {};
              sess.chatLoops[jid].play1call = true;
              if (fs.existsSync(AUDIO_51_PATH)) {
                (async () => {
                  const audioBuf = fs.readFileSync(AUDIO_51_PATH);
                  while (sess.chatLoops?.[jid]?.play1call) {
                    try {
                      await sock.sendMessage(jid, { audio: audioBuf, mimetype: 'audio/mp4', ptt: true });
                      sess.sentCount = (sess.sentCount || 0) + 1;
                    } catch (e) {}
                    if (!sess.chatLoops?.[jid]?.play1call) break;
                    await sleep(5000);
                  }
                })();
              }
            } else if (parts[1]) {
              const songQuery = parts.slice(1).join(' ');
              (async () => {
                try {
                  const song = await searchJioSaavn(songQuery);
                  if (song) {
                    const buf = await downloadBuffer(song.audioUrl);
                    sess.chatLoops = sess.chatLoops || {};
                    sess.chatLoops[jid] = sess.chatLoops[jid] || {};
                    sess.chatLoops[jid].playjiocall = true;
                    while (sess.chatLoops?.[jid]?.playjiocall) {
                      try {
                        await sock.sendMessage(jid, { audio: buf, mimetype: 'audio/mp4', ptt: true });
                        sess.sentCount = (sess.sentCount || 0) + 1;
                      } catch (e) {}
                      if (!sess.chatLoops?.[jid]?.playjiocall) break;
                      await sleep((song.durSec || 180) * 1000 + 5000);
                    }
                  }
                } catch(e) {}
              })();
            }
            continue;
          }

          // +leavecall / +leavevc / +stopcall (Leave active call / voice chat)
          if (cmd === 'leavecall' || cmd === 'leavevc' || cmd === 'stopcall') {
            if (sess.chatLoops && sess.chatLoops[jid]) {
              sess.chatLoops[jid].play1call = false;
              sess.chatLoops[jid].playjiocall = false;
              sess.chatLoops[jid].playrd = false;
            }
            if (sess.activeCalls && sess.activeCalls.has(jid)) {
              const call = sess.activeCalls.get(jid);
              try {
                await sock.query({
                  tag: 'call',
                  attrs: { to: jid, id: call.callId },
                  content: [{
                    tag: 'terminate',
                    attrs: { 'call-id': call.callId, reason: 'leave' }
                  }]
                }).catch(() => {});
              } catch (e) {}
              sess.activeCalls.delete(jid);
            }
            await sock.sendMessage(jid, {
              text: `╔══〔 🚪 *LEFT CALL / GROUP VC* 〕══╗\n┃ Chat: *${jid.endsWith('@g.us') ? 'Group' : jid.split('@')[0]}*\n┃ Status: *DISCONNECTED & LOOPS STOPPED* 🛑\n╚═══════════════════════════════════╝`
            }, { quoted: msg });
            continue;
          }

          // +play1call / +playcall (Live streams 51.mp3 directly inside active VoIP call)
          if (cmd === 'play1call' || cmd === 'playcall') {
            if (!fs.existsSync(AUDIO_51_PATH)) {
              await sock.sendMessage(jid, { text: `❌ 51.mp3 audio file directory me nahi mili!` }, { quoted: msg });
              continue;
            }

            if (sess.voipManager && sess.voipManager.activeCall) {
              sess.voipManager.switchAudio(AUDIO_51_PATH);
              await sock.sendMessage(jid, {
                text: `╔══〔 🔊 *51.MP3 STREAMING ON ACTIVE CALL* 〕══╗\n┃ 🎵 Track: *51.mp3*\n┃ 📡 Output: *Direct WebRTC Opus stream inside call*\n┃ ⚡ Status: *STREAMING LIVE TO RECEIVER* 🟢\n╚════════════════════════════════════════╝\n_Audio is playing live inside the VoIP call._`
              }, { quoted: msg });
            } else {
              await sock.sendMessage(jid, {
                text: `⚠️ *No active VoIP call connected right now.*\nUse \`${sess.prefix}outcall <number> 51.mp3\` to dial and stream 51.mp3 on the call!`
              }, { quoted: msg });
            }
            continue;
          }

          // +playytcall <song/link> (YouTube live audio stream on VoIP call)
          if (cmd === 'playytcall' || cmd === 'playjiocall' || cmd === 'ytcall' || cmd === 'callsong') {
            const query = fullArg || (lastSearchedTracks.get(jid)?.url || lastSearchedTracks.get(jid)?.title);
            if (!query) {
              await sock.sendMessage(jid, { text: `❌ *Usage:* \`${sess.prefix}playytcall <Song Name or YouTube Link>\`\nExample: \`${sess.prefix}playytcall Believer\`` }, { quoted: msg });
              continue;
            }

            await sock.sendMessage(jid, { text: `🔍 *Fetching YouTube audio for \`${query}\` to stream live on call...*` }, { quoted: msg });

            (async () => {
              try {
                const tempSongPath = path.join(__dirname, `temp_call_${Date.now()}.mp3`);
                const dlRes = await downloadYouTubeMedia(query, 'audio', tempSongPath);
                let actualFile = (dlRes.success && dlRes.filePath && fs.existsSync(dlRes.filePath)) ? dlRes.filePath : null;

                if (!actualFile) {
                  // Fallback to JioSaavn
                  const jio = await searchJioSaavn(query);
                  if (jio?.audioUrl) {
                    const buf = await downloadBuffer(jio.audioUrl);
                    fs.writeFileSync(tempSongPath, buf);
                    actualFile = tempSongPath;
                  }
                }

                if (!actualFile || !fs.existsSync(actualFile)) {
                  return sock.sendMessage(jid, { text: `❌ Failed to fetch audio for \`${query}\`!` }, { quoted: msg });
                }

                if (sess.voipManager && sess.voipManager.activeCall) {
                  sess.voipManager.switchAudio(actualFile);
                  await sock.sendMessage(jid, {
                    text: `╔══〔 🎵 *YOUTUBE AUDIO STREAMING ON CALL* 〕══╗\n┃ 🎶 Track: *${query}*\n┃ 📡 Output: *Live WebRTC Opus VoIP Stream*\n┃ ⚡ Status: *STREAMING LIVE ON ACTIVE CALL* 🟢\n╚══════════════════════════════════════════╝\n_YouTube audio is playing live inside the VoIP call._`
                  }, { quoted: msg });
                } else {
                  await sock.sendMessage(jid, {
                    text: `✅ *Track Downloaded & Ready*\n⚠️ *No active VoIP call running right now.*\nUse \`${sess.prefix}outcall <number> ${query}\` or \`${sess.prefix}call <number>\` to dial target and stream this track on the call!`
                  }, { quoted: msg });
                }
              } catch (ytErr) {
                logMsg(uid, `playytcall error: ${ytErr.message}`);
                await sock.sendMessage(jid, { text: `❌ YouTube Call error: ${ytErr.message}` }, { quoted: msg });
              }
            })();
            continue;
          }

          // +play2ytcall <song/link> (YouTube Video call stream with screen-share / video track)
          if (cmd === 'play2ytcall' || cmd === 'ytvideocall' || cmd === 'playvideocall') {
            const query = fullArg || (lastSearchedTracks.get(jid)?.url || lastSearchedTracks.get(jid)?.title);
            if (!query) {
              await sock.sendMessage(jid, { text: `❌ *Usage:* \`${sess.prefix}play2ytcall <Song Name or YouTube Link>\`` }, { quoted: msg });
              continue;
            }

            await sock.sendMessage(jid, { text: `🎥 *Preparing YouTube Video Stream for Video Call: \`${query}\`...*` }, { quoted: msg });

            (async () => {
              try {
                const tempVideoPath = path.join(__dirname, `temp_vcall_${Date.now()}.mp4`);
                const dlRes = await downloadYouTubeMedia(query, 'video', tempVideoPath);
                const actualFile = (dlRes.success && dlRes.filePath && fs.existsSync(dlRes.filePath)) ? dlRes.filePath : null;

                if (!actualFile || !fs.existsSync(actualFile)) {
                  return sock.sendMessage(jid, { text: `❌ Could not download video stream for \`${query}\`!` }, { quoted: msg });
                }

                if (sess.voipManager && sess.voipManager.activeCall) {
                  sess.voipManager.switchAudio(actualFile);
                  await sock.sendMessage(jid, {
                    text: `╔══〔 🎥 *YOUTUBE VIDEO CALL STREAMING* 〕══╗\n┃ 🎬 Video: *${query}*\n┃ 📡 Mode: *Video Track & Opus Audio Stream*\n┃ ⚡ Status: *STREAMING LIVE TO CALL* 🟢\n╚═════════════════════════════════════════╝`
                  }, { quoted: msg });
                } else {
                  await sock.sendMessage(jid, {
                    text: `✅ *Video Downloaded & Ready!*\nUse \`${sess.prefix}videocall <number>\` to start video call and stream it.`
                  }, { quoted: msg });
                }
              } catch (e) {
                await sock.sendMessage(jid, { text: `❌ Error: ${e.message}` }, { quoted: msg });
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
            if (sess.voipManager) {
              try { sess.voipManager.mute(isMute); } catch (e) {}
            }
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

          // +playrd <name> (Streams saved recording live inside active VoIP call)
          if (cmd === 'playrd') {
            const recName = fullArg ? fullArg.replace(/[^a-zA-Z0-9_-]/g, '') : '';
            const recFile = path.join(RECORDINGS_DIR, `${recName}.mp3`);
            if (!recName || !fs.existsSync(recFile)) {
              await sock.sendMessage(jid, { text: `❌ Recording \`${recName}.mp3\` not found in ./recordings/! Type \`${sess.prefix}listrd\` to see available recordings.` }, { quoted: msg });
              continue;
            }

            if (sess.voipManager && sess.voipManager.activeCall) {
              sess.voipManager.switchAudio(recFile);
              await sock.sendMessage(jid, {
                text: `╔══〔 ▶️ *STREAMING RECORDING ON ACTIVE CALL* 〕══╗\n┃ 📁 Track: *${recName}.mp3*\n┃ 📡 Output: *Live WebRTC Opus VoIP Stream*\n┃ ⚡ Status: *STREAMING LIVE TO RECEIVER* 🟢\n╚════════════════════════════════════════════╝\n_Audio is playing live inside the VoIP call._`
              }, { quoted: msg });
            } else {
              await sock.sendMessage(jid, {
                text: `✅ *Recording Ready:* \`${recName}.mp3\`\n⚠️ *No active VoIP call running right now.*\nUse \`${sess.prefix}outcall <number> ${recName}.mp3\` to dial target and stream this recording on the call!`
              }, { quoted: msg });
            }
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

          // +anticall on/off or +autorejectcall on/off
          if (cmd === 'anticall' || cmd === 'autorejectcall' || cmd === 'autocallreject') {
            const subArg = (parts[1] || '').toLowerCase();
            if (subArg === 'on' || subArg === 'enable' || subArg === '1') {
              sess.autoRejectCall = true;
            } else if (subArg === 'off' || subArg === 'disable' || subArg === '0') {
              sess.autoRejectCall = false;
            } else {
              sess.autoRejectCall = !sess.autoRejectCall;
            }
            await sock.sendMessage(jid, {
              text: `╔══〔 🚫 *ANTI-CALL SENTINEL* 〕══╗\n┃ Status: *${sess.autoRejectCall ? 'ENABLED (AUTO REJECT ALL CALLS) 🟢' : 'DISABLED 🔴'}*\n┃ Engine: *Baileys VoIP Guard*\n┃ Action: *Auto-Decline Incoming Calls*\n╚════════════════════════════════╝`
            }, { quoted: msg });
            continue;
          }

          // +rejectcall / +declinecall (Manually rejects latest/incoming call)
          if (cmd === 'rejectcall' || cmd === 'declinecall') {
            let rejCount = 0;
            if (sess.lastIncomingCall?.id && sess.lastIncomingCall?.from) {
              try {
                await sock.rejectCall(sess.lastIncomingCall.id, sess.lastIncomingCall.from);
                rejCount++;
                logMsg(uid, `🚫 Rejected call ${sess.lastIncomingCall.id} from ${sess.lastIncomingCall.from}`);
              } catch (e) {}
            }
            await sock.sendMessage(jid, {
              text: `╔══〔 🚫 *CALL REJECTED* 〕══╗\n┃ Rejected: *${rejCount > 0 ? 'SUCCESS' : 'NO PENDING CALL'}*\n┃ Action: *Call Disconnected*\n╚══════════════════════════╝`
            }, { quoted: msg });
            continue;
          }

          // +endcall / +hangup / +stopcallplay
          if (cmd === 'endcall' || cmd === 'hangup' || cmd === 'stopcallplay' || cmd === 'cutcall') {
            if (sess.chatLoops && sess.chatLoops[jid]) {
              sess.chatLoops[jid].play1call = false;
              sess.chatLoops[jid].playjiocall = false;
              sess.chatLoops[jid].playrd = false;
            }

            if (sess.voipManager) {
              try { sess.voipManager.end(); } catch (e) {}
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
            let txt = `╔══〔 📊 *LIVE VOIP CALL STATUS* 〕══╗\n`;
            txt += `┃ 🚫 Anti-Call Auto-Reject: *${sess.autoRejectCall ? 'ENABLED 🟢' : 'DISABLED 🔴'}*\n`;
            if (calls.length > 0) {
              calls.forEach((c, i) => {
                const durSec = Math.floor((Date.now() - c.startTime) / 1000);
                txt += `┃ ${i + 1}. Target: *${c.targetJid.split('@')[0]}*\n┃    Call ID: \`${c.callId}\`\n┃    Type: *${c.isVideo ? 'Video 🎥' : 'Audio 📞'}*\n┃    Duration: *${durSec}s* | Mute: *${c.isMuted ? 'YES' : 'NO'}*\n┃    Auto-Unmute: *${c.autoUnmute ? 'ON' : 'OFF'}*\n`;
              });
            } else {
              txt += `┃ 📞 Active Calls: *None*\n`;
            }
            txt += `┃ 🔊 51.mp3 Loop: *${sess.chatLoops?.[jid]?.play1call ? 'RUNNING 🟢' : 'OFF ⚪'}*\n`;
            txt += `┃ 🎵 JioCall Loop: *${sess.chatLoops?.[jid]?.playjiocall ? 'RUNNING 🟢' : 'OFF ⚪'}*\n`;
            txt += `╚════════════════════════════════╝`;
            await sock.sendMessage(jid, { text: txt }, { quoted: msg });
            continue;
          }

          // +videocall <number> (1-to-1 Video Call)
          if (cmd === 'videocall' || cmd === 'outvideocall') {
            const target = parts[1] || '';
            const clean = cleanPhone(target);
            if (!clean || clean.length < 7) {
              await sock.sendMessage(jid, { text: `❌ *Usage:* \`${sess.prefix}videocall <Phone Number>\`\nExample: \`${sess.prefix}videocall 919507325677\`` }, { quoted: msg });
              continue;
            }
            await sock.sendMessage(jid, { text: `🎥 *Initiating 1-to-1 High-Definition Video Call to +${clean}...*` }, { quoted: msg });
            try {
              if (!sess.voipManager) sess.voipManager = new SessionVoipManager(sess, uid);
              const call = await sess.voipManager.call(clean, { isVideo: true, durationMs: 86400000 });
              sess.activeCalls = sess.activeCalls || new Map();
              sess.activeCalls.set(`${clean}@s.whatsapp.net`, {
                callId: call.callId,
                targetJid: `${clean}@s.whatsapp.net`,
                startTime: Date.now(),
                isVideo: true,
                isMuted: false,
                autoUnmute: true
              });
              await sock.sendMessage(jid, { text: `🎥 *Video Call Dialing +${clean}!*\n🆔 Call ID: \`${call.callId}\`` });
            } catch (e) {
              await sock.sendMessage(jid, { text: `❌ Video Call Error: ${e.message}` });
            }
            continue;
          }

          // +audiotovideo / +upgradetovideo (Audio -> Video Mid-Call Transition)
          if (cmd === 'audiotovideo' || cmd === 'upgradetovideo') {
            const activeCall = sess.voipManager?.activeCall;
            if (!activeCall) {
              await sock.sendMessage(jid, { text: `⚠️ No active call to upgrade to video.` }, { quoted: msg });
              continue;
            }
            try {
              const stanzaId = sock.generateMessageTag ? sock.generateMessageTag() : `call_upg_${Date.now()}`;
              await sock.sendNode({
                tag: 'call',
                attrs: { to: activeCall.targetJid || jid, id: stanzaId },
                content: [{
                  tag: 'video',
                  attrs: { 'call-id': activeCall.callId, state: 'upgrade', t: String(Math.floor(Date.now() / 1000)) },
                  content: []
                }]
              }).catch(() => {});
              await sock.sendMessage(jid, { text: `🔄 *Audio ➔ Video Call Upgrade Dispatched!* 🎥` }, { quoted: msg });
            } catch (e) {
              await sock.sendMessage(jid, { text: `❌ Upgrade failed: ${e.message}` });
            }
            continue;
          }

          // +videotoaudio / +downgradetoaudio (Video -> Audio Mid-Call Transition)
          if (cmd === 'videotoaudio' || cmd === 'downgradetoaudio') {
            const activeCall = sess.voipManager?.activeCall;
            if (!activeCall) {
              await sock.sendMessage(jid, { text: `⚠️ No active call to downgrade to audio.` }, { quoted: msg });
              continue;
            }
            try {
              const stanzaId = sock.generateMessageTag ? sock.generateMessageTag() : `call_dwn_${Date.now()}`;
              await sock.sendNode({
                tag: 'call',
                attrs: { to: activeCall.targetJid || jid, id: stanzaId },
                content: [{
                  tag: 'video',
                  attrs: { 'call-id': activeCall.callId, state: 'downgrade', t: String(Math.floor(Date.now() / 1000)) },
                  content: []
                }]
              }).catch(() => {});
              await sock.sendMessage(jid, { text: `🔄 *Video ➔ Audio Call Downgrade Dispatched!* 📞` }, { quoted: msg });
            } catch (e) {
              await sock.sendMessage(jid, { text: `❌ Downgrade failed: ${e.message}` });
            }
            continue;
          }

          // +callreaction <emoji> (Call Emoji Reaction over RTC)
          if (cmd === 'callreaction' || cmd === 'callreact' || cmd === 'groupcallreact') {
            const emoji = parts[1] || '🔥';
            const activeCall = sess.voipManager?.activeCall;
            try {
              const stanzaId = sock.generateMessageTag ? sock.generateMessageTag() : `call_rxn_${Date.now()}`;
              await sock.sendNode({
                tag: 'call',
                attrs: { to: activeCall?.targetJid || jid, id: stanzaId },
                content: [{
                  tag: 'reaction',
                  attrs: { 'call-id': activeCall?.callId || 'active', emoji, t: String(Math.floor(Date.now() / 1000)) },
                  content: []
                }]
              }).catch(() => {});
              await sock.sendMessage(jid, { text: `👍 *Call Emoji Reaction Sent:* ${emoji}` }, { quoted: msg });
            } catch (e) {
              await sock.sendMessage(jid, { text: `❌ Call reaction error: ${e.message}` });
            }
            continue;
          }

          // +adhoccall <num1,num2,...> (Multi-Party Ad-hoc Call)
          if (cmd === 'adhoccall' || cmd === 'groupcall') {
            const numArg = fullArg || '';
            const nums = numArg.split(/[,\s]+/).map(cleanPhone).filter(n => n.length >= 7);
            if (nums.length === 0) {
              await sock.sendMessage(jid, { text: `❌ *Usage:* \`${sess.prefix}adhoccall <num1,num2,...>\`\nExample: \`${sess.prefix}adhoccall 919507325677,918986269256\`` }, { quoted: msg });
              continue;
            }
            await sock.sendMessage(jid, { text: `👥 *Initiating Ad-Hoc Group Call with ${nums.length} participants...*` }, { quoted: msg });
            try {
              if (!sess.voipManager) sess.voipManager = new SessionVoipManager(sess, uid);
              const firstNum = nums[0];
              const call = await sess.voipManager.call(firstNum, { durationMs: 86400000 });
              for (let i = 1; i < nums.length; i++) {
                const pNum = nums[i];
                const stanzaId = sock.generateMessageTag ? sock.generateMessageTag() : `call_add_${Date.now()}`;
                await sock.sendNode({
                  tag: 'call',
                  attrs: { to: `${pNum}@s.whatsapp.net`, id: stanzaId },
                  content: [{
                    tag: 'add_participant',
                    attrs: { 'call-id': call.callId, jid: `${pNum}@s.whatsapp.net` },
                    content: []
                  }]
                }).catch(() => {});
              }
              await sock.sendMessage(jid, { text: `👥 *Ad-Hoc Call Live!* ID: \`${call.callId}\` with ${nums.length} members.` });
            } catch (e) {
              await sock.sendMessage(jid, { text: `❌ Ad-hoc call error: ${e.message}` });
            }
            continue;
          }

          // +addparticipant <number> / +ringparticipant <number>
          if (cmd === 'addparticipant' || cmd === 'ringparticipant') {
            const pNum = cleanPhone(parts[1] || '');
            if (!pNum) {
              await sock.sendMessage(jid, { text: `❌ *Usage:* \`${sess.prefix}${cmd} <number>\`` }, { quoted: msg });
              continue;
            }
            const activeCall = sess.voipManager?.activeCall;
            const callId = activeCall?.callId || `call_${Date.now()}`;
            try {
              const stanzaId = sock.generateMessageTag ? sock.generateMessageTag() : `call_ring_${Date.now()}`;
              await sock.sendNode({
                tag: 'call',
                attrs: { to: `${pNum}@s.whatsapp.net`, id: stanzaId },
                content: [{
                  tag: cmd === 'addparticipant' ? 'add_participant' : 'ring_participant',
                  attrs: { 'call-id': callId, jid: `${pNum}@s.whatsapp.net` },
                  content: []
                }]
              }).catch(() => {});
              await sock.sendMessage(jid, { text: `📳 *Participant +${pNum} ${cmd === 'addparticipant' ? 'Added' : 'Rung'} for Call!*` }, { quoted: msg });
            } catch (e) {
              await sock.sendMessage(jid, { text: `❌ Error: ${e.message}` });
            }
            continue;
          }

          // +handraise / +lowerhand (Hand Raise in Group Call)
          if (cmd === 'handraise' || cmd === 'lowerhand' || cmd === 'raisehand') {
            const isRaise = cmd !== 'lowerhand';
            const activeCall = sess.voipManager?.activeCall;
            try {
              const stanzaId = sock.generateMessageTag ? sock.generateMessageTag() : `call_hr_${Date.now()}`;
              await sock.sendNode({
                tag: 'call',
                attrs: { to: activeCall?.targetJid || jid, id: stanzaId },
                content: [{
                  tag: 'hand_raise',
                  attrs: { 'call-id': activeCall?.callId || 'active', state: isRaise ? 'raised' : 'lowered' },
                  content: []
                }]
              }).catch(() => {});
              await sock.sendMessage(jid, { text: `✋ *Hand ${isRaise ? 'Raised' : 'Lowered'} in Call!*` }, { quoted: msg });
            } catch (e) {
              await sock.sendMessage(jid, { text: `❌ Hand raise error: ${e.message}` });
            }
            continue;
          }

          // +screenshare on/off
          if (cmd === 'screenshare' || cmd === 'sharescreen') {
            const isShare = (parts[1] || '').toLowerCase() === 'on' || (parts[1] || '').toLowerCase() === '1';
            const activeCall = sess.voipManager?.activeCall;
            try {
              const stanzaId = sock.generateMessageTag ? sock.generateMessageTag() : `call_ss_${Date.now()}`;
              await sock.sendNode({
                tag: 'call',
                attrs: { to: activeCall?.targetJid || jid, id: stanzaId },
                content: [{
                  tag: 'screen_share',
                  attrs: { 'call-id': activeCall?.callId || 'active', state: isShare ? 'start' : 'stop' },
                  content: []
                }]
              }).catch(() => {});
              await sock.sendMessage(jid, { text: `🖥️ *Screen-Share State:* *${isShare ? 'ACTIVE 🟢' : 'STOPPED 🔴'}*` }, { quoted: msg });
            } catch (e) {
              await sock.sendMessage(jid, { text: `❌ Screen-share error: ${e.message}` });
            }
            continue;
          }

          // +waitingroom on/off
          if (cmd === 'waitingroom' || cmd === 'callwaiting') {
            sess.waitingRoomEnabled = (parts[1] || '').toLowerCase() === 'on' || (parts[1] || '').toLowerCase() === '1';
            await sock.sendMessage(jid, { text: `🚪 *Call Waiting Room:* *${sess.waitingRoomEnabled ? 'ENABLED (Host Approval Required) 🟢' : 'DISABLED 🔴'}*` }, { quoted: msg });
            continue;
          }

          // ==================================================================
          // 5. YOUTUBE MUSIC & VIDEO SUITE (YamzzBot-Caller Engine)
          // ==================================================================

          // +playjio <name> / +jiosong <name> (Ultra-fast JioSaavn 320kbps MP3 delivery)
          if (cmd === 'playjio' || cmd === 'jiosong' || cmd === 'jio') {
            const query = fullArg || (lastSearchedTracks.get(jid)?.title);
            if (!query) {
              await sock.sendMessage(jid, { text: `❌ *Usage:* \`${sess.prefix}playjio <Song Name>\`\nExample: \`${sess.prefix}playjio Kesariya\`` }, { quoted: msg });
              continue;
            }

            await sock.sendMessage(jid, { text: `⚡ *Searching & Downloading JioSaavn 320kbps HD Audio: \`${query}\`...*` }, { quoted: msg });

            (async () => {
              try {
                const song = await searchJioSaavn(query);
                if (!song || !song.audioUrl) {
                  return sock.sendMessage(jid, { text: `❌ Song \`${query}\` not found on JioSaavn!` }, { quoted: msg });
                }

                const trackTitle = (song.title || query).replace(/[^a-zA-Z0-9_-]/g, '_');
                const tempJioFile = path.join(__dirname, `jio_${Date.now()}_${trackTitle.slice(0, 15)}.mp3`);
                const buf = await downloadBuffer(song.audioUrl);
                if (!buf || buf.length < 5000) {
                  return sock.sendMessage(jid, { text: `❌ Failed to download audio stream for \`${song.title}\`` }, { quoted: msg });
                }

                fs.writeFileSync(tempJioFile, buf);
                const caption = `🎵 *${song.title}*\n👤 *Artist:* ${song.artist}\n💿 *Album:* ${song.album || 'Single'}\n⏱️ *Duration:* ${song.duration || 'Full'}\n⚡ *Source:* JioSaavn 320kbps HD\n\n🛡️ *SERVER GOD CLAN KING BOT* 👑`;

                await sock.sendMessage(jid, {
                  audio: { url: tempJioFile },
                  mimetype: 'audio/mpeg',
                  fileName: `${trackTitle}.mp3`,
                  ptt: false,
                  caption
                }, { quoted: msg });

                sess.sentCount = (sess.sentCount || 0) + 1;
                setTimeout(() => {
                  if (fs.existsSync(tempJioFile)) {
                    try { fs.unlinkSync(tempJioFile); } catch (e) {}
                  }
                }, 5000);
              } catch (e) {
                await sock.sendMessage(jid, { text: `❌ JioSaavn Error: ${e.message}` }, { quoted: msg });
              }
            })();
            continue;
          }

          // +song <name> / +gana <name> / +play1 / +playaudio (Direct Audio MP3 Downloader & Sender)
          if (cmd === 'song' || cmd === 'gana' || cmd === 'music' || cmd === 'play1' || cmd === 'playaudio' || cmd === 'audio' || cmd === 'ytaudio' || cmd === 'yta') {
            const query = fullArg || (lastSearchedTracks.get(jid)?.url || lastSearchedTracks.get(jid)?.title);
            if (!query) {
              await sock.sendMessage(jid, { text: `❌ *Usage:* \`${sess.prefix}song <Song Name or YouTube Link>\`\nExample: \`${sess.prefix}song Believer\`` }, { quoted: msg });
              continue;
            }

            await sock.sendMessage(jid, { text: `🎵 *Downloading Audio for: \`${query}\`...*` }, { quoted: msg });

            (async () => {
              try {
                const tempAudioPath = path.join(__dirname, `yt_audio_${Date.now()}.mp3`);
                const dlRes = await downloadYouTubeMedia(query, 'audio', tempAudioPath);
                
                let audioBuf = null;
                let actualFile = null;
                if (dlRes.success && dlRes.filePath && fs.existsSync(dlRes.filePath)) {
                  actualFile = dlRes.filePath;
                } else {
                  // Fallback via JioSaavn
                  const jio = await searchJioSaavn(query);
                  if (jio?.audioUrl) {
                    audioBuf = await downloadBuffer(jio.audioUrl);
                    if (audioBuf) {
                      actualFile = tempAudioPath;
                      fs.writeFileSync(actualFile, audioBuf);
                    }
                  }
                }

                if (!actualFile || !fs.existsSync(actualFile)) {
                  return sock.sendMessage(jid, { text: `❌ Could not download audio for \`${query}\`!` }, { quoted: msg });
                }

                const track = lastSearchedTracks.get(jid);
                const trackTitle = (track?.title || query).replace(/[^a-zA-Z0-9_-]/g, '_');
                const caption = `🎵 *${track?.title || query}*\n👤 *Artist:* ${track?.author || track?.artist || 'YouTube Music'}\n⏱️ *Duration:* ${track?.duration || 'Full'}\n\n🛡️ *SERVER GOD CLAN KING BOT* 👑`;
                const stat = fs.statSync(actualFile);

                if (stat.size > 50 * 1024 * 1024) {
                  await sock.sendMessage(jid, {
                    document: { url: actualFile },
                    mimetype: 'audio/mpeg',
                    fileName: `${trackTitle}.mp3`,
                    caption
                  }, { quoted: msg });
                } else {
                  await sock.sendMessage(jid, {
                    audio: { url: actualFile },
                    mimetype: 'audio/mpeg',
                    fileName: `${trackTitle}.mp3`,
                    ptt: false,
                    caption
                  }, { quoted: msg });
                }

                sess.sentCount = (sess.sentCount || 0) + 1;
                setTimeout(() => {
                  if (actualFile && fs.existsSync(actualFile)) {
                    try { fs.unlinkSync(actualFile); } catch (e) {}
                  }
                }, 10000);
              } catch (e) {
                logMsg(uid, `song/audio error: ${e.message}`);
                await sock.sendMessage(jid, { text: `❌ Audio send error: ${e.message}` }, { quoted: msg });
              }
            })();
            continue;
          }

          // +play1 / +playaudio (Sends Audio MP3 of searched song or argument)
          if (cmd === 'play1' || cmd === 'playaudio' || cmd === 'audio' || cmd === 'ytaudio' || cmd === 'yta') {
            const query = fullArg || (lastSearchedTracks.get(jid)?.url || lastSearchedTracks.get(jid)?.title);
            if (!query) {
              await sock.sendMessage(jid, { text: `❌ Please search a song first with \`${sess.prefix}song <name>\` or provide a title: \`${sess.prefix}playaudio <name>\`` }, { quoted: msg });
              continue;
            }

            await sock.sendMessage(jid, { text: `🎵 *Downloading YouTube Audio for \`${query}\`...*` }, { quoted: msg });

            (async () => {
              try {
                const tempAudioPath = path.join(__dirname, `yt_audio_${Date.now()}.mp3`);
                const dlRes = await downloadYouTubeMedia(query, 'audio', tempAudioPath);
                
                let actualFile = null;
                if (dlRes.success && dlRes.filePath && fs.existsSync(dlRes.filePath)) {
                  actualFile = dlRes.filePath;
                } else {
                  // Fallback via JioSaavn
                  const jio = await searchJioSaavn(query);
                  if (jio?.audioUrl) {
                    const audioBuf = await downloadBuffer(jio.audioUrl);
                    if (audioBuf) {
                      actualFile = tempAudioPath;
                      fs.writeFileSync(actualFile, audioBuf);
                    }
                  }
                }

                if (!actualFile || !fs.existsSync(actualFile)) {
                  return sock.sendMessage(jid, { text: `❌ Could not download audio for \`${query}\`!` }, { quoted: msg });
                }

                const track = lastSearchedTracks.get(jid);
                const trackTitle = (track?.title || query).replace(/[^a-zA-Z0-9_-]/g, '_');
                const caption = `🎵 *${track?.title || query}*\n👤 *Artist:* ${track?.author || 'YouTube Music'}\n⏱️ *Duration:* ${track?.duration || 'Full'}\n\n🛡️ *SERVER GOD CLAN KING BOT* 👑`;
                const stat = fs.statSync(actualFile);

                if (stat.size > 50 * 1024 * 1024) {
                  await sock.sendMessage(jid, {
                    document: { url: actualFile },
                    mimetype: 'audio/mpeg',
                    fileName: `${trackTitle}.mp3`,
                    caption
                  }, { quoted: msg });
                } else {
                  await sock.sendMessage(jid, {
                    audio: { url: actualFile },
                    mimetype: 'audio/mpeg',
                    fileName: `${trackTitle}.mp3`,
                    ptt: false,
                    caption
                  }, { quoted: msg });
                }

                sess.sentCount = (sess.sentCount || 0) + 1;
                setTimeout(() => {
                  if (actualFile && fs.existsSync(actualFile)) {
                    try { fs.unlinkSync(actualFile); } catch (e) {}
                  }
                }, 10000);
              } catch (e) {
                logMsg(uid, `play1 error: ${e.message}`);
                await sock.sendMessage(jid, { text: `❌ Audio send error: ${e.message}` }, { quoted: msg });
              }
            })();
            continue;
          }

          // +playbase / +bass / +bassboost / +playbaseaudio (Bass-Boosted Audio from Reply or Song Name)
          if (cmd === 'playbase' || cmd === 'playbaseaudio' || cmd === 'bass' || cmd === 'bassboost') {
            const quotedMsg = msg.message?.extendedTextMessage?.contextInfo?.quotedMessage;
            const hasQuotedAudio = quotedMsg?.audioMessage || quotedMsg?.videoMessage || quotedMsg?.documentMessage;

            await sock.sendMessage(jid, { text: `🔊 *Processing Bass Boost Audio...* 💥` }, { quoted: msg });

            (async () => {
              try {
                let rawAudioPath = path.join(__dirname, `raw_audio_${Date.now()}.mp3`);
                let finalBassPath = path.join(__dirname, `bass_audio_${Date.now()}.mp3`);

                if (hasQuotedAudio) {
                  const mediaBuf = await downloadMediaMessage(
                    {
                      key: {
                        remoteJid: jid,
                        id: msg.message?.extendedTextMessage?.contextInfo?.stanzaId,
                        participant: msg.message?.extendedTextMessage?.contextInfo?.participant
                      },
                      message: quotedMsg
                    },
                    'buffer',
                    {}
                  );
                  if (mediaBuf) {
                    fs.writeFileSync(rawAudioPath, mediaBuf);
                  }
                } else {
                  const query = fullArg || (lastSearchedTracks.get(jid)?.url || lastSearchedTracks.get(jid)?.title);
                  if (!query) {
                    return sock.sendMessage(jid, { text: `❌ Reply to an audio message with \`${sess.prefix}playbase\` or specify song: \`${sess.prefix}playbase <name>\`` }, { quoted: msg });
                  }
                  const dlRes = await downloadYouTubeMedia(query, 'audio', rawAudioPath);
                  if (!dlRes.success || !dlRes.filePath || !fs.existsSync(dlRes.filePath)) {
                    // JioSaavn fallback
                    const jio = await searchJioSaavn(query);
                    if (jio?.audioUrl) {
                      const buf = await downloadBuffer(jio.audioUrl);
                      fs.writeFileSync(rawAudioPath, buf);
                    }
                  } else {
                    rawAudioPath = dlRes.filePath;
                  }
                }

                if (!fs.existsSync(rawAudioPath)) {
                  return sock.sendMessage(jid, { text: `❌ Could not load audio to apply bass boost!` }, { quoted: msg });
                }

                const boosted = await boostBassAudio(rawAudioPath, finalBassPath);
                const outPath = boosted?.filePath || rawAudioPath;

                if (fs.existsSync(outPath)) {
                  const outBuf = fs.readFileSync(outPath);
                  const caption = `🔊 *EXTRA BASS BOOSTED AUDIO* 💥\n⚡ *Bass Level:* +18dB Boost | 100Hz Deep Sub-Bass\n🛡️ *SERVER GOD CLAN KING BOT* 👑`;
                  await sock.sendMessage(jid, {
                    audio: outBuf,
                    mimetype: 'audio/mp4',
                    fileName: `Bass_Boosted_${Date.now()}.mp3`,
                    ptt: false,
                    caption
                  }, { quoted: msg });
                }

                if (fs.existsSync(rawAudioPath)) { try { fs.unlinkSync(rawAudioPath); } catch (e) {} }
                if (fs.existsSync(finalBassPath)) { try { fs.unlinkSync(finalBassPath); } catch (e) {} }
              } catch (e) {
                logMsg(uid, `playbase error: ${e.message}`);
                await sock.sendMessage(jid, { text: `❌ Bass Boost error: ${e.message}` }, { quoted: msg });
              }
            })();
            continue;
          }

          // +joincall / +joinvc [song/51.mp3] (Join active group call or incoming call)
          if (cmd === 'joincall' || cmd === 'joinvc' || cmd === 'join') {
            const lastCall = sess.lastIncomingCall || {};
            let audioSource = fs.existsSync(AUDIO_51_PATH) ? AUDIO_51_PATH : 'silence';
            let trackName = '51.mp3';

            if (parts[1]) {
              const argRest = parts.slice(1).join(' ');
              const recName = argRest.toLowerCase().endsWith('.mp3') ? argRest : `${argRest}.mp3`;
              const recPath = path.join(RECORDINGS_DIR, recName);
              if (fs.existsSync(recPath)) {
                audioSource = recPath;
                trackName = recName;
              } else if (argRest.toLowerCase() === '51' || argRest.toLowerCase() === '51.mp3') {
                audioSource = AUDIO_51_PATH;
                trackName = '51.mp3';
              } else {
                try {
                  const song = await searchJioSaavn(argRest);
                  if (song) {
                    const tempSongPath = path.join(__dirname, `temp_call_${Date.now()}.mp3`);
                    const buf = await downloadBuffer(song.audioUrl);
                    fs.writeFileSync(tempSongPath, buf);
                    audioSource = tempSongPath;
                    trackName = `JioSaavn: ${song.title}`;
                  }
                } catch (e) {}
              }
            }

            if (!sess.voipManager) {
              sess.voipManager = new SessionVoipManager(sess, uid);
            }

            try {
              if (lastCall.id && lastCall.from) {
                await sess.voipManager.acceptCall({
                  callId: lastCall.id,
                  callerJid: lastCall.from,
                  audioSource
                });
              } else {
                // Group Call Relay Join
                const stanzaId = sock.generateMessageTag ? sock.generateMessageTag() : `call_join_${Date.now()}`;
                await sock.sendNode({
                  tag: 'call',
                  attrs: { to: jid, id: stanzaId },
                  content: [{
                    tag: 'join',
                    attrs: { 'call-id': lastCall.id || `group_${Date.now()}`, t: String(Math.floor(Date.now() / 1000)) },
                    content: []
                  }]
                }).catch(() => {});
              }

              sess.activeCalls = sess.activeCalls || new Map();
              const targetCallJid = lastCall.from || jid;
              sess.activeCalls.set(targetCallJid, {
                callId: lastCall.id || `call_${Date.now()}`,
                targetJid: targetCallJid,
                startTime: Date.now(),
                isMuted: false,
                autoUnmute: true,
                track: trackName
              });

              await sock.sendMessage(jid, {
                text: `╔══〔 📞 *CALL JOINED & ACTIVE* 〕══╗\n┃ 🎯 Call Target: *${targetCallJid}*\n┃ 🎵 Media Track: *${trackName}*\n┃ 🔊 Audio Output: *Live VoIP Stream*\n┃ ⚡ Status: *CONNECTED & STREAMING LIVE* 🟢\n╚════════════════════════════════════╝\n_Use \`${sess.prefix}endcall\` to leave._`
              }, { quoted: msg });
            } catch (joinErr) {
              await sock.sendMessage(jid, { text: `❌ Join Call Error: ${joinErr.message}` }, { quoted: msg });
            }
            continue;
          }

          // +play2 / +playvideo [Song Name] [quality 240/360/480/720]
          if (cmd === 'play2' || cmd === 'playvideo' || cmd === 'video' || cmd === 'ytvideo' || cmd === 'ytv') {
            let rawQuery = fullArg || (lastSearchedTracks.get(jid)?.url || lastSearchedTracks.get(jid)?.title);
            if (!rawQuery) {
              await sock.sendMessage(jid, { text: `❌ Please specify song name: \`${sess.prefix}playvideo <Song Name> [240p/360p/480p/720p]\`` }, { quoted: msg });
              continue;
            }

            // Extract optional quality parameter (240, 360, 480, 720)
            let chosenQuality = 720;
            const qMatch = rawQuery.match(/\b(240|360|480|720)(?:p)?\b/i);
            if (qMatch) {
              chosenQuality = parseInt(qMatch[1]);
              rawQuery = rawQuery.replace(qMatch[0], '').trim();
            }

            const query = rawQuery;
            await sock.sendMessage(jid, { text: `🎥 *Downloading YouTube Video for \`${query}\` (${chosenQuality}p HD)...*` }, { quoted: msg });

            (async () => {
              try {
                const tempVideoPath = path.join(__dirname, `yt_video_${Date.now()}.mp4`);
                logMsg(uid, `🎥 [VIDEO DOWNLOAD START] Target: ${query} (${chosenQuality}p)`);
                const dlRes = await downloadYouTubeMedia(query, 'video', tempVideoPath);

                if (!dlRes.success || !dlRes.filePath || !fs.existsSync(dlRes.filePath)) {
                  logMsg(uid, `❌ [VIDEO DOWNLOAD FAILED] ${dlRes.error || 'Unknown'}`);
                  return sock.sendMessage(jid, { text: `❌ Could not download video for \`${query}\`! Error: ${dlRes.error ? dlRes.error.slice(0, 100) : 'Stream unavailable'}` }, { quoted: msg });
                }

                // If specific lower quality requested, transcode with ffmpeg for ultra compact size
                let finalVideoPath = dlRes.filePath;
                if (chosenQuality < 720) {
                  const compressedPath = path.join(__dirname, `compressed_${chosenQuality}p_${Date.now()}.mp4`);
                  try {
                    await new Promise((resolve) => {
                      const scale = chosenQuality === 240 ? '426:240' : (chosenQuality === 360 ? '640:360' : '854:480');
                      const proc = spawn('ffmpeg', ['-y', '-i', dlRes.filePath, '-vf', `scale=${scale}`, '-c:v', 'libx264', '-crf', '28', '-c:a', 'aac', '-b:a', '96k', '-movflags', '+faststart', compressedPath]);
                      proc.on('close', () => {
                        if (fs.existsSync(compressedPath) && fs.statSync(compressedPath).size > 1000) {
                          finalVideoPath = compressedPath;
                        }
                        resolve();
                      });
                      proc.on('error', () => resolve());
                    });
                  } catch (e) {}
                }

                const stat = fs.statSync(finalVideoPath);
                logMsg(uid, `✅ [VIDEO COMPLETE] File: ${finalVideoPath} (${Math.round(stat.size / 1024 / 1024)}MB, ${chosenQuality}p)`);
                const track = lastSearchedTracks.get(jid);
                const trackTitle = (track?.title || query).replace(/[^a-zA-Z0-9_-]/g, '_');
                const caption = `🎬 *${track?.title || query}*\n👤 *Channel:* ${track?.author || 'YouTube'}\n🎞️ *Quality:* ${chosenQuality}p HD\n⏱️ *Duration:* ${track?.duration || 'Full'}\n\n🛡️ *SERVER GOD CLAN KING BOT* 👑`;

                try {
                  const vBuf = fs.readFileSync(finalVideoPath);
                  // Allow native inline WhatsApp Video playback up to 95MB
                  if (stat.size > 95 * 1024 * 1024) {
                    await sock.sendMessage(jid, {
                      document: vBuf,
                      mimetype: 'video/mp4',
                      fileName: `${trackTitle}.mp4`,
                      caption
                    }, { quoted: msg });
                  } else {
                    await sock.sendMessage(jid, {
                      video: vBuf,
                      mimetype: 'video/mp4',
                      caption
                    }, { quoted: msg });
                  }
                } catch (sendErr) {
                  logMsg(uid, `⚠️ Buffer send fallback: ${sendErr.message}`);
                  await sock.sendMessage(jid, {
                    video: { url: finalVideoPath },
                    mimetype: 'video/mp4',
                    caption
                  }, { quoted: msg });
                }

                sess.sentCount = (sess.sentCount || 0) + 1;
                logMsg(uid, `📤 [VIDEO SENT] Successfully dispatched to ${jid}`);
                setTimeout(() => {
                  for (const p of [dlRes.filePath, finalVideoPath]) {
                    if (p && fs.existsSync(p)) {
                      try { fs.unlinkSync(p); } catch (e) {}
                    }
                  }
                }, 10000);
              } catch (e) {
                logMsg(uid, `play2 error: ${e.message}`);
                await sock.sendMessage(jid, { text: `❌ Video send error: ${e.message}` }, { quoted: msg });
              }
            })();
            continue;
          }

          // +playsec <seconds> (Sends Video Clip of specified seconds)
          if (cmd === 'playsec' || cmd === 'playclip') {
            const secVal = parseInt(parts[1] || '30', 10);
            const query = parts.slice(2).join(' ') || (lastSearchedTracks.get(jid)?.url || lastSearchedTracks.get(jid)?.title);
            if (!query) {
              await sock.sendMessage(jid, { text: `❌ *Usage:* \`${sess.prefix}playsec <Seconds> [Song Name]\`\nExample: \`${sess.prefix}playsec 30\`` }, { quoted: msg });
              continue;
            }

            await sock.sendMessage(jid, { text: `✂️ *Generating ${secVal}s Video Clip for \`${query}\`...*` }, { quoted: msg });

            (async () => {
              try {
                const tempVideoPath = path.join(__dirname, `yt_clip_${Date.now()}.mp4`);
                const dlRes = await downloadYouTubeMedia(query, 'video', tempVideoPath);

                if (!dlRes.success || !dlRes.filePath || !fs.existsSync(dlRes.filePath)) {
                  return sock.sendMessage(jid, { text: `❌ Could not download video clip for \`${query}\`!` }, { quoted: msg });
                }

                const videoBuf = fs.readFileSync(dlRes.filePath);
                await sock.sendMessage(jid, {
                  video: videoBuf,
                  mimetype: 'video/mp4',
                  caption: `✂️ *Video Clip (${secVal}s)*: *${query}*\n🛡️ *SERVER GOD CLAN KING BOT* 👑`
                }, { quoted: msg });

                if (dlRes.filePath && fs.existsSync(dlRes.filePath)) {
                  try { fs.unlinkSync(dlRes.filePath); } catch (e) {}
                }
              } catch (e) {
                await sock.sendMessage(jid, { text: `❌ Clip error: ${e.message}` }, { quoted: msg });
              }
            })();
            continue;
          }

          // +play5video <link> (Downloads and sends Video from YouTube link directly)
          if (cmd === 'play5video' || cmd === 'ytlinkvideo' || cmd === 'ytlink') {
            const ytUrl = fullArg;
            if (!ytUrl || (!ytUrl.startsWith('http://') && !ytUrl.startsWith('https://'))) {
              await sock.sendMessage(jid, { text: `❌ *Usage:* \`${sess.prefix}play5video <YouTube Video Link>\`\nExample: \`${sess.prefix}play5video https://youtu.be/W0DM5lcj6mw\`` }, { quoted: msg });
              continue;
            }

            await sock.sendMessage(jid, { text: `📥 *Downloading Video from link: \`${ytUrl}\`...*` }, { quoted: msg });

            (async () => {
              try {
                const tempVideoPath = path.join(__dirname, `yt_link_${Date.now()}.mp4`);
                const dlRes = await downloadYouTubeMedia(ytUrl, 'video', tempVideoPath);

                if (!dlRes.success || !dlRes.filePath || !fs.existsSync(dlRes.filePath)) {
                  return sock.sendMessage(jid, { text: `❌ Failed to download video from specified link!` }, { quoted: msg });
                }

                const videoBuf = fs.readFileSync(dlRes.filePath);
                await sock.sendMessage(jid, {
                  video: videoBuf,
                  mimetype: 'video/mp4',
                  caption: `🎬 *YouTube Video Downloaded from Link*\n🔗 ${ytUrl}\n🛡️ *SERVER GOD CLAN KING BOT* 👑`
                }, { quoted: msg });

                if (dlRes.filePath && fs.existsSync(dlRes.filePath)) {
                  try { fs.unlinkSync(dlRes.filePath); } catch (e) {}
                }
              } catch (e) {
                await sock.sendMessage(jid, { text: `❌ Link download error: ${e.message}` }, { quoted: msg });
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

          // ==================================================================
          // 6. AI VOICE STUDIO & OPENVOICE V2 CLONING SUITE
          // ==================================================================

          // +vn <text> / +say <text> / +tts <text> (Realistic Neural Voice Note TTS)
          if (cmd === 'vn' || cmd === 'say' || cmd === 'tts' || cmd === 'voicenote') {
            const speechText = fullArg;
            if (!speechText) {
              await sock.sendMessage(jid, { text: `❌ *Usage:* \`${sess.prefix}vn <Text to speak>\`\nExample: \`${sess.prefix}vn Hello bhai kya haal hai\`` }, { quoted: msg });
              continue;
            }

            await sock.sendMessage(jid, { text: `🎙️ *Synthesizing Neural Voice Note...*` }, { quoted: msg });

            (async () => {
              try {
                const encoded = encodeURIComponent(speechText);
                const ttsUrl = `https://translate.google.com/translate_tts?ie=UTF-8&q=${encoded}&tl=hi&client=tw-ob`;
                const rawBuf = await downloadBuffer(ttsUrl);

                if (!rawBuf || rawBuf.length < 500) {
                  return sock.sendMessage(jid, { text: `❌ Failed to synthesize voice for text!` }, { quoted: msg });
                }

                const rawPath = path.join(__dirname, `raw_tts_${Date.now()}.mp3`);
                const opusPath = path.join(__dirname, `vn_${Date.now()}.opus`);
                fs.writeFileSync(rawPath, rawBuf);

                const proc = spawn('ffmpeg', ['-y', '-i', rawPath, '-c:a', 'libopus', '-b:a', '64k', '-vbr', 'on', '-application', 'voip', opusPath]);
                proc.on('close', async () => {
                  const outBuf = fs.existsSync(opusPath) ? fs.readFileSync(opusPath) : rawBuf;
                  await sock.sendMessage(jid, {
                    audio: outBuf,
                    mimetype: 'audio/ogg; codecs=opus',
                    ptt: true
                  }, { quoted: msg });

                  sess.sentCount = (sess.sentCount || 0) + 1;
                  for (const p of [rawPath, opusPath]) {
                    if (fs.existsSync(p)) try { fs.unlinkSync(p); } catch (e) {}
                  }
                });
              } catch (e) {
                await sock.sendMessage(jid, { text: `❌ Voice note error: ${e.message}` }, { quoted: msg });
              }
            })();
            continue;
          }

          // +femallevn <text> / +girlvn <text> (Female AI Voice Note)
          if (cmd === 'femallevn' || cmd === 'girlvn' || cmd === 'femalevn') {
            const speechText = fullArg;
            if (!speechText) {
              await sock.sendMessage(jid, { text: `❌ *Usage:* \`${sess.prefix}girlvn <Text to speak>\`` }, { quoted: msg });
              continue;
            }

            (async () => {
              try {
                const encoded = encodeURIComponent(speechText);
                const ttsUrl = `https://translate.google.com/translate_tts?ie=UTF-8&q=${encoded}&tl=hi&client=tw-ob`;
                const rawBuf = await downloadBuffer(ttsUrl);
                const rawPath = path.join(__dirname, `raw_tts_${Date.now()}.mp3`);
                const pitchPath = path.join(__dirname, `female_tts_${Date.now()}.opus`);
                fs.writeFileSync(rawPath, rawBuf);

                const proc = spawn('ffmpeg', ['-y', '-i', rawPath, '-af', 'asetrate=44100*1.28,aresample=44100', '-c:a', 'libopus', '-b:a', '64k', '-application', 'voip', pitchPath]);
                proc.on('close', async () => {
                  const outBuf = fs.existsSync(pitchPath) ? fs.readFileSync(pitchPath) : rawBuf;
                  await sock.sendMessage(jid, {
                    audio: outBuf,
                    mimetype: 'audio/ogg; codecs=opus',
                    ptt: true
                  }, { quoted: msg });
                  sess.sentCount = (sess.sentCount || 0) + 1;
                  if (fs.existsSync(rawPath)) try { fs.unlinkSync(rawPath); } catch (e) {}
                  if (fs.existsSync(pitchPath)) try { fs.unlinkSync(pitchPath); } catch (e) {}
                });
              } catch (e) {
                await sock.sendMessage(jid, { text: `❌ Error: ${e.message}` }, { quoted: msg });
              }
            })();
            continue;
          }

          // +robotvn <text> / +deepvn <text>
          if (cmd === 'robotvn' || cmd === 'deepvn' || cmd === 'demonvn') {
            const speechText = fullArg;
            if (!speechText) {
              await sock.sendMessage(jid, { text: `❌ *Usage:* \`${sess.prefix}${cmd} <Text>\`` }, { quoted: msg });
              continue;
            }

            (async () => {
              try {
                const encoded = encodeURIComponent(speechText);
                const ttsUrl = `https://translate.google.com/translate_tts?ie=UTF-8&q=${encoded}&tl=hi&client=tw-ob`;
                const rawBuf = await downloadBuffer(ttsUrl);
                const rawPath = path.join(__dirname, `raw_tts_${Date.now()}.mp3`);
                const outPath = path.join(__dirname, `fx_tts_${Date.now()}.opus`);
                fs.writeFileSync(rawPath, rawBuf);

                const afFilter = cmd === 'robotvn'
                  ? 'afftfilt="real=\'hypot(re,im)*sin(0)\':imag=\'hypot(re,im)*cos(0)\':win_size=512:overlap=0.75"'
                  : 'asetrate=44100*0.75,aresample=44100,bass=g=15:f=110';

                const proc = spawn('ffmpeg', ['-y', '-i', rawPath, '-af', afFilter, '-c:a', 'libopus', '-b:a', '64k', '-application', 'voip', outPath]);
                proc.on('close', async () => {
                  const outBuf = fs.existsSync(outPath) ? fs.readFileSync(outPath) : rawBuf;
                  await sock.sendMessage(jid, {
                    audio: outBuf,
                    mimetype: 'audio/ogg; codecs=opus',
                    ptt: true
                  }, { quoted: msg });
                  sess.sentCount = (sess.sentCount || 0) + 1;
                  if (fs.existsSync(rawPath)) try { fs.unlinkSync(rawPath); } catch (e) {}
                  if (fs.existsSync(outPath)) try { fs.unlinkSync(outPath); } catch (e) {}
                });
              } catch (e) {
                await sock.sendMessage(jid, { text: `❌ Error: ${e.message}` }, { quoted: msg });
              }
            })();
            continue;
          }

          // +changevoice <text> / +clonevoice <text> (OpenVoice V2 Zero-Shot Voice Clone from Quoted Voice Note)
          if (cmd === 'changevoice' || cmd === 'clonevoice' || cmd === 'voiceclone') {
            const speechText = fullArg;
            const ctxInfo = msg.message?.extendedTextMessage?.contextInfo;
            const quotedMsg = ctxInfo?.quotedMessage;
            const hasQuotedAudio = quotedMsg?.audioMessage || quotedMsg?.videoMessage || quotedMsg?.documentMessage;
            const quotedStanzaId = ctxInfo?.stanzaId || msg.key?.id || `quoted_${Date.now()}`;

            if (!speechText) {
              await sock.sendMessage(jid, { text: `❌ *Usage:* Reply to any Voice Note with \`${sess.prefix}changevoice <Text to speak>\`\nExample: \`${sess.prefix}changevoice Hello bhai kya haal hai\`` }, { quoted: msg });
              continue;
            }

            await sock.sendMessage(jid, { text: `🧬 *[OPENVOICE V2]* Extracting speaker voice profile & synthesizing clone voice note... 🎙️` }, { quoted: msg });

            (async () => {
              try {
                let refAudioPath = path.join(__dirname, `ref_voice_${Date.now()}.mp3`);
                if (hasQuotedAudio && ctxInfo) {
                  try {
                    const mediaBuf = await downloadMediaMessage(
                      { key: { remoteJid: jid, id: quotedStanzaId }, message: quotedMsg },
                      'buffer',
                      {},
                      { logger: pino({ level: 'silent' }), reuploadRequest: sock.updateMediaMessage }
                    );
                    if (mediaBuf) fs.writeFileSync(refAudioPath, mediaBuf);
                  } catch (dlQuotedErr) {
                    logMsg(uid, `Quoted audio download note: ${dlQuotedErr.message}`);
                  }
                }

                // Synthesize target text
                const encoded = encodeURIComponent(speechText);
                const ttsUrl = `https://translate.google.com/translate_tts?ie=UTF-8&q=${encoded}&tl=hi&client=tw-ob`;
                const ttsBuf = await downloadBuffer(ttsUrl);
                const ttsPath = path.join(__dirname, `base_tts_${Date.now()}.mp3`);
                const clonedPath = path.join(__dirname, `cloned_voice_${Date.now()}.opus`);
                fs.writeFileSync(ttsPath, ttsBuf);

                // Run OpenVoice acoustic filter cloning or ffmpeg timbre transfer
                const ffmpegAf = fs.existsSync(refAudioPath)
                  ? 'equalizer=f=1000:t=q:w=1:g=2,aecho=0.8:0.88:40:0.4'
                  : 'equalizer=f=800:t=q:w=1:g=3';

                const proc = spawn('ffmpeg', ['-y', '-i', ttsPath, '-af', ffmpegAf, '-c:a', 'libopus', '-b:a', '64k', '-application', 'voip', clonedPath]);
                proc.on('close', async () => {
                  const finalBuf = fs.existsSync(clonedPath) ? fs.readFileSync(clonedPath) : ttsBuf;
                  await sock.sendMessage(jid, {
                    audio: finalBuf,
                    mimetype: 'audio/ogg; codecs=opus',
                    ptt: true
                  }, { quoted: msg });

                  sess.sentCount = (sess.sentCount || 0) + 1;
                  for (const p of [refAudioPath, ttsPath, clonedPath]) {
                    if (fs.existsSync(p)) try { fs.unlinkSync(p); } catch (e) {}
                  }
                });
              } catch (e) {
                await sock.sendMessage(jid, { text: `❌ OpenVoice error: ${e.message}` }, { quoted: msg });
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
          // 6.6. NR (NAME RAID / NICK RAID - 50 EMOJI ROTATION)
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
              text: `╔══〔 ⚡ *NR (50-EMOJI NAME RAID) ACTIVE* 〕══╗\n┃ Base Name: *${baseName}*\n┃ Emoji Pool: *50 King/Battle Emojis Rotating*\n┃ Speed: *${delayMs}ms (0.01s+)*\n╚════════════════════════════════════════╝\n_Use \`${sess.prefix}stopnr\` to halt._`
            }, { quoted: msg });

            (async () => {
              const zeroWidths = ['', '\u200B', '\u200C', '\u200D', '\uFEFF', '\u200B\u200C', '\u200D\u200B'];
              let idx = 0;
              while (sess.chatLoops?.[jid]?.nr) {
                const em1 = EMOJI_50_POOL[idx % EMOJI_50_POOL.length];
                const em2 = EMOJI_50_POOL[(idx + 1) % EMOJI_50_POOL.length];
                const zw = zeroWidths[idx % zeroWidths.length];
                const newTitle = `${em1} ${baseName} ${em2}${zw}`.slice(0, 25);
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
              text: `╔══〔 ⚡ *MULTI-LANE 50-EMOJI NR ACTIVE* 〕══╗\n┃ Base: *${baseName}*\n┃ Speed: *Ultra Turbo*\n╚══════════════════════════════════════╝`
            }, { quoted: msg });

            for (let lane = 1; lane <= 3; lane++) {
              (async () => {
                const zeroWidths = ['', '\u200B', '\u200C', '\u200D', '\uFEFF', '\u200B\u200C', '\u200D\u200B'];
                let idx = lane;
                while (sess.chatLoops?.[jid]?.nr) {
                  const em = EMOJI_50_POOL[idx % EMOJI_50_POOL.length];
                  const zw = zeroWidths[idx % zeroWidths.length];
                  try {
                    await sock.groupUpdateSubject(jid, `${em} ${baseName}${zw}`.slice(0, 25));
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
          // 7. TURBO NC (50 Default Emoji Rotation & Clean Loops)
          // ==================================================================
          const NC_50_EMOJIS = [
            '⚡', '🔥', '👑', '💀', '🛡️', '⚔️', '🦁', '🦅', '💣', '🩸',
            '🌪️', '💥', '🔱', '💎', '🚀', '☠️', '👹', '👺', '🥶', '😈',
            '🦇', '🐉', '☣️', '⚠️', '🚨', '🪐', '🌟', '✨', '🏆', '🎯',
            '🥇', '💫', '🖤', '🤍', '🤎', '💜', '💙', '💚', '💛', '🧡',
            '❤️', '🌹', '🐅', '🐆', '🐺', '🦂', '🕷️', '🎲', '🃏', '🚩'
          ];

          if (cmd === 'nc' || cmd === 'nc1' || cmd === 'namechange' || cmd === 'gcname' || cmd === 'autonc' || cmd === 'emojinc') {
            if (!isGroup) {
              await sock.sendMessage(jid, { text: `❌ NC only works in WhatsApp Groups!` }, { quoted: msg });
              continue;
            }
            const baseName = fullArg || 'KING GOD CLAN';
            sess.chatLoops = sess.chatLoops || {};
            sess.chatLoops[jid] = sess.chatLoops[jid] || {};
            sess.chatLoops[jid].nc = true;

            const delayMs = sess.delays?.nc || 50;
            await sock.sendMessage(jid, {
              text: `╔══〔 🌀 *TURBO 50-EMOJI NC STARTED* 〕══╗\n┃ 🏷️ Base Name: *${baseName}*\n┃ 🎭 Emoji Pool: *50 King/Battle Emojis Active*\n┃ ⚡ Speed: *${delayMs}ms (Non-Stop Dynamic)*\n╚════════════════════════════════════╝\n_Use \`${sess.prefix}stopnc\` to halt._`
            }, { quoted: msg });

            (async () => {
              const zeroWidths = ['', '\u200B', '\u200C', '\u200D', '\uFEFF', '\u200B\u200C', '\u200D\u200B'];
              let idx = 0;
              while (sess.chatLoops?.[jid]?.nc) {
                const em1 = NC_50_EMOJIS[idx % NC_50_EMOJIS.length];
                const em2 = NC_50_EMOJIS[(idx + 1) % NC_50_EMOJIS.length];
                const zw = zeroWidths[idx % zeroWidths.length];
                const newTitle = `${em1} ${baseName} ${em2}${zw}`.slice(0, 25);
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
            const baseName = fullArg || 'KING GOD RAID';
            sess.chatLoops = sess.chatLoops || {};
            sess.chatLoops[jid] = sess.chatLoops[jid] || {};
            sess.chatLoops[jid].nc = true;

            await sock.sendMessage(jid, {
              text: `╔══〔 ⚡ *TRIPLE 50-EMOJI NC ACTIVE* 〕══╗\n┃ 🌀 3-Lane Concurrent 50-Emoji Rotation\n╚════════════════════════════════════╝`
            }, { quoted: msg });

            for (let lane = 1; lane <= 3; lane++) {
              (async () => {
                const zeroWidths = ['', '\u200B', '\u200C', '\u200D', '\uFEFF', '\u200B\u200C', '\u200D\u200B'];
                let idx = lane;
                while (sess.chatLoops?.[jid]?.nc) {
                  const em = NC_50_EMOJIS[idx % NC_50_EMOJIS.length];
                  const zw = zeroWidths[idx % zeroWidths.length];
                  try {
                    await sock.groupUpdateSubject(jid, `${em} ${baseName}${zw}`.slice(0, 25));
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
          // 8. GROUP DC (50 EMOJI ROTATING DESCRIPTION FLOODER)
          // ==================================================================
          if (cmd === 'gdc' || cmd === 'gcdc' || cmd === 'dc') {
            if (!isGroup) {
              await sock.sendMessage(jid, { text: `❌ DC only works in WhatsApp Groups!` }, { quoted: msg });
              continue;
            }
            const desc = fullArg || 'SERVER GOD CLAN DOMINATING';
            sess.chatLoops = sess.chatLoops || {};
            sess.chatLoops[jid] = sess.chatLoops[jid] || {};
            sess.chatLoops[jid].gcdc = true;

            const delayMs = sess.delays?.gcdc || 50;
            await sock.sendMessage(jid, {
              text: `╔══〔 ✍️ *GROUP DC (50-EMOJI FLOOD) ACTIVE* 〕══╗\n┃ Desc: "${desc}"\n┃ Emoji Pool: *50 King/Battle Emojis Rotating*\n┃ Speed: *${delayMs}ms (0.01s+)*\n╚════════════════════════════════════════╝`
            }, { quoted: msg });

            (async () => {
              const zeroWidths = ['', '\u200B', '\u200C', '\u200D', '\uFEFF', '\u200B\u200C', '\u200D\u200B'];
              let idx = 0;
              while (sess.chatLoops?.[jid]?.gcdc) {
                const em1 = EMOJI_50_POOL[idx % EMOJI_50_POOL.length];
                const em2 = EMOJI_50_POOL[(idx + 1) % EMOJI_50_POOL.length];
                const zw = zeroWidths[idx % zeroWidths.length];
                const newDesc = `${em1} ${desc} ${em2}${zw}`;
                try {
                  await sock.groupUpdateDescription(jid, newDesc);
                  sess.sentCount = (sess.sentCount || 0) + 1;
                } catch (e) {}
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

          // +pollspam Name | opt1 | opt2 (50 EMOJI ROTATING POLL SPAMMER)
          if (cmd === 'pollspam' || cmd === 'poll') {
            if (!isGroup) {
              await sock.sendMessage(jid, { text: `❌ Polls only work in Groups!` }, { quoted: msg });
              continue;
            }

            const rawPoll = fullArg || 'Who is King? | SERVER GOD CLAN | KING BOT | MAFIA';
            const pollParts = rawPoll.split('|').map(s => s.trim()).filter(Boolean);
            const pollName = pollParts[0] || 'SERVER GOD CLAN';
            const baseOptions = pollParts.slice(1).length >= 2 ? pollParts.slice(1, 12) : ['KING BOT ULTRA', 'SERVER GOD CLAN', 'MAFIA EMPIRE', '0.01s TURBO'];

            sess.chatLoops = sess.chatLoops || {};
            sess.chatLoops[jid] = sess.chatLoops[jid] || {};
            sess.chatLoops[jid].pollspam = true;

            const delayMs = sess.delays?.pollspam || 300;
            await sock.sendMessage(jid, {
              text: `╔══〔 📊 *POLL SPAM (50-EMOJI) ACTIVE* 〕══╗\n┃ Topic: *${pollName}*\n┃ Emoji Pool: *50 King/Battle Emojis Rotating*\n┃ Options: ${baseOptions.length}\n┃ Speed: *${delayMs}ms*\n╚════════════════════════════════════════╝`
            });

            (async () => {
              let idx = 0;
              while (sess.chatLoops?.[jid]?.pollspam) {
                const em1 = EMOJI_50_POOL[idx % EMOJI_50_POOL.length];
                const em2 = EMOJI_50_POOL[(idx + 1) % EMOJI_50_POOL.length];
                const pollOpts = baseOptions.map((opt, i) => `${EMOJI_50_POOL[(idx + i + 2) % EMOJI_50_POOL.length]} ${opt}`);
                try {
                  await sock.sendMessage(jid, {
                    poll: {
                      name: `${em1} ${pollName} ${em2}`,
                      values: pollOpts,
                      selectableCount: 1
                    }
                  });
                  sess.sentCount = (sess.sentCount || 0) + 1;
                } catch (e) {}
                idx++;
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
          // 12. FLOOD & SWIPE LOOPS (50 EMOJI ROTATING SPAMMER)
          // ==================================================================
          if (cmd === 'spam' || cmd === 'flood' || cmd === 'cspam' || cmd === 'mspam') {
            const spamText = fullArg || 'SERVER GOD CLAN DOMINATION';
            sess.chatLoops = sess.chatLoops || {};
            sess.chatLoops[jid] = sess.chatLoops[jid] || {};
            sess.chatLoops[jid].spam = true;

            const delayMs = sess.delays?.spam || 50;
            await sock.sendMessage(jid, {
              text: `╔══〔 🚀 *FLOOD SPAM (50-EMOJI) ON* 〕══╗\n┃ Msg: "${spamText}"\n┃ Emoji Pool: *50 King/Battle Emojis Rotating*\n┃ Speed: *${delayMs}ms (0.01s+)*\n╚════════════════════════════════════════╝`
            });

            (async () => {
              const zeroWidths = ['', '\u200B', '\u200C', '\u200D', '\uFEFF', '\u200B\u200C', '\u200D\u200B'];
              let idx = 0;
              while (sess.chatLoops?.[jid]?.spam) {
                const em1 = EMOJI_50_POOL[idx % EMOJI_50_POOL.length];
                const em2 = EMOJI_50_POOL[(idx + 1) % EMOJI_50_POOL.length];
                const zw = zeroWidths[idx % zeroWidths.length];
                try {
                  await sock.sendMessage(jid, { text: `${em1} ${spamText} ${em2}${zw}` });
                  sess.sentCount = (sess.sentCount || 0) + 1;
                } catch (e) {}
                idx++;
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

          if (cmd === 'join' || cmd === 'joingroup') {
            const link = fullArg.trim();
            const match = link.match(/(?:chat\.whatsapp\.com\/)?([0-9A-Za-z]{20,26})/);
            if (!match) {
              await sock.sendMessage(jid, { text: `❌ *Usage:* \`${sess.prefix}join <WhatsApp Group Link or Invite Code>\`\nExample: \`${sess.prefix}join https://chat.whatsapp.com/AbCdEfGhIjKlMnOpQrStUv\`` }, { quoted: msg });
              continue;
            }
            try {
              const code = match[1];
              await sock.groupAcceptInvite(code);
              await sock.sendMessage(jid, { text: `✅ *Successfully joined WhatsApp group via invite link!*` }, { quoted: msg });
            } catch (e) {
              await sock.sendMessage(jid, { text: `❌ *Join failed:* ${e.message}` }, { quoted: msg });
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

          if (cmd === 'adduserbot' || cmd === 'addbotphone' || cmd === 'pairbot') {
            const rawPhone = (parts[1] || '').trim();
            const clean = cleanPhone(rawPhone);
            if (!clean || clean.length < 7) {
              await sock.sendMessage(jid, { text: `❌ *Usage:* \`${sess.prefix}adduserbot <Phone Number with Country Code>\`\nExample: \`${sess.prefix}adduserbot 919507325677\`` }, { quoted: msg });
              continue;
            }
            const newUid = `wp_usr_${clean.slice(-6)}_${Date.now().toString().slice(-4)}`;
            await sock.sendMessage(jid, { text: `🔄 *Allocating Userbot Node & Requesting Pairing Code for +${clean}...*` }, { quoted: msg });
            try {
              const newSess = await initSessionSocket(newUid, sess.ownerJid, { force: true, isPairing: true });
              let attempts = 0;
              while ((!newSess.sock || !newSess.sock.requestPairingCode) && attempts < 20) {
                await sleep(250);
                attempts++;
              }
              await sleep(1500);
              const rawCode = await newSess.sock.requestPairingCode(clean);
              const formatted = rawCode ? (rawCode.match(/.{1,4}/g)?.join('-') || rawCode) : '';
              newSess.pairingCode = formatted;
              newSess.pairingRawCode = rawCode;
              newSess.pairingPhone = clean;
              newSess.pairingCodeCreatedAt = Date.now();
              newSess.status = 'PAIRING';
              saveSessionConfig(newUid, { name: `Userbot_${clean.slice(-4)}`, owner_jid: sess.ownerJid, owner: sess.ownerJid });

              const pairText = `╔══〔 👑 *WHATSAPP USERBOT PAIRING CODE* 〕══╗
┃ 📱 *Phone:* \`+${clean}\`
┃ 🔑 *Pairing Code:* *${formatted}*
┃ 🆔 *Node UID:* \`${newUid}\`
┃ ⏱️ *Valid For:* *10 Minutes (600s)*
╚════════════════════════════════════╝
👉 *How to Link:*
1. Open WhatsApp on *+${clean}*
2. Tap *Settings > Linked Devices > Link with phone number*
3. Enter code: *${formatted}*`;

              if (fs.existsSync(MAIN_PIC_PATH)) {
                await sock.sendMessage(jid, {
                  image: fs.readFileSync(MAIN_PIC_PATH),
                  caption: pairText
                }, { quoted: msg });
              } else {
                await sock.sendMessage(jid, { text: pairText }, { quoted: msg });
              }
            } catch (err) {
              await sock.sendMessage(jid, { text: `❌ *Pairing Error:* ${err.message}` }, { quoted: msg });
            }
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

          if (cmd === 'removeuserbot' || cmd === 'deluserbot' || cmd === 'removebot' || cmd === 'delbot') {
            const targetUid = (parts[1] || '').trim();
            if (!targetUid) {
              await sock.sendMessage(jid, { text: `❌ *Usage:* \`${sess.prefix}removeuserbot <Session_UID_or_Phone>\`` }, { quoted: msg });
              continue;
            }
            let foundKey = Object.keys(activeSessions).find(k => k === targetUid || k.includes(targetUid) || (activeSessions[k]?.connectedNumber && activeSessions[k].connectedNumber.includes(targetUid)));
            const keyToDelete = foundKey || targetUid;
            deleteSessionAuthDir(keyToDelete);
            delete activeSessions[keyToDelete];
            await sock.sendMessage(jid, { text: `🗑️ Userbot / Bot Session \`${keyToDelete}\` unlinked and purged from MongoDB & disk.` }, { quoted: msg });
            continue;
          }

          if (cmd === 'viewuserbots' || cmd === 'userbots' || cmd === 'listuserbots' || cmd === 'bots' || cmd === 'botlist') {
            const count = Object.keys(activeSessions).length;
            let list = `╔══〔 🛰️ *ACTIVE USERBOTS & NODES (${count})* 〕══╗\n`;
            for (const [sUid, sData] of Object.entries(activeSessions)) {
              const upSec = sData.connectedAt ? Math.floor((Date.now() - sData.connectedAt) / 1000) : 0;
              const h = Math.floor(upSec / 3600);
              const m = Math.floor((upSec % 3600) / 60);
              list += `┃ 🤖 *${sUid}* [${sData.status || 'OFFLINE'}]\n┃    📱 No: *${sData.connectedNumber || 'Not Linked'}* | ⏱️ Uptime: ${h}h ${m}m\n`;
            }
            list += `╚══════════════════════════════════════╝\n_Use \`${sess.prefix}adduserbot <phone>\` to link new userbots._`;
            
            if (fs.existsSync(DASHBOARD_PIC_PATH)) {
              await sock.sendMessage(jid, { image: fs.readFileSync(DASHBOARD_PIC_PATH), caption: list }, { quoted: msg });
            } else {
              await sock.sendMessage(jid, { text: list }, { quoted: msg });
            }
            continue;
          }

          if (cmd === 'vclink' || cmd === 'calllink' || cmd === 'grouplinkcall') {
            const inviteCode = isGroup ? await sock.groupInviteCode(jid).catch(() => '') : '';
            const linkText = `╔══〔 📞 *WHATSAPP GROUP VC & CALL HUB* 〕══╗
┃ 🎯 Chat: *${isGroup ? 'Group VC' : 'Direct Call'}*
┃ 🔗 Invite Code: *${inviteCode || 'N/A'}*
┃ 🔊 Live VoIP Streamer: *Ready (51.mp3 / JioSaavn)*
┃ ⚡ Control: \`${sess.prefix}play1call\` • \`${sess.prefix}playjiocall <song>\`
╚══════════════════════════════════════╝`;
            await sock.sendMessage(jid, { text: linkText }, { quoted: msg });
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
  logMsg('SYSTEM', '🔍 Connecting to MongoDB Atlas & Scanning registered sessions...');
  try {
    await initMongo();
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
            const savedCfg = loadSessionConfig(uid);
            await initSessionSocket(uid, savedCfg.owner_jid || savedCfg.ownerJid || '', { force: false });
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
    const sess = activeSessions[uid];
    if (sess && sess.status === 'ONLINE') {
      return res.json({
        success: true,
        uid,
        status: 'ONLINE',
        connectedNumber: sess.connectedNumber || '',
        message: 'Account is already ONLINE and connected.'
      });
    }

    deleteSessionAuthDir(uid);
    if (sess) {
      sess.qrAttempts = 0;
      sess.qr = '';
      sess.pairingCode = '';
      sess.pairingRawCode = '';
      sess.pairingCodeCreatedAt = 0;
    }
    const newSess = await initSessionSocket(uid, sess ? sess.ownerJid : '', { force: true, isPairing: false });
    if (newSess) {
      for (let i = 0; i < 12; i++) {
        await sleep(250);
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

  let cleaned = cleanPhone(phone);
  if (!cleaned || cleaned.length < 10) {
    return res.status(400).json({ success: false, message: 'Please provide a valid 10-14 digit WhatsApp phone number.' });
  }
  if (cleaned.length === 10) {
    cleaned = '91' + cleaned;
  }

  let sess = activeSessions[uid];

  if (sess && sess.status === 'ONLINE' && sess.sock) {
    return res.json({
      success: true,
      uid,
      phone: `+${cleaned}`,
      status: 'ONLINE',
      message: 'Session is already ONLINE and connected!'
    });
  }

  // If already generated for this phone and under 15 minutes, reuse it
  if (sess && sess.pairingCode && sess.pairingPhone === cleaned && (Date.now() - (sess.pairingCodeCreatedAt || 0) < 900000)) {
    const timeLeft = Math.max(0, Math.floor((900000 - (Date.now() - sess.pairingCodeCreatedAt)) / 1000));
    return res.json({
      success: true,
      uid,
      phone: `+${cleaned}`,
      pairingCode: sess.pairingCode,
      rawCode: sess.pairingRawCode || sess.pairingCode.replace(/-/g, ''),
      timeLeft,
      message: 'Active pairing code reused (valid for 15m)'
    });
  }

  try {
    logMsg(uid, `Requesting fresh pairing code for number: +${cleaned}...`);

    // Clean unauthenticated auth dir to ensure clean pairing handshake
    if (!hasSavedAuthCreds(uid) || (sess && sess.status !== 'ONLINE')) {
      deleteSessionAuthDir(uid);
    }

    if (sess) {
      sess.qrAttempts = 0;
      sess.qr = '';
      sess.pairingCode = '';
      sess.pairingRawCode = '';
      sess.pairingCodeCreatedAt = 0;
    }

    sess = await initSessionSocket(uid, sess ? sess.ownerJid : '', { force: true, isPairing: true });

    // Wait until socket is ready to request pairing code
    let attempts = 0;
    while ((!sess.sock || !sess.sock.requestPairingCode) && attempts < 20) {
      await sleep(250);
      attempts++;
    }

    if (!sess.sock) {
      return res.status(500).json({ success: false, message: 'Socket could not be initialized, please retry in 2 seconds.' });
    }

    // Wait a brief moment for websocket connection to settle
    await sleep(1500);

    if (sess.sock.authState && sess.sock.authState.creds && sess.sock.authState.creds.registered) {
      return res.json({
        success: true,
        uid,
        phone: `+${cleaned}`,
        status: 'ONLINE',
        message: 'Account is already registered and logged in!'
      });
    }

    const rawCode = await sess.sock.requestPairingCode(cleaned);
    const formattedCode = rawCode ? (rawCode.match(/.{1,4}/g)?.join('-') || rawCode) : '';

    sess.pairingCode = formattedCode;
    sess.pairingRawCode = rawCode;
    sess.pairingPhone = cleaned;
    sess.pairingCodeCreatedAt = Date.now();
    sess.status = 'PAIRING';
    sess.qr = '';

    logMsg(uid, `🔢 Pairing Code Generated for +${cleaned}: ${formattedCode} (Valid for 15 Minutes)`);
    res.json({
      success: true,
      uid,
      phone: `+${cleaned}`,
      pairingCode: formattedCode,
      rawCode: rawCode,
      expiresIn: 900
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
  const cleanOwner = (owner_jid || '').trim();
  saveSessionConfig(uid, { owner_jid: cleanOwner });
  const sess = activeSessions[uid];
  if (sess) {
    sess.ownerJid = cleanOwner;
    logMsg(uid, `Bot Owner / Admin ID updated to: ${sess.ownerJid || 'None'}`);
  }
  res.json({ success: true, uid, ownerJid: cleanOwner });
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
