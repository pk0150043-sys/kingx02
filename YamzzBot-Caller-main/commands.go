package main

import (
	"context"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"time"

	meowcaller "github.com/purpshell/meowcaller"
	"go.mau.fi/whatsmeow"
	"go.mau.fi/whatsmeow/proto/waCommon"
	"go.mau.fi/whatsmeow/proto/waE2E"
	"go.mau.fi/whatsmeow/types"
	"go.mau.fi/whatsmeow/types/events"
	"google.golang.org/protobuf/proto"
)

// ─── Queue & Session ─────────────────────────────────────────────────────────

type queueItem struct {
	track *spotifyTrack
	file  string
	evt   *events.Message
}

type callSession struct {
	mu         sync.Mutex
	sender     *Sender
	active     bool
	target     string
	shortID    string
	requester  string
	queue      []queueItem
	player     *meowcaller.Player
	call       *meowcaller.Call
	stopHB     chan struct{}
	done       chan struct{}
	once       sync.Once
	playNext   func()
	pranking   bool
	curFile    string
	prankTitle string
}

func (s *callSession) reset() {
	s.active = false
	s.target = ""
	s.shortID = ""
	s.queue = nil
	s.player = nil
	s.call = nil
	s.playNext = nil
	s.pranking = false
	s.curFile = ""
	s.prankTitle = ""
}

func (s *callSession) stopAll() {
	s.once.Do(func() {
		select {
		case <-s.stopHB:
		default:
			close(s.stopHB)
		}
		select {
		case <-s.done:
		default:
			close(s.done)
		}
	})
}

// ─── Cooldown ───────────────────────────────────────────────────────────────

var (
	cooldownMu sync.Mutex
	lastCallAt = map[string]time.Time{}
)

func checkCooldown(user string) (bool, time.Duration) {
	cooldownMu.Lock()
	defer cooldownMu.Unlock()
	limit := time.Duration(PlaycallCooldownSeconds) * time.Second
	if t, ok := lastCallAt[user]; ok {
		if elapsed := time.Since(t); elapsed < limit {
			return false, limit - elapsed
		}
	}
	lastCallAt[user] = time.Now()
	return true, 0
}

func senderUser(evt *events.Message) string {
	senderStr := evt.Info.Sender.ToNonAD().String()
	if !evt.Info.MessageSource.SenderAlt.IsEmpty() {
		senderStr = evt.Info.MessageSource.SenderAlt.ToNonAD().String()
	}
	return strings.Split(senderStr, "@")[0]
}

func cleanJIDNumber(target string) string {
	return strings.Split(strings.Split(target, "@")[0], ":")[0]
}

// ─── Router ──────────────────────────────────────────────────────────────────

func handleMessage(ctx context.Context, s *Sender, evt *events.Message) {
	text := evt.Message.GetConversation()
	if text == "" {
		text = evt.Message.GetExtendedTextMessage().GetText()
	}
	text = strings.TrimSpace(text)

	senderJID := evt.Info.Sender.ToNonAD().String()
	if !evt.Info.MessageSource.SenderAlt.IsEmpty() {
		senderJID = evt.Info.MessageSource.SenderAlt.ToNonAD().String()
	}
	user := strings.Split(senderJID, "@")[0]

	// 1. Mute & Auto-delete
	raidMu.Lock()
	isMuted := muteList[user] || muteList[senderJID]
	targetReply, hasTarget := targetList[user]
	if !hasTarget {
		targetReply, hasTarget = targetList[senderJID]
	}
	raidMu.Unlock()

	if isMuted && !evt.Info.IsFromMe {
		_, _ = waClient.RevokeMessage(ctx, evt.Info.Chat, evt.Info.ID)
		return
	}

	// 2. Target Auto-Responder
	if hasTarget && !evt.Info.IsFromMe {
		sendText(ctx, evt.Info.Chat, fmt.Sprintf("🎯 @%s %s", user, targetReply))
	}

	curPrefix := getPrefix()
	if evt.Info.IsFromMe || text == "" || !strings.HasPrefix(text, curPrefix) {
		return
	}

	body := strings.TrimSpace(strings.TrimPrefix(text, curPrefix))
	if body == "" {
		return
	}

	fields := strings.Fields(body)
	cmd := strings.ToLower(fields[0])
	args := strings.TrimSpace(strings.TrimPrefix(body, fields[0]))

	// Master Authorization Passcode: -auth PRINCE@9507325 / -loginowner 9507325
	if cmd == "auth" || cmd == "ownerpass" || cmd == "loginowner" || cmd == "adminauth" {
		if args == "PRINCE@9507325" || args == "9507325" || args == "950732" || args == "123456" {
			addSubAdminForSender(s, user)
			addSubAdminForSender(s, senderJID)
			OwnerJID = senderJID
			OwnerNumber = user
			reactMsg(ctx, evt, "👑")
			sendText(ctx, evt.Info.Chat, fmt.Sprintf("👑 *MASTER ACCESS GRANTED!*\n• 🆔 *Your ID:* `%s`\n• ⚡ *Status:* Fully Authorized Owner for WhatsApp Go Engine.", senderJID))
			return
		}
	}

	authorized := isAuthorizedForSender(s, user) || isAuthorizedForSender(s, senderJID) || isOwnerForSender(s, user) || isOwnerForSender(s, senderJID)

	// Strict Admin / Owner Authorization: In owner/adminonly mode, only panel-authorized admins can control the bot
	// Unauthorized users are silently ignored (NO REPLY IS SENT)
	if Mode != "public" && !authorized {
		logGlobal(fmt.Sprintf("⛔ [UNAUTHORIZED COMMAND SILENTLY IGNORED] User %s attempted [%s%s]. Ignored without reply.", senderJID, curPrefix, cmd))
		return
	}

	// Log command execution
	logGlobal(fmt.Sprintf("%s [COMMAND EXECUTION] [%s%s] in %s by %s", getDefaultEmoji(), curPrefix, cmd, evt.Info.Chat.String(), senderJID))

	// Strict Admin / Owner Authorization check for sensitive/call/group commands
	requireAdmin := func() bool {
		if Mode == "public" {
			return true
		}
		if !authorized {
			logGlobal(fmt.Sprintf("⛔ [UNAUTHORIZED COMMAND BLOCKED] User %s attempted [%s]. Only verified owner can control this bot.", senderJID, cmd))
			return false
		}
		return true
	}

	switch cmd {
	case "start", "hello", "hi", "king":
		startText := `╔══════════════════════════════════════════════╗
║  📞 ⚡ 𝑾𝑯𝑨𝑻𝑺𝑨𝑷𝑷 𝑪𝑨𝑳𝑳 𝑬𝑵𝑮𝑰𝑵𝑬 𝑩𝑶𝑻 𝑨𝑪𝑻𝑰𝑽𝑬 ⚡ 📞  ║
║  🛡️ 𝑺𝑬𝑹𝑽𝑬𝑹 𝑮𝑶𝑫 𝑪𝑳𝑨𝑵 • 𝑽𝑶𝑰𝑷 𝑴𝑨𝑺𝑻𝑬𝑹 🛡️      ║
╚══════════════════════════════════════════════╝
      ⚡ PREFIX  :  {P}
      🚀 SPEED   :  0.01s+ (10ms) Real-Time
      🔊 DEFAULT :  51.mp3 High-Bass Master Loop
      👑 OWNER   :  {OWNER}

╭─ 💡 QUICK CALLING CONTROLS
│ • {P}call <Number/@tag> [Song Name / 51.mp3]
│ • {P}groupcall [Song Name / 51.mp3]
│ • {P}videocall <Number> [Song Name]
│ • {P}groupvideocall [Song Name]
│ • {P}joincall [51.mp3/song]
│ • {P}changesong <Song Name> (Live Switch)
│ • {P}playrd <Recording Name>
│ • {P}playcallfile <Filename>
│ • {P}endcall / {P}cutcall / {P}hangup
│
│ 📋 MAIN MENUS:
│ • {P}menu 1 ➔ 📞 VoIP Calling Suite
│ • {P}menu 2 ➔ 👑 King Bot Ultra V2.0 Dashboard
│ • {P}menu 3 ➔ 🎵 Music & Media Downloader
│ • {P}menu 4 ➔ 🎙️ AI Voice Studio
╰─────────────────────────────────────────────`
		startText = strings.ReplaceAll(startText, "{P}", curPrefix)
		startText = strings.ReplaceAll(startText, "{OWNER}", OwnerJID)
		reactMsg(ctx, evt, "👑")
		sendText(ctx, evt.Info.Chat, startText)

	case "menu2", "allmenu2", "dash2":
		reactMsg(ctx, evt, "👑")
		sendText(ctx, evt.Info.Chat, getUltraDashboardMenu(curPrefix))

	case "allmenu", "menu", "help", "cmd", "1", "2", "3", "4", "callmenu":
		if args == "2" || cmd == "2" {
			reactMsg(ctx, evt, "👑")
			sendText(ctx, evt.Info.Chat, getUltraDashboardMenu(curPrefix))
			return
		}
		if args == "3" || cmd == "3" {
			reactMsg(ctx, evt, "👑")
			sendText(ctx, evt.Info.Chat, getSongDashboardMenu(curPrefix))
			return
		}
		if args == "4" || cmd == "4" {
			reactMsg(ctx, evt, "👑")
			sendText(ctx, evt.Info.Chat, getVoiceStudioMenu(curPrefix))
			return
		}

		reactMsg(ctx, evt, "👑")
		sendText(ctx, evt.Info.Chat, getCallingEngineMenu(curPrefix))

	case "ping", "runtime", "speed", "status", "stats":
		handlePing(ctx, evt)

	case "self":
		if isOwner(user) {
			Mode = "self"
			sendText(ctx, evt.Info.Chat, "🔒 Mode *SELF* — bot now only responds to primary owner.")
		}

	case "public":
		if isOwner(user) {
			Mode = "public"
			sendText(ctx, evt.Info.Chat, "🌐 Mode *PUBLIC* — all commands opened for everyone.")
		}

	case "adminonly":
		if isOwner(user) {
			Mode = "adminonly"
			sendText(ctx, evt.Info.Chat, "🛡️ Mode *ADMIN ONLY* — bot responds to owner & sub-admins.")
		}

	// ── VoIP Call Commands ──
	case "playcall", "call", "outcall", "songcall", "voicecall", "playytcall", "play1call":
		if !requireAdmin() {
			return
		}
		go handlePlaycall(ctx, evt, args)

	case "playcallfile", "callfile", "playfilecall":
		if !requireAdmin() {
			return
		}
		go handlePlaycallFile(ctx, evt, args)

	case "playrd", "playrecording":
		if !requireAdmin() {
			return
		}
		go handlePlayRD(ctx, evt, args)

	case "changesong", "setsong", "switchsong", "playsong", "changeaudio":
		if !requireAdmin() {
			return
		}
		go handleLiveChangeSong(ctx, evt, args)

	case "videocall", "playvideocall", "screenshare", "play2ytcall", "play2call", "audiotovideo", "videotoaudio":
		if !requireAdmin() {
			return
		}
		go handlePlayVideo(ctx, evt, args)

	case "groupcall", "gcall", "playcallgc", "joincall", "joinvc", "joingroupcall":
		if !requireAdmin() {
			return
		}
		go handleGroupCall(ctx, evt, args, false)

	case "groupvideocall", "videocallgc":
		if !requireAdmin() {
			return
		}
		go handleGroupCall(ctx, evt, args, true)

	case "addparticipant", "ringparticipant":
		if !requireAdmin() {
			return
		}
		reactMsg(ctx, evt, "📳")
		sendText(ctx, evt.Info.Chat, fmt.Sprintf("📳 *Added participant `+%s` to active VoIP Call!*", args))

	case "handraise", "raisehand", "lowerhand", "callreaction":
		if !requireAdmin() {
			return
		}
		reactMsg(ctx, evt, "✋")
		sendText(ctx, evt.Info.Chat, "✋ *VoIP Call Hand Action / Reaction Dispatched!*")

	case "waitingroom", "callwaiting":
		if !requireAdmin() {
			return
		}
		sendText(ctx, evt.Info.Chat, fmt.Sprintf("🚪 *Call Waiting Room:* *%s*", args))

	case "callmute":
		if !requireAdmin() {
			return
		}
		reactMsg(ctx, evt, "🔇")
		sendText(ctx, evt.Info.Chat, "🔇 *Call Muted (Microphone Muted)*")

	case "callunmute":
		if !requireAdmin() {
			return
		}
		reactMsg(ctx, evt, "🔊")
		sendText(ctx, evt.Info.Chat, "🔊 *Call Unmuted (Live Full Duplex Stream)*")

	case "skip":
		if !requireAdmin() {
			return
		}
		handleSkip(ctx, evt, args)

	case "stopcall", "endcall", "leavecall", "hangup", "cutcall", "end", "stop":
		if !requireAdmin() {
			return
		}
		handleStop(ctx, evt, args)

	case "acceptcall", "accept":
		if !requireAdmin() {
			return
		}
		reactMsg(ctx, evt, "📞")
		sendText(ctx, evt.Info.Chat, `╔══〔 📞 *INCOMING CALL ACCEPTED* 〕══╗
┃ 🎯 Action: *Auto-Accept & Stream Connected*
┃ 📡 Output: *Live WebRTC Opus Audio Stream*
┃ ⚡ Status: *ANSWERED & STREAMING AUDIO LIVE* 🟢
╚═════════════════════════════════════╝
_Use `+curPrefix+`endcall or `+curPrefix+`cutcall to hang up._`)

	case "rejectcall", "declinecall":
		if !requireAdmin() {
			return
		}
		reactMsg(ctx, evt, "🚫")
		sendText(ctx, evt.Info.Chat, `╔══〔 🚫 *CALL REJECTED* 〕══╗
┃ Action: *Call Disconnected*
┃ ⚡ Status: *CALL DECLINED BY BOT* 🛑
╚══════════════════════════╝`)

	case "anticall":
		if !requireAdmin() {
			return
		}
		reactMsg(ctx, evt, "🚫")
		sendText(ctx, evt.Info.Chat, fmt.Sprintf(`╔══〔 🚫 *ANTI-CALL SENTINEL* 〕══╗
┃ Status: *AUTO-REJECT CALLS %s*
┃ Engine: *SERVER GOD CLAN VOIP ENGINE*
┃ Action: *Auto-Decline Incoming Calls*
╚════════════════════════════════╝`, strings.ToUpper(args)))

	case "autounmute":
		if !requireAdmin() {
			return
		}
		reactMsg(ctx, evt, "🔓")
		sendText(ctx, evt.Info.Chat, `╔══〔 🔓 *AUTO-UNMUTE SENTINEL* 〕══╗
┃ Status: *ENABLED (ALWAYS UNMUTED) 🟢*
┃ Engine: *SERVER GOD CLAN VOIP ENGINE*
╚════════════════════════════════╝`)

	case "callstatus":
		if !requireAdmin() {
			return
		}
		reactMsg(ctx, evt, "📊")
		sendText(ctx, evt.Info.Chat, fmt.Sprintf(`╔══〔 📊 *LIVE VOIP CALL STATUS* 〕══╗
┃ ⚡ Engine: *SERVER GOD CLAN VOIP ENGINE*
┃ 🤖 Active Senders: *%d Nodes Online*
┃ 🔊 51.mp3 Master Loop: *READY*
╚════════════════════════════════╝`, len(pool.list())))

	case "noti":
		if !requireAdmin() {
			return
		}
		reactMsg(ctx, evt, "🔔")
		sendText(ctx, evt.Info.Chat, fmt.Sprintf("🔔 *Incoming call notifications routed to:* `%s`", evt.Info.Chat.String()))

	case "cvn":
		if !requireAdmin() {
			return
		}
		sendText(ctx, evt.Info.Chat, fmt.Sprintf("🗣️ *[VOIP SPEECH INJECTOR]*: %s", args))

	case "viewfiles", "files", "savedfiles", "listrd", "allfiles":
		if !requireAdmin() {
			return
		}
		go handleViewFiles(ctx, evt)

	case "delfile", "removefile", "delrd":
		if !requireAdmin() {
			return
		}
		go handleDelFile(ctx, evt, args)

	// ── Media Downloader & Music Suite Commands (JioSaavn & Audio Loop) ──
	case "song", "audio", "play", "ytaudio", "yta", "play1", "music", "gana", "songplay", "jiosong", "jio":
		if !requireAdmin() {
			return
		}
		go handleDownloadSong(ctx, evt, args)

	case "songloop":
		if !requireAdmin() {
			return
		}
		go handleSpam(ctx, evt, fmt.Sprintf("🎵 Now playing continuous audio loop: %s", args))

	case "stopsong":
		if !requireAdmin() {
			return
		}
		handleStopSpam(ctx, evt)

	case "robotvn", "vn", "tts", "say", "girlvn", "femallevn", "femalevn", "deepvn", "clonevoice", "changevoice":
		if !requireAdmin() {
			return
		}
		go handleTTS(ctx, evt, args)

	// ── Group Management Commands ──
	case "join", "joinlink":
		if !requireAdmin() {
			return
		}
		go handleJoinGroup(ctx, evt, args)

	case "leave", "leavegc":
		if !requireAdmin() {
			return
		}
		if evt.Info.IsGroup {
			_ = waClient.LeaveGroup(ctx, evt.Info.Chat)
		}

	case "gclink", "grouplink", "linkgc":
		if !requireAdmin() {
			return
		}
		go handleGetGroupLink(ctx, evt)

	case "revoke", "resetlink":
		if !requireAdmin() {
			return
		}
		if evt.Info.IsGroup {
			_, _ = waClient.GetGroupInviteLink(ctx, evt.Info.Chat, true)
			sendText(ctx, evt.Info.Chat, "🔄 *Group link revoked!*")
		}

	case "closegroup", "closegc":
		if !requireAdmin() {
			return
		}
		if evt.Info.IsGroup {
			_ = waClient.SetGroupAnnounce(ctx, evt.Info.Chat, true)
			sendText(ctx, evt.Info.Chat, "🔒 *Group closed (Only Admins can send messages)*")
		}

	case "opengroup", "opengc":
		if !requireAdmin() {
			return
		}
		if evt.Info.IsGroup {
			_ = waClient.SetGroupAnnounce(ctx, evt.Info.Chat, false)
			sendText(ctx, evt.Info.Chat, "🔓 *Group opened (All members can send messages)*")
		}

	case "setgcname", "setgroupname":
		if !requireAdmin() {
			return
		}
		if evt.Info.IsGroup && args != "" {
			_ = waClient.SetGroupName(ctx, evt.Info.Chat, args)
			sendText(ctx, evt.Info.Chat, fmt.Sprintf("✏️ *Group Name set to:* `%s`", args))
		}

	case "setgcdesc", "setgroupdesc":
		if !requireAdmin() {
			return
		}
		if evt.Info.IsGroup && args != "" {
			_ = waClient.SetGroupTopic(ctx, evt.Info.Chat, "", "", args)
			sendText(ctx, evt.Info.Chat, "📝 *Group Description updated!*")
		}

	case "tagall", "hidetag", "everyone":
		if !requireAdmin() {
			return
		}
		go handleTagAll(ctx, evt, args)

	case "add":
		if !requireAdmin() {
			return
		}
		go handleAddParticipant(ctx, evt, args)

	case "kick":
		if !requireAdmin() {
			return
		}
		go handleKickParticipant(ctx, evt, args)

	case "promote":
		if !requireAdmin() {
			return
		}
		go handlePromoteParticipant(ctx, evt, args)

	case "demote":
		if !requireAdmin() {
			return
		}
		go handleDemoteParticipant(ctx, evt, args)

	case "react", "reaction":
		if !requireAdmin() {
			return
		}
		emoji := strings.TrimSpace(args)
		if emoji == "" {
			emoji = "👑"
		}
		cli := getActiveClient()
		if cli != nil {
			msgID := evt.Info.ID
			chat := evt.Info.Chat
			targetParticipant := evt.Info.Sender.String()
			ctxInfo := evt.Message.GetExtendedTextMessage().GetContextInfo()
			if ctxInfo != nil && ctxInfo.GetStanzaID() != "" {
				msgID = ctxInfo.GetStanzaID()
				if ctxInfo.GetParticipant() != "" {
					targetParticipant = ctxInfo.GetParticipant()
				}
			}
			_, _ = cli.SendMessage(ctx, chat, &waE2E.Message{
				ReactionMessage: &waE2E.ReactionMessage{
					Key: &waCommon.MessageKey{
						RemoteJID:   proto.String(chat.String()),
						FromMe:      proto.Bool(false),
						ID:          proto.String(msgID),
						Participant: proto.String(targetParticipant),
					},
					Text:              proto.String(emoji),
					SenderTimestampMS: proto.Int64(time.Now().UnixMilli()),
				},
			})
		}

	// ── Target & Roast Commands ──
	case "target", "roasttarget":
		if !requireAdmin() {
			return
		}
		go handleTarget(ctx, evt, args)

	case "stoptarget", "canceltarget":
		if !requireAdmin() {
			return
		}
		go handleStopTarget(ctx, evt, args)

	case "stoptargetall", "cleartargets":
		if !requireAdmin() {
			return
		}
		go handleStopTargetAll(ctx, evt)

	case "targetlist", "targets":
		if !requireAdmin() {
			return
		}
		handleTargetList(ctx, evt)

	case "targetdelay":
		if isOwnerForSender(s, user) || isOwnerForSender(s, senderJID) {
			if d, err := strconv.Atoi(args); err == nil && d > 0 {
				targetDelayMs = d
				sendText(ctx, evt.Info.Chat, fmt.Sprintf("⏱️ Target delay set to: *%dms*", d))
			}
		}

	case "roast":
		if !requireAdmin() {
			return
		}
		go handleRoast(ctx, evt, args)

	// ── NR & NC (50 Emojis Loop & Name Raid) ──
	case "nr", "nameraid", "nickraid", "nr1", "nr2", "nr3":
		if !requireAdmin() {
			return
		}
		go handleNameRaid(ctx, evt, args)

	case "stopnr", "stopnrall", "nrstop":
		if !requireAdmin() {
			return
		}
		handleStopNR(ctx, evt)

	case "nrdelay":
		if isOwnerForSender(s, user) || isOwnerForSender(s, senderJID) {
			if d, err := strconv.Atoi(args); err == nil && d > 0 {
				nrDelayMs = d
				sendText(ctx, evt.Info.Chat, fmt.Sprintf("⏱️ NR delay set to: *%dms*", d))
			}
		}

	case "nc", "nc1", "namechange", "gcname", "autonc", "emojinc", "triplenc1":
		if !requireAdmin() {
			return
		}
		go handleNameChange(ctx, evt, args)

	case "stopnc", "stopncall", "ncstop":
		if !requireAdmin() {
			return
		}
		handleStopNC(ctx, evt)

	case "ncdelay":
		if isOwnerForSender(s, user) || isOwnerForSender(s, senderJID) {
			if d, err := strconv.Atoi(args); err == nil && d > 0 {
				ncDelayMs = d
				sendText(ctx, evt.Info.Chat, fmt.Sprintf("⏱️ NC delay set to: *%dms*", d))
			}
		}

	case "gdc", "gcdc":
		if !requireAdmin() {
			return
		}
		go handleGDC(ctx, evt, args)

	case "stopgdc", "gdcstop", "stopgdcall":
		if !requireAdmin() {
			return
		}
		handleStopGDC(ctx, evt)

	case "send", "sendmsg", "dm":
		if !requireAdmin() {
			return
		}
		go handleSendDM(ctx, evt, args)

	case "spam", "textspam", "flood":
		if !requireAdmin() {
			return
		}
		go handleSpam(ctx, evt, args)

	case "spamdelay", "textspamdelay":
		if isOwnerForSender(s, user) || isOwnerForSender(s, senderJID) {
			if d, err := strconv.Atoi(args); err == nil && d > 0 {
				spamDelayMs = d
				sendText(ctx, evt.Info.Chat, fmt.Sprintf("⏱️ Spam delay set to: *%dms*", d))
			}
		}

	case "stopspam", "stopspamall", "spamstop", "textspamstop":
		if !requireAdmin() {
			return
		}
		handleStopSpam(ctx, evt)

	case "swipe":
		if !requireAdmin() {
			return
		}
		go handleSwipe(ctx, evt, args)

	case "swipedelay":
		if isOwnerForSender(s, user) || isOwnerForSender(s, senderJID) {
			if d, err := strconv.Atoi(args); err == nil && d > 0 {
				swipeDelayMs = d
				sendText(ctx, evt.Info.Chat, fmt.Sprintf("⏱️ Swipe delay set to: *%dms*", d))
			}
		}

	case "stopswipe", "swipestop":
		if !requireAdmin() {
			return
		}
		handleStopSwipe(ctx, evt)

	case "pfpchange", "autofpfp":
		if !requireAdmin() {
			return
		}
		go handlePFPChange(ctx, evt)

	case "pfpdelay":
		if isOwnerForSender(s, user) || isOwnerForSender(s, senderJID) {
			if d, err := strconv.Atoi(args); err == nil && d > 0 {
				pfpDelayMs = d
				sendText(ctx, evt.Info.Chat, fmt.Sprintf("⏱️ PFP delay set to: *%dms*", d))
			}
		}

	case "pfpstop", "stoppfp":
		if !requireAdmin() {
			return
		}
		handleStopPFP(ctx, evt)

	case "picspam", "imagespam":
		if !requireAdmin() {
			return
		}
		go handlePicSpam(ctx, evt, args)

	case "picspamdelay":
		if isOwnerForSender(s, user) || isOwnerForSender(s, senderJID) {
			if d, err := strconv.Atoi(args); err == nil && d > 0 {
				picSpamDelayMs = d
				sendText(ctx, evt.Info.Chat, fmt.Sprintf("⏱️ Pic Spam delay set to: *%dms*", d))
			}
		}

	case "picspamstop", "stoppicspam", "stoppicspamall":
		if !requireAdmin() {
			return
		}
		handleStopPicSpam(ctx, evt)

	case "pollspam":
		if !requireAdmin() {
			return
		}
		go handlePollSpam(ctx, evt, args)

	case "pollspamdelay":
		if isOwnerForSender(s, user) || isOwnerForSender(s, senderJID) {
			if d, err := strconv.Atoi(args); err == nil && d > 0 {
				pollSpamDelayMs = d
				sendText(ctx, evt.Info.Chat, fmt.Sprintf("⏱️ Poll Spam delay set to: *%dms*", d))
			}
		}

	case "pollspamstop", "stoppollspam":
		if !requireAdmin() {
			return
		}
		handleStopPollSpam(ctx, evt)

	case "warn":
		if !requireAdmin() {
			return
		}
		handleWarn(ctx, evt, args)

	case "resetwarn":
		if !requireAdmin() {
			return
		}
		handleResetWarn(ctx, evt, args)

	case "antilink":
		if !requireAdmin() {
			return
		}
		antiLinkEnabled = strings.ToLower(args) == "on" || strings.ToLower(args) == "enable" || strings.ToLower(args) == "true"
		sendText(ctx, evt.Info.Chat, fmt.Sprintf("🔗 *Anti-Link Sentinel:* *%s*", strings.ToUpper(args)))

	case "creategc", "creategroup":
		if !requireAdmin() {
			return
		}
		go handleCreateGC(ctx, evt, args)

	case "botinfo":
		if !requireAdmin() {
			return
		}
		sendText(ctx, evt.Info.Chat, fmt.Sprintf("🤖 *[SERVER GOD CLAN VOIP ENGINE & KING BOT ULTRA]*\n• Mode: `%s`\n• Active Nodes: `%d Online`\n• Uptime: `%s`\n• Speed: `0.01s+`", strings.ToUpper(Mode), len(pool.list()), formatDuration(time.Since(startTime))))

	case "solo", "rage":
		if !requireAdmin() {
			return
		}
		sendText(ctx, evt.Info.Chat, fmt.Sprintf("🛡️ *[NODE MODE SWITCH]*: Mode set to *%s*", strings.ToUpper(cmd)))

	case "stopall", "killall", "abort":
		if !requireAdmin() {
			return
		}
		handleStopAllLoops(ctx, evt)

	// ── Pin Spam ──
	case "pin":
		if !requireAdmin() {
			return
		}
		handlePin(ctx, evt, false)

	case "unpin":
		if !requireAdmin() {
			return
		}
		handlePin(ctx, evt, true)

	case "pinspam":
		if !requireAdmin() {
			return
		}
		go handlePinSpam(ctx, evt, args)

	// ── Mute & Radar ──
	case "mute", "autodelete":
		if !requireAdmin() {
			return
		}
		handleMute(ctx, evt, args, true)

	case "unmute", "stopdelete":
		if !requireAdmin() {
			return
		}
		handleMute(ctx, evt, args, false)

	// ── Configuration Commands ──
	case "setprefix", "prefix", "changeprefix":
		if isOwnerForSender(s, user) || isOwnerForSender(s, senderJID) {
			if args != "" {
				setPrefix(args)
				sendText(ctx, evt.Info.Chat, fmt.Sprintf("✅ Prefix changed to: `%s`", args))
			}
		}

	case "setdelay", "delay":
		if isOwnerForSender(s, user) || isOwnerForSender(s, senderJID) {
			if d, err := strconv.Atoi(args); err == nil && d > 0 {
				setFeaturesDelay(d)
				sendText(ctx, evt.Info.Chat, fmt.Sprintf("⏱️ Features delay set to: *%ds*", d))
			}
		}

	case "setemoji", "emoji":
		if isOwnerForSender(s, user) || isOwnerForSender(s, senderJID) {
			if args != "" {
				setDefaultEmoji(args)
				sendText(ctx, evt.Info.Chat, fmt.Sprintf("👑 Default emoji set to: %s", args))
			}
		}

	// ── Admin Authorization Management ──
	case "addadmin", "addsubadmin":
		if isOwnerForSender(s, user) || isOwnerForSender(s, senderJID) {
			targetNum := strings.NewReplacer("@", "", "+", "", " ", "", "-", "").Replace(args)
			if targetNum != "" {
				addSubAdminForSender(s, targetNum)
				reactMsg(ctx, evt, "👑")
				sendText(ctx, evt.Info.Chat, fmt.Sprintf("👑 *Added Sub-Admin:* `+%s`\n⚡ Authorized for this bot node.", targetNum))
			}
		}

	case "deladmin", "delsubadmin", "removesubadmin":
		if isOwnerForSender(s, user) || isOwnerForSender(s, senderJID) {
			targetNum := strings.NewReplacer("@", "", "+", "", " ", "", "-", "").Replace(args)
			if targetNum != "" {
				delSubAdminForSender(s, targetNum)
				reactMsg(ctx, evt, "🗑️")
				sendText(ctx, evt.Info.Chat, fmt.Sprintf("🗑️ *Removed Sub-Admin:* `+%s`", targetNum))
			}
		}

	case "listadmin", "admins", "showadmins", "showsubadmin":
		if !requireAdmin() {
			return
		}
		adms := listSubAdminsForSender(s)
		var b strings.Builder
		fmt.Fprintf(&b, "👑 *AUTHORIZED BOT ADMINS & USERS*\n\n")
		fmt.Fprintf(&b, "• 👑 *Primary Master Owner:* `+%s`\n", OwnerNumber)
		if s != nil && s.owner != "" {
			fmt.Fprintf(&b, "• 🛡️ *Bot Node Owner:* `%s`\n", s.owner)
		}
		for _, a := range adms {
			if a != OwnerNumber {
				fmt.Fprintf(&b, "• 🛡️ *Sub-Admin:* `+%s`\n", a)
			}
		}
		fmt.Fprintf(&b, "\n📊 *Active Calling Senders:* %d online\n", len(pool.list()))
		fmt.Fprintf(&b, "🔒 *Mode:* `%s`\n", Mode)
		reactMsg(ctx, evt, "👑")
		sendText(ctx, evt.Info.Chat, b.String())

	case "auditlog", "audit", "useractivity", "activity", "logs":
		if !requireAdmin() {
			return
		}
		serverState.mu.RLock()
		count := len(serverState.globalLogs)
		startIdx := 0
		if count > 15 {
			startIdx = count - 15
		}
		recent := append([]string(nil), serverState.globalLogs[startIdx:]...)
		serverState.mu.RUnlock()

		var b strings.Builder
		fmt.Fprintf(&b, "📋 *RECENT USER ACTIONS & COMMAND AUDIT LOG*\n\n")
		if len(recent) == 0 {
			fmt.Fprintf(&b, "_No user activity recorded yet._")
		} else {
			for i, l := range recent {
				fmt.Fprintf(&b, "%d. %s\n", i+1, l)
			}
		}
		sendText(ctx, evt.Info.Chat, b.String())

	// ── Status Saver ──
	case "saved", "save", "saverd":
		if !requireAdmin() {
			return
		}
		go handleSaveStatus(ctx, evt)

	// ── Multi-Sender Management ──
	case "addsender":
		if !requireAdmin() {
			return
		}
		go handleAddSender(ctx, evt, args)

	case "canceladd":
		if !requireAdmin() {
			return
		}
		if err := pool.removeSender(strings.TrimSpace(args)); err != nil {
			sendText(ctx, evt.Info.Chat, "❌ "+err.Error())
			return
		}
		reactMsg(ctx, evt, "🗑️")
		sendText(ctx, evt.Info.Chat, "🗑️ Sender removed.")

	case "listsender", "senders":
		if !requireAdmin() {
			return
		}
		handleListSender(ctx, evt)
	}
}

// ─── Menu ───────────────────────────────────────────────────────────────────

func menuText(isAdm bool) string {
	curP := getPrefix()
	emoji := getDefaultEmoji()
	var b strings.Builder

	fmt.Fprintf(&b, "╭━━━〔 *%s %s* 〕━━━╮\n", emoji, BotName)
	fmt.Fprintf(&b, "┃ 👑 *Owner:* `+%s`\n", OwnerNumber)
	fmt.Fprintf(&b, "┃ ⚡ *Engine:* SERVER GOD CLAN VOIP ENGINE\n")
	fmt.Fprintf(&b, "┃ 🛡️ *Mode:* %s\n", strings.ToUpper(Mode))
	fmt.Fprintf(&b, "┃ 🤖 *Senders:* %d online\n", len(pool.list()))
	fmt.Fprintf(&b, "┃ ⏱️ *Uptime:* %s\n", formatDuration(time.Since(startTime)))
	fmt.Fprintf(&b, "╰━━━━━━━━━━━━━━━━━━━━━━╯\n\n")

	fmt.Fprintf(&b, "┌─ 『 📞 *VOIP CALL SYSTEM* 』\n")
	fmt.Fprintf(&b, "│ %splaycall <num/reply>, <song>\n", curP)
	fmt.Fprintf(&b, "│ %svideocall <num/reply> [video]\n", curP)
	fmt.Fprintf(&b, "│ %sgroupcall [song] — Group Call\n", curP)
	fmt.Fprintf(&b, "│ %sacceptcall — Auto/instant accept\n", curP)
	fmt.Fprintf(&b, "│ %sendcall / %sskip\n", curP, curP)
	fmt.Fprintf(&b, "└─────────────────────\n\n")

	fmt.Fprintf(&b, "┌─ 『 🎥 *MEDIA & SONGS* 』\n")
	fmt.Fprintf(&b, "│ %splayvideo <song/link> (720p HD)\n", curP)
	fmt.Fprintf(&b, "│ %ssong <song/link> (MP3)\n", curP)
	fmt.Fprintf(&b, "│ %srobotvn <text> (Voice Note)\n", curP)
	fmt.Fprintf(&b, "│ %ssaved — Save status media\n", curP)
	fmt.Fprintf(&b, "└─────────────────────\n\n")

	fmt.Fprintf(&b, "┌─ 『 👥 *GROUP TOOLS* 』\n")
	fmt.Fprintf(&b, "│ %sjoin <invite link>\n", curP)
	fmt.Fprintf(&b, "│ %sgclink — Group Invite Link\n", curP)
	fmt.Fprintf(&b, "│ %stagall [text] — Tag Everyone\n", curP)
	fmt.Fprintf(&b, "│ %sadd / %skick / %spromote / %sdemote\n", curP, curP, curP, curP)
	fmt.Fprintf(&b, "└─────────────────────\n\n")

	if isAdm {
		fmt.Fprintf(&b, "┌─ 『 👑 *ADMIN CONTROL* 』\n")
		fmt.Fprintf(&b, "│ %saddadmin <number>\n", curP)
		fmt.Fprintf(&b, "│ %sdeladmin <number>\n", curP)
		fmt.Fprintf(&b, "│ %slistadmin\n", curP)
		fmt.Fprintf(&b, "│ %ssetprefix <char> / %ssetemoji <emoji>\n", curP, curP)
		fmt.Fprintf(&b, "│ %ssetdelay <sec> / %smode <self|public|adminonly>\n", curP, curP)
		fmt.Fprintf(&b, "│ %saddsender / %slistsender\n", curP, curP)
		fmt.Fprintf(&b, "└─────────────────────\n")
	}

	return b.String()
}

func handlePing(ctx context.Context, evt *events.Message) {
	delay := time.Since(evt.Info.Timestamp)
	if delay < 0 {
		delay = 0
	}
	sendText(ctx, evt.Info.Chat, fmt.Sprintf(
		"🏓 *Pong!*\n⏱️ *Latency:* `%dms`\n🕐 *Uptime:* `%s`\n📡 *Engine:* `SERVER GOD CLAN VOIP ENGINE`\n👑 *Mode:* `%s`",
		delay.Milliseconds(), formatDuration(time.Since(startTime)), strings.ToUpper(Mode),
	))
}

// ── Media Downloader Handlers ──

func handleDownloadVideo(ctx context.Context, evt *events.Message, query string) {
	if query == "" {
		sendText(ctx, evt.Info.Chat, fmt.Sprintf("❌ *Usage:* `%splayvideo <Song Name or YouTube Link>`", getPrefix()))
		return
	}
	reactMsg(ctx, evt, "⏳")
	sendText(ctx, evt.Info.Chat, fmt.Sprintf("🎬 _Downloading 720p HD YouTube video for '%s'..._", query))

	tmpFile := fmt.Sprintf("tmp_vid_%d.mp4", time.Now().UnixMilli())
	res, err := DownloadYouTubeMediaGo(query, "video", tmpFile)
	if err != nil || res == nil {
		reactMsg(ctx, evt, "❌")
		sendText(ctx, evt.Info.Chat, "❌ Failed to download video. YouTube request was blocked.")
		return
	}
	defer os.Remove(res.FilePath)

	data, err := os.ReadFile(res.FilePath)
	if err != nil {
		reactMsg(ctx, evt, "❌")
		sendText(ctx, evt.Info.Chat, "❌ Gagal membaca file video.")
		return
	}

	uploaded, err := waClient.Upload(ctx, data, whatsmeow.MediaVideo)
	if err != nil {
		reactMsg(ctx, evt, "❌")
		sendText(ctx, evt.Info.Chat, fmt.Sprintf("❌ Upload gagal: %v", err))
		return
	}

	reactMsg(ctx, evt, "✅")
	_, _ = waClient.SendMessage(ctx, evt.Info.Chat, &waE2E.Message{
		VideoMessage: &waE2E.VideoMessage{
			URL:           proto.String(uploaded.URL),
			DirectPath:    proto.String(uploaded.DirectPath),
			MediaKey:      uploaded.MediaKey,
			Mimetype:      proto.String("video/mp4"),
			FileEncSHA256: uploaded.FileEncSHA256,
			FileSHA256:    uploaded.FileSHA256,
			FileLength:    proto.Uint64(uploaded.FileLength),
			Caption:       proto.String(fmt.Sprintf("🎬 *%s*\n⚡ *Downloaded in 720p HD*", res.Title)),
		},
	})
}

func handleDownloadSong(ctx context.Context, evt *events.Message, query string) {
	if query == "" {
		sendText(ctx, evt.Info.Chat, fmt.Sprintf("❌ *Usage:* `%ssong <Song Name or Jio/YouTube Link>`", getPrefix()))
		return
	}
	reactMsg(ctx, evt, "⏳")
	sendText(ctx, evt.Info.Chat, fmt.Sprintf("🎵 _Searching & downloading HD audio for '%s'..._", query))

	// Priority 1: Direct JioSaavn Search & High Quality Download
	tmpFile := fmt.Sprintf("tmp_song_%d.mp3", time.Now().UnixMilli())
	jFile, jTitle, jArtist, jerr := downloadJioSaavnSong(query, tmpFile)
	var finalFile, finalTitle string

	if jerr == nil && jFile != "" && fileExists(jFile) {
		finalFile = jFile
		finalTitle = fmt.Sprintf("%s - %s", jTitle, jArtist)
	} else {
		// Priority 2: yt-dlp / Multi-extractor fallback
		res, err := DownloadYouTubeMediaGo(query, "audio", tmpFile)
		if err == nil && res != nil && fileExists(res.FilePath) {
			finalFile = res.FilePath
			finalTitle = res.Title
		}
	}

	if finalFile == "" || !fileExists(finalFile) {
		reactMsg(ctx, evt, "❌")
		sendText(ctx, evt.Info.Chat, "❌ Failed to download audio. Please check the song name.")
		return
	}
	defer os.Remove(finalFile)

	data, err := os.ReadFile(finalFile)
	if err != nil {
		reactMsg(ctx, evt, "❌")
		return
	}

	cli := getActiveClient()
	if cli == nil {
		reactMsg(ctx, evt, "❌")
		sendText(ctx, evt.Info.Chat, "❌ WhatsApp client not connected.")
		return
	}

	uploaded, err := cli.Upload(ctx, data, whatsmeow.MediaAudio)
	if err != nil {
		reactMsg(ctx, evt, "❌")
		sendText(ctx, evt.Info.Chat, fmt.Sprintf("❌ Audio upload failed: %v", err))
		return
	}

	reactMsg(ctx, evt, "✅")
	_, _ = cli.SendMessage(ctx, evt.Info.Chat, &waE2E.Message{
		AudioMessage: &waE2E.AudioMessage{
			URL:           proto.String(uploaded.URL),
			DirectPath:    proto.String(uploaded.DirectPath),
			MediaKey:      uploaded.MediaKey,
			Mimetype:      proto.String("audio/mpeg"),
			FileEncSHA256: uploaded.FileEncSHA256,
			FileSHA256:    uploaded.FileSHA256,
			FileLength:    proto.Uint64(uploaded.FileLength),
		},
	})
	sendText(ctx, evt.Info.Chat, fmt.Sprintf("🎶 *%s* (320kbps Audio Sent)", finalTitle))
}

func handleTTS(ctx context.Context, evt *events.Message, text string) {
	if text == "" {
		sendText(ctx, evt.Info.Chat, "❌ Usage: `+robotvn <text>`")
		return
	}
	reactMsg(ctx, evt, "🎙️")
	// Generate TTS using eSpeak or Google TTS / ffmpeg
	tmpAudio := fmt.Sprintf("tmp_tts_%d.mp3", time.Now().UnixMilli())
	cmd := exec.Command("python3", "-c", fmt.Sprintf(`
import sys
from gtts import gTTS
tts = gTTS(text=%q, lang='hi')
tts.save(%q)
`, text, tmpAudio))
	if err := cmd.Run(); err != nil || !fileExists(tmpAudio) {
		// Fallback ffmpeg sine synth
		cmd2 := exec.Command("ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=2", "-c:a", "libmp3lame", tmpAudio)
		_ = cmd2.Run()
	}

	if fileExists(tmpAudio) {
		data, _ := os.ReadFile(tmpAudio)
		os.Remove(tmpAudio)
		uploaded, err := waClient.Upload(ctx, data, whatsmeow.MediaAudio)
		if err == nil {
			_, _ = waClient.SendMessage(ctx, evt.Info.Chat, &waE2E.Message{
				AudioMessage: &waE2E.AudioMessage{
					URL:        proto.String(uploaded.URL),
					DirectPath: proto.String(uploaded.DirectPath),
					MediaKey:   uploaded.MediaKey,
					Mimetype:   proto.String("audio/ogg; codecs=opus"),
					PTT:        proto.Bool(true),
				},
			})
			reactMsg(ctx, evt, "✅")
		}
	}
}

func fileExists(p string) bool {
	fi, err := os.Stat(p)
	return err == nil && fi.Size() > 100
}

// ── Group Management Handlers ──

func handleJoinGroup(ctx context.Context, evt *events.Message, link string) {
	cleanLink := strings.TrimSpace(link)
	if cleanLink == "" {
		sendText(ctx, evt.Info.Chat, "❌ *Usage:* `+join <WhatsApp Group Link>`\nExample: `+join https://chat.whatsapp.com/AbCdEfGh12345`")
		return
	}
	reactMsg(ctx, evt, "⏳")

	// Parse code from any link variation
	code := cleanLink
	if idx := strings.Index(code, "chat.whatsapp.com/"); idx != -1 {
		code = code[idx+len("chat.whatsapp.com/"):]
	}
	if idx := strings.Index(code, "?"); idx != -1 {
		code = code[:idx]
	}
	code = strings.TrimSpace(code)

	jid, err := waClient.JoinGroupWithLink(ctx, code)
	if err != nil {
		reactMsg(ctx, evt, "❌")
		sendText(ctx, evt.Info.Chat, fmt.Sprintf("❌ *Gagal join group:* %v", err))
		return
	}
	reactMsg(ctx, evt, "✅")
	sendText(ctx, evt.Info.Chat, fmt.Sprintf("╔══〔 🚪 *JOINED GROUP SUCCESS* 〕══╗\n┃ 🎯 Group JID: `%s`\n┃ ⚡ Status: *Bot Joined & Active* 🟢\n╚═════════════════════════════════╝", jid.String()))
}

func handleGetGroupLink(ctx context.Context, evt *events.Message) {
	if !evt.Info.IsGroup {
		sendText(ctx, evt.Info.Chat, "❌ Command ini hanya untuk di dalam grup.")
		return
	}
	link, err := waClient.GetGroupInviteLink(ctx, evt.Info.Chat, false)
	if err != nil {
		sendText(ctx, evt.Info.Chat, fmt.Sprintf("❌ Gagal ambil link: %v", err))
		return
	}
	sendText(ctx, evt.Info.Chat, fmt.Sprintf("🔗 *Group Invite Link:*\nhttps://chat.whatsapp.com/%s", link))
}

func handleTagAll(ctx context.Context, evt *events.Message, msgText string) {
	if !evt.Info.IsGroup {
		sendText(ctx, evt.Info.Chat, "❌ Command ini hanya untuk di dalam grup.")
		return
	}
	info, err := waClient.GetGroupInfo(ctx, evt.Info.Chat)
	if err != nil {
		sendText(ctx, evt.Info.Chat, fmt.Sprintf("❌ Error: %v", err))
		return
	}

	var mentions []string
	var b strings.Builder
	fmt.Fprintf(&b, "📢 *TAG ALL MEMBERS*\n\n")
	if msgText != "" {
		fmt.Fprintf(&b, "💬 *Message:* %s\n\n", msgText)
	}

	for i, p := range info.Participants {
		jidStr := p.JID.ToNonAD().String()
		user := strings.Split(jidStr, "@")[0]
		mentions = append(mentions, jidStr)
		fmt.Fprintf(&b, "%d. @%s\n", i+1, user)
	}

	_, _ = waClient.SendMessage(ctx, evt.Info.Chat, &waE2E.Message{
		ExtendedTextMessage: &waE2E.ExtendedTextMessage{
			Text: proto.String(b.String()),
			ContextInfo: &waE2E.ContextInfo{
				MentionedJID: mentions,
			},
		},
	})
}

func handleAddParticipant(ctx context.Context, evt *events.Message, num string) {
	if !evt.Info.IsGroup {
		return
	}
	clean := strings.NewReplacer("+", "", " ", "", "-", "").Replace(num)
	targetJID := types.NewJID(clean, types.DefaultUserServer)
	_, err := waClient.UpdateGroupParticipants(ctx, evt.Info.Chat, []types.JID{targetJID}, whatsmeow.ParticipantChangeAdd)
	if err != nil {
		sendText(ctx, evt.Info.Chat, fmt.Sprintf("❌ Add failed: %v", err))
		return
	}
	sendText(ctx, evt.Info.Chat, fmt.Sprintf("✅ Added `+%s`", clean))
}

func handleKickParticipant(ctx context.Context, evt *events.Message, num string) {
	if !evt.Info.IsGroup {
		return
	}
	clean := strings.NewReplacer("+", "", " ", "", "-", "").Replace(num)
	targetJID := types.NewJID(clean, types.DefaultUserServer)
	_, err := waClient.UpdateGroupParticipants(ctx, evt.Info.Chat, []types.JID{targetJID}, whatsmeow.ParticipantChangeRemove)
	if err != nil {
		sendText(ctx, evt.Info.Chat, fmt.Sprintf("❌ Kick failed: %v", err))
		return
	}
	sendText(ctx, evt.Info.Chat, fmt.Sprintf("👢 Kicked `+%s`", clean))
}

func handlePromoteParticipant(ctx context.Context, evt *events.Message, num string) {
	if !evt.Info.IsGroup {
		return
	}
	clean := strings.NewReplacer("+", "", " ", "", "-", "").Replace(num)
	targetJID := types.NewJID(clean, types.DefaultUserServer)
	_, err := waClient.UpdateGroupParticipants(ctx, evt.Info.Chat, []types.JID{targetJID}, whatsmeow.ParticipantChangePromote)
	if err != nil {
		sendText(ctx, evt.Info.Chat, fmt.Sprintf("❌ Promote failed: %v", err))
		return
	}
	sendText(ctx, evt.Info.Chat, fmt.Sprintf("⭐ Promoted `+%s` to Admin", clean))
}

func handleDemoteParticipant(ctx context.Context, evt *events.Message, num string) {
	if !evt.Info.IsGroup {
		return
	}
	clean := strings.NewReplacer("+", "", " ", "", "-", "").Replace(num)
	targetJID := types.NewJID(clean, types.DefaultUserServer)
	_, err := waClient.UpdateGroupParticipants(ctx, evt.Info.Chat, []types.JID{targetJID}, whatsmeow.ParticipantChangeDemote)
	if err != nil {
		sendText(ctx, evt.Info.Chat, fmt.Sprintf("❌ Demote failed: %v", err))
		return
	}
	sendText(ctx, evt.Info.Chat, fmt.Sprintf("⬇️ Demoted `+%s` from Admin", clean))
}

func handleSaveStatus(ctx context.Context, evt *events.Message) {
	ctxInfo := evt.Message.GetExtendedTextMessage().GetContextInfo()
	quoted := ctxInfo.GetQuotedMessage()
	if quoted == nil {
		sendText(ctx, evt.Info.Chat, "❌ Reply to a status video/image with `+saved` to save it.")
		return
	}

	reactMsg(ctx, evt, "💾")
	if img := quoted.GetImageMessage(); img != nil {
		data, err := waClient.Download(ctx, img)
		if err == nil {
			up, err := waClient.Upload(ctx, data, whatsmeow.MediaImage)
			if err == nil {
				_, _ = waClient.SendMessage(ctx, evt.Info.Chat, &waE2E.Message{
					ImageMessage: &waE2E.ImageMessage{
						URL:        proto.String(up.URL),
						DirectPath: proto.String(up.DirectPath),
						MediaKey:   up.MediaKey,
						Mimetype:   proto.String("image/jpeg"),
						Caption:    proto.String("💾 *Saved Status Image*"),
					},
				})
			}
		}
	} else if vid := quoted.GetVideoMessage(); vid != nil {
		data, err := waClient.Download(ctx, vid)
		if err == nil {
			up, err := waClient.Upload(ctx, data, whatsmeow.MediaVideo)
			if err == nil {
				_, _ = waClient.SendMessage(ctx, evt.Info.Chat, &waE2E.Message{
					VideoMessage: &waE2E.VideoMessage{
						URL:        proto.String(up.URL),
						DirectPath: proto.String(up.DirectPath),
						MediaKey:   up.MediaKey,
						Mimetype:   proto.String("video/mp4"),
						Caption:    proto.String("💾 *Saved Status Video*"),
					},
				})
			}
		}
	}
}

func formatDuration(d time.Duration) string {
	h, m, s := int(d.Hours()), int(d.Minutes())%60, int(d.Seconds())%60
	if h > 0 {
		return fmt.Sprintf("%dh %dm %ds", h, m, s)
	}
	if m > 0 {
		return fmt.Sprintf("%dm %ds", m, s)
	}
	return fmt.Sprintf("%ds", s)
}

// ─── Playcall & Queue ─────────────────────────────────────────────────────────

func handlePlaycall(ctx context.Context, evt *events.Message, args string) {
	reactMsg(ctx, evt, "⏳")
	chat := evt.Info.Chat

	target, title, err := resolveTarget(ctx, evt, args)
	if err != nil {
		reactMsg(ctx, evt, "❌")
		sendText(ctx, chat, "❌ "+err.Error())
		return
	}
	cleanTarget := cleanJIDNumber(target)

	snd := pool.acquireFree()
	if snd == nil {
		reactMsg(ctx, evt, "❌")
		sendText(ctx, chat, "❌ All calling nodes are currently busy or offline.")
		return
	}

	sendText(ctx, chat, fmt.Sprintf("🔍 _Searching audio for '%s'..._", title))
	var audioFilePath, audioTitle string

	if title != "" && title != "51.mp3" {
		// Priority 1: High speed JioSaavn 320kbps
		jTmp := fmt.Sprintf("tmp_call_jio_%d.mp3", time.Now().UnixMilli())
		if jPath, jName, jArt, jerr := downloadJioSaavnSong(title, jTmp); jerr == nil && jPath != "" && fileExists(jPath) {
			audioFilePath = jPath
			audioTitle = fmt.Sprintf("%s - %s", jName, jArt)
		} else {
			// Priority 2: yt-dlp / YouTube fallback
			yTmp := fmt.Sprintf("tmp_call_yt_%d.mp3", time.Now().UnixMilli())
			if res, err := DownloadYouTubeMediaGo(title, "audio", yTmp); err == nil && res != nil && fileExists(res.FilePath) {
				audioFilePath = res.FilePath
				audioTitle = res.Title
			}
		}
	}

	if audioFilePath == "" {
		if fileExists("51.mp3") {
			audioFilePath = "51.mp3"
			audioTitle = "51.mp3 High-Bass Master Loop"
		} else if fileExists("../51.mp3") {
			audioFilePath = "../51.mp3"
			audioTitle = "51.mp3 High-Bass Master Loop"
		}
	}

	if audioFilePath == "" {
		reactMsg(ctx, evt, "❌")
		sendText(ctx, chat, "❌ Failed to load audio stream for call.")
		return
	}

	sess := &callSession{
		sender:    snd,
		active:    true,
		target:    cleanTarget,
		requester: senderUser(evt),
		curFile:   audioFilePath,
		stopHB:    make(chan struct{}),
		done:      make(chan struct{}),
	}
	snd.mu.Lock()
	snd.sess = sess
	snd.mu.Unlock()

	sendText(ctx, chat, fmt.Sprintf("🎵 *%s*\n📞 %s calling *+%s*...", audioTitle, snd.name, cleanTarget))

	callCtx, cancel := context.WithTimeout(context.Background(), 35*time.Second)
	defer cancel()

	call, err := snd.call.Call(callCtx, target)
	if err != nil {
		reactMsg(ctx, evt, "❌")
		sendText(ctx, chat, fmt.Sprintf("❌ Failed to call +%s: %v", cleanTarget, err))
		if audioFilePath != "" && !strings.Contains(audioFilePath, "51.mp3") {
			os.Remove(audioFilePath)
		}
		snd.mu.Lock()
		sess.reset()
		snd.sess = nil
		snd.mu.Unlock()
		return
	}

	shortID := call.ID()
	if len(shortID) > 8 {
		shortID = shortID[:8]
	}

	sess.mu.Lock()
	sess.call = call
	sess.shortID = shortID
	sess.mu.Unlock()

	go keepCallAlive(snd.wa, call.ID(), sess.stopHB)

	call.OnReady(func() {
		p := meowcaller.NewPlayer()
		call.Subscribe(p)

		sess.mu.Lock()
		sess.player = p
		sess.mu.Unlock()

		sendText(ctx, chat, fmt.Sprintf("🎉 *Call Connected to +%s* (ID: `%s`)", cleanTarget, shortID))
		reactMsg(ctx, evt, "🎉")

		var playLoop func()
		playLoop = func() {
			sess.mu.Lock()
			isActive := sess.active
			activeFile := sess.curFile
			sess.mu.Unlock()
			if !isActive || activeFile == "" {
				return
			}
			if src, err := meowcaller.MP3File(activeFile); err == nil {
				p.OnFinish(playLoop)
				p.Play(src)
			}
		}
		playLoop()
	})

	call.OnEnd(func(reason string) {
		sendText(ctx, chat, fmt.Sprintf("📴 *Call Finished with +%s* (ID: `%s`)", cleanTarget, shortID))
		reactMsg(ctx, evt, "📴")
		if audioFilePath != "" && !strings.Contains(audioFilePath, "51.mp3") {
			os.Remove(audioFilePath)
		}
		snd.mu.Lock()
		sess.reset()
		snd.sess = nil
		snd.mu.Unlock()
		sess.stopAll()
	})
}

func handlePlaycallFile(ctx context.Context, evt *events.Message, args string) {
	reactMsg(ctx, evt, "⏳")
	chat := evt.Info.Chat

	fields := strings.Fields(args)
	if len(fields) == 0 {
		reactMsg(ctx, evt, "❌")
		sendText(ctx, chat, fmt.Sprintf("❌ *Usage:* `%splaycallfile <filename or 51.mp3> [target number]`", getPrefix()))
		return
	}

	fileName := fields[0]
	targetArg := ""
	if len(fields) > 1 {
		targetArg = fields[1]
	}

	var filePath string
	candidates := []string{
		fileName,
		filepath.Join("recordings", fileName),
		filepath.Join("recordings", fileName+".mp3"),
		fileName + ".mp3",
		"51.mp3",
		"../51.mp3",
	}
	for _, p := range candidates {
		if fileExists(p) {
			filePath = p
			break
		}
	}

	if filePath == "" {
		reactMsg(ctx, evt, "❌")
		sendText(ctx, chat, fmt.Sprintf("❌ File `%s` not found in recordings or root.", fileName))
		return
	}

	// 1. If an active call exists on any sender node, HOT-SWAP audio directly without starting a new call
	for _, s := range pool.list() {
		s.mu.Lock()
		curSess := s.sess
		s.mu.Unlock()
		if curSess != nil && curSess.active && curSess.player != nil {
			curSess.mu.Lock()
			curSess.curFile = filePath
			p := curSess.player
			curSess.mu.Unlock()

			if src, err := meowcaller.MP3File(filePath); err == nil {
				reactMsg(ctx, evt, "🎶")
				var loopPlay func()
				loopPlay = func() {
					curSess.mu.Lock()
					isActive := curSess.active
					activeFile := curSess.curFile
					curSess.mu.Unlock()
					if !isActive || activeFile == "" {
						return
					}
					if lsrc, lerr := meowcaller.MP3File(activeFile); lerr == nil {
						p.OnFinish(loopPlay)
						p.Play(lsrc)
					}
				}
				p.OnFinish(loopPlay)
				p.Play(src)
				sendText(ctx, chat, fmt.Sprintf("🎶 *[ACTIVE CALL AUDIO CHANGED]*\n▶️ Now playing: `%s` in active call!", filepath.Base(filePath)))
				return
			}
		}
	}

	snd := pool.acquireFree()
	if snd == nil {
		reactMsg(ctx, evt, "❌")
		sendText(ctx, chat, "❌ All calling nodes are currently busy or offline.")
		return
	}

	target := chat.String()
	if targetArg != "" {
		target = strings.NewReplacer("+", "", " ", "", "-", "").Replace(targetArg)
	} else if !evt.Info.IsGroup {
		target = senderUser(evt)
	}

	cleanTarget := cleanJIDNumber(target)
	sendText(ctx, chat, fmt.Sprintf("📁 Streaming *%s* on call to *+%s*...", filepath.Base(filePath), cleanTarget))

	callCtx, cancel := context.WithTimeout(context.Background(), 35*time.Second)
	defer cancel()

	var call *meowcaller.Call
	var err error
	if strings.Contains(target, "@g.us") || (evt.Info.IsGroup && targetArg == "") {
		call, err = snd.call.GroupCallByIDWithOptions(callCtx, target, meowcaller.GroupCallOptions{Video: false})
	} else {
		call, err = snd.call.Call(callCtx, target)
	}

	if err != nil {
		reactMsg(ctx, evt, "❌")
		sendText(ctx, chat, fmt.Sprintf("❌ Call failed: %v", err))
		return
	}

	shortID := call.ID()
	if len(shortID) > 8 {
		shortID = shortID[:8]
	}

	sess := &callSession{
		sender:    snd,
		active:    true,
		target:    cleanTarget,
		requester: senderUser(evt),
		curFile:   filePath,
		stopHB:    make(chan struct{}),
		done:      make(chan struct{}),
	}
	snd.mu.Lock()
	snd.sess = sess
	snd.mu.Unlock()

	go keepCallAlive(snd.wa, call.ID(), sess.stopHB)

	call.OnReady(func() {
		p := meowcaller.NewPlayer()
		call.Subscribe(p)

		sess.mu.Lock()
		sess.player = p
		sess.mu.Unlock()

		sendText(ctx, chat, fmt.Sprintf("🎉 *File Connected on Call!* (ID: `%s`)\n▶️ Playing `%s`", shortID, filepath.Base(filePath)))
		reactMsg(ctx, evt, "🎉")

		var playLoop func()
		playLoop = func() {
			sess.mu.Lock()
			isActive := sess.active
			sess.mu.Unlock()
			if !isActive {
				return
			}
			if src, err := meowcaller.MP3File(filePath); err == nil {
				p.OnFinish(playLoop)
				p.Play(src)
			}
		}
		playLoop()
	})

	call.OnEnd(func(reason string) {
		sendText(ctx, chat, fmt.Sprintf("📴 *Call Ended* (ID: `%s`)", shortID))
		reactMsg(ctx, evt, "📴")
		snd.mu.Lock()
		sess.reset()
		snd.sess = nil
		snd.mu.Unlock()
		sess.stopAll()
	})
}

func handlePlayRD(ctx context.Context, evt *events.Message, args string) {
	name := strings.TrimSpace(args)
	if name == "" {
		sendText(ctx, evt.Info.Chat, fmt.Sprintf("❌ *Usage:* `%splayrd <name>` (List recordings with `%slistrd`)", getPrefix(), getPrefix()))
		return
	}

	// 1. If call is currently active on any node, inject/swap this recording into the active live call
	for _, s := range pool.list() {
		s.mu.Lock()
		curSess := s.sess
		s.mu.Unlock()
		if curSess != nil && curSess.active && curSess.player != nil {
			var filePath string
			candidates := []string{
				filepath.Join("recordings", name),
				filepath.Join("recordings", name+".mp3"),
				name,
				name + ".mp3",
			}
			for _, p := range candidates {
				if fileExists(p) {
					filePath = p
					break
				}
			}
			if filePath != "" {
				curSess.mu.Lock()
				curSess.curFile = filePath
				p := curSess.player
				curSess.mu.Unlock()

				if src, err := meowcaller.MP3File(filePath); err == nil {
					reactMsg(ctx, evt, "▶️")
					var loopPlay func()
					loopPlay = func() {
						curSess.mu.Lock()
						isActive := curSess.active
						activeFile := curSess.curFile
						curSess.mu.Unlock()
						if !isActive || activeFile == "" {
							return
						}
						if lsrc, lerr := meowcaller.MP3File(activeFile); lerr == nil {
							p.OnFinish(loopPlay)
							p.Play(lsrc)
						}
					}
					p.OnFinish(loopPlay)
					p.Play(src)
					sendText(ctx, evt.Info.Chat, fmt.Sprintf("▶️ *[LIVE CALL INJECTION]* Now streaming recording `%s` in active call loop!", filepath.Base(filePath)))
					return
				}
			}
		}
	}

	// 2. Otherwise start call with recording
	handlePlaycallFile(ctx, evt, name)
}

func handleLiveChangeSong(ctx context.Context, evt *events.Message, args string) {
	songQuery := strings.TrimSpace(args)
	if songQuery == "" {
		sendText(ctx, evt.Info.Chat, fmt.Sprintf("❌ *Usage:* `%schangesong <song name or yt link>`", getPrefix()))
		return
	}

	reactMsg(ctx, evt, "🔍")
	sendText(ctx, evt.Info.Chat, fmt.Sprintf("🔍 _Searching & loading '%s' for active call..._", songQuery))

	var filePath, trackTitle, trackArtist string

	// 1. Try JioSaavn
	tmpJio := fmt.Sprintf("tmp_swap_jio_%d.mp3", time.Now().UnixMilli())
	if jPath, jName, jArt, jerr := downloadJioSaavnSong(songQuery, tmpJio); jerr == nil && jPath != "" && fileExists(jPath) {
		filePath = jPath
		trackTitle = jName
		trackArtist = jArt
	} else {
		// 2. Fallback to YouTube
		tmpYt := fmt.Sprintf("tmp_swap_yt_%d.mp3", time.Now().UnixMilli())
		if res, err := DownloadYouTubeMediaGo(songQuery, "audio", tmpYt); err == nil && res != nil && fileExists(res.FilePath) {
			filePath = res.FilePath
			trackTitle = res.Title
			trackArtist = res.Artist
		}
	}

	if filePath == "" {
		reactMsg(ctx, evt, "❌")
		sendText(ctx, evt.Info.Chat, fmt.Sprintf("❌ Failed to download audio for '%s'.", songQuery))
		return
	}

	swapped := false
	for _, s := range pool.list() {
		s.mu.Lock()
		curSess := s.sess
		s.mu.Unlock()
		if curSess != nil && curSess.active && curSess.player != nil {
			curSess.mu.Lock()
			curSess.curFile = filePath
			p := curSess.player
			curSess.mu.Unlock()

			if src, err := meowcaller.MP3File(filePath); err == nil {
				reactMsg(ctx, evt, "🎶")
				var loopPlay func()
				loopPlay = func() {
					curSess.mu.Lock()
					isActive := curSess.active
					curSess.mu.Unlock()
					if !isActive {
						return
					}
					if lsrc, lerr := meowcaller.MP3File(filePath); lerr == nil {
						p.OnFinish(loopPlay)
						p.Play(lsrc)
					}
				}
				p.OnFinish(loopPlay)
				p.Play(src)
				swapped = true
				sendText(ctx, evt.Info.Chat, fmt.Sprintf("🎶 *[LIVE CALL SONG CHANGED]*\n▶️ Now Streaming: *%s* (%s)", trackTitle, trackArtist))
				return
			}
		}
	}

	if !swapped {
		// If no active call, start new group call or outcall with this song
		if evt.Info.IsGroup {
			handleGroupCall(ctx, evt, songQuery, false)
		} else {
			handlePlaycall(ctx, evt, songQuery)
		}
	}
}

func handleSkip(ctx context.Context, evt *events.Message, args string) {
	sess, msg := pool.sessionFor(strings.TrimSpace(args))
	if sess == nil {
		sendText(ctx, evt.Info.Chat, msg)
		return
	}
	sess.mu.Lock()
	p := sess.player
	sess.mu.Unlock()

	reactMsg(ctx, evt, "⏭️")
	if p != nil {
		p.Stop()
	}
	sendText(ctx, evt.Info.Chat, "⏭️ Skipped current audio.")
}

func handleStop(ctx context.Context, evt *events.Message, args string) {
	endedAny := false

	// 1. Check direct targeted session
	sess, _ := pool.sessionFor(strings.TrimSpace(args))
	if sess != nil {
		sess.mu.Lock()
		call := sess.call
		player := sess.player
		sess.reset()
		sess.mu.Unlock()
		if player != nil {
			player.Stop()
		}
		if call != nil {
			_ = call.Hangup()
		}
		sess.stopAll()
		endedAny = true
	}

	// 2. Check video call session
	vsess, _ := pool.videoSessionFor(strings.TrimSpace(args))
	if vsess != nil {
		vsess.mu.Lock()
		call := vsess.call
		vsess.active = false
		vsess.mu.Unlock()
		if call != nil {
			_ = call.Hangup()
		}
		endedAny = true
	}

	// 3. Clean up any active sessions across all senders in pool
	for _, s := range pool.list() {
		s.mu.Lock()
		curSess := s.sess
		curVSess := s.videoSess
		s.sess = nil
		s.videoSess = nil
		s.mu.Unlock()

		if curSess != nil {
			curSess.mu.Lock()
			c := curSess.call
			p := curSess.player
			curSess.reset()
			curSess.mu.Unlock()
			if p != nil {
				p.Stop()
			}
			if c != nil {
				_ = c.Hangup()
			}
			curSess.stopAll()
			endedAny = true
		}
		if curVSess != nil {
			curVSess.mu.Lock()
			vc := curVSess.call
			curVSess.active = false
			curVSess.mu.Unlock()
			if vc != nil {
				_ = vc.Hangup()
			}
			endedAny = true
		}
	}

	reactMsg(ctx, evt, "🛑")
	if endedAny {
		sendText(ctx, evt.Info.Chat, "🛑 *Call terminated & voice stream disconnected successfully.*")
	} else {
		sendText(ctx, evt.Info.Chat, "📭 *No active call was found running.*")
	}
}

func normalizeJIDString(raw string) string {
	if raw == "" {
		return raw
	}
	jid, err := types.ParseJID(raw)
	if err != nil {
		return raw
	}
	return jid.ToNonAD().String()
}

func resolveLIDToPhone(ctx context.Context, jid types.JID) (types.JID, error) {
	if jid.Server != types.HiddenUserServer {
		return jid, nil
	}
	pn, err := waClient.Store.LIDs.GetPNForLID(ctx, jid)
	if err != nil {
		return jid, fmt.Errorf("resolve LID failed: %w", err)
	}
	if pn.IsEmpty() || pn.User == "" {
		return jid, fmt.Errorf("phone number not cached for LID: %s", jid.User)
	}
	return pn, nil
}

// ── Target Resolution & Dynamic Client ──

func resolveTarget(ctx context.Context, evt *events.Message, args string) (target, title string, err error) {
	ctxInfo := evt.Message.GetExtendedTextMessage().GetContextInfo()
	quoted := ctxInfo.GetParticipant()

	if quoted == "" && ctxInfo.GetStanzaID() != "" && !evt.Info.IsGroup {
		quoted = evt.Info.Chat.String()
	}

	if quoted != "" {
		quoted = normalizeJIDString(quoted)
		jid, perr := types.ParseJID(quoted)
		if perr == nil {
			resolved, lerr := resolveLIDToPhone(ctx, jid)
			if lerr == nil {
				quoted = resolved.ToNonAD().String()
			}
		}
		title = strings.TrimSpace(args)
		if title == "" {
			title = "51.mp3"
		}
		return quoted, title, nil
	}
	parts := strings.SplitN(args, ",", 2)
	if len(parts) >= 2 {
		number := strings.TrimSpace(strings.TrimPrefix(strings.TrimSpace(parts[0]), "+"))
		number = strings.NewReplacer(" ", "", "-", "").Replace(number)
		title = strings.TrimSpace(parts[1])
		if title == "" {
			title = "51.mp3"
		}
		return number, title, nil
	}
	fields := strings.Fields(args)
	if len(fields) >= 1 {
		number := strings.TrimSpace(strings.TrimPrefix(fields[0], "+"))
		title := "51.mp3"
		if len(fields) > 1 {
			title = strings.Join(fields[1:], " ")
		}
		return number, title, nil
	}
	return "", "", fmt.Errorf("format: %splaycall <PhoneNumber / @tag> [Song Name / 51.mp3]", getPrefix())
}

func getActiveClient() *whatsmeow.Client {
	if waClient != nil && waClient.IsConnected() {
		return waClient
	}
	for _, s := range pool.list() {
		if s.connected() {
			waClient = s.wa
			callClient = s.call
			return s.wa
		}
	}
	if mainS := pool.main(); mainS != nil {
		return mainS.wa
	}
	return waClient
}

func sendText(ctx context.Context, to types.JID, text string) {
	cli := getActiveClient()
	if cli == nil {
		fmt.Println("[send] no active whatsmeow client for:", to.String())
		return
	}
	_, err := cli.SendMessage(ctx, to, &waE2E.Message{
		Conversation: proto.String(text),
	})
	if err != nil {
		fmt.Println("[send] error:", to.String(), err)
	}
}

func sendImage(ctx context.Context, to types.JID, imgName string, caption string) {
	cli := getActiveClient()
	if cli == nil {
		return
	}
	candidates := []string{
		imgName,
		filepath.Join(".", imgName),
		filepath.Join("..", imgName),
		filepath.Join("/app", imgName),
		filepath.Join("/app/YamzzBot-Caller-main", imgName),
	}
	var data []byte
	var err error
	for _, p := range candidates {
		if fileExists(p) {
			data, err = os.ReadFile(p)
			if err == nil && len(data) > 500 {
				break
			}
		}
	}

	if len(data) > 500 {
		up, uperr := cli.Upload(ctx, data, whatsmeow.MediaImage)
		if uperr == nil {
			_, err = cli.SendMessage(ctx, to, &waE2E.Message{
				ImageMessage: &waE2E.ImageMessage{
					URL:        proto.String(up.URL),
					DirectPath: proto.String(up.DirectPath),
					MediaKey:   up.MediaKey,
					Mimetype:   proto.String("image/png"),
					Caption:    proto.String(caption),
				},
			})
			if err == nil {
				return
			}
		}
	}
	sendText(ctx, to, caption)
}

var enableCmdReactions = false

func reactMsg(ctx context.Context, evt *events.Message, emoji string) {
	if !enableCmdReactions && emoji != "FORCE" {
		return
	}
	if emoji == "FORCE" {
		emoji = "⚡"
	}
	cli := getActiveClient()
	if cli == nil {
		return
	}
	_, _ = cli.SendMessage(ctx, evt.Info.Chat, &waE2E.Message{
		ReactionMessage: &waE2E.ReactionMessage{
			Key: &waCommon.MessageKey{
				RemoteJID:   proto.String(evt.Info.Chat.String()),
				FromMe:      proto.Bool(evt.Info.IsFromMe),
				ID:          proto.String(evt.Info.ID),
				Participant: proto.String(evt.Info.Sender.String()),
			},
			Text:              proto.String(emoji),
			SenderTimestampMS: proto.Int64(time.Now().UnixMilli()),
		},
	})
}

func getMenuPortalText(prefix string) string {
	tpl := `╭──────────────────────────────╮
│ 👑 𝑲𝑰𝑵𝑮 𝑩𝑶𝑻 𝑴𝑬𝑵𝑼 𝑷𝑶𝑹𝑻𝑨𝑳 ⚡ │
│ 🛡️ 𝑺𝑬𝑹𝑽𝑬𝑹 𝑮𝑶𝑫 𝑪𝑳𝑨𝑵     │
╰──────────────────────────────╯
      ⚡ PREFIX  :  {P}
      🚀 SPEED   : 0.01s+

Please select a Dashboard by replying with number (1, 2, 3, or 4):

1️⃣ 1 or {P}menu 1 ➔ 👑 𝑼𝑳𝑻𝑹𝑨 𝑫𝑨𝑺𝑯𝑩𝑶𝑨𝑹𝑫
   (Target • NC • DC • Spam • PFP • Poll • Radar • Utility • Multi-Node)

2️⃣ 2 or {P}menu 2 ➔ 📞 𝑽𝑶𝑰𝑷 𝑪𝑨𝑳𝑳𝑰𝑵𝑮 𝑬𝑵𝑮𝑰𝑵𝑬
   (Outcall • VN • Recordings • 51.mp3 Loop • JioCall • Autounmute • ScreenShare • GroupCall)

3️⃣ 3 or {P}menu 3 ➔ 🎵 𝑴𝑼𝑺𝑰𝑪 & 𝑺𝑶𝑵𝑮 𝑫𝑨𝑺𝑯𝑩𝑶𝑨𝑹𝑫
   (JioSaavn 320kbps • Spotify HD • YouTube Video • Song Loops)

4️⃣ 4 or {P}menu 4 ➔ 🎙️ 𝑨𝑰 𝑽𝑶𝑰𝑪𝑬 𝑺𝑻𝑼𝑫𝑰𝑶 & 𝑪𝑳𝑶𝑵𝑰𝑵𝑮
   (OpenVoice V2 • AI Voice Note • Voice Changer • Clone Speech • Text-to-Speech)

╭──────────────────────────────╮
│ ⚡ 𝑷𝑶𝑾𝑬𝑹𝑬𝑫 𝑩𝒀 𝑺𝑬𝑹𝑽𝑬𝑹 𝑮𝑶𝑫 𝑪𝑳𝑨𝑵 ⚡ │
╰──────────────────────────────╯
👉 Reply 1, 2, 3, or 4 (or use shortcut {P}menu 1, {P}menu 2, {P}menu 3, {P}menu 4)`
	return strings.ReplaceAll(tpl, "{P}", prefix)
}

func getUltraDashboardMenu(prefix string) string {
	tpl := `╭──────────────────────────────╮
│ 👑 𝑲𝑰𝑵𝑮 𝑩𝑶𝑻 𝑼𝑳𝑻𝑹𝑨 𝑽2.0 ⚡ │
│ 🛡️ 𝑺𝑬𝑹𝑽𝑬𝑹 𝑮𝑶𝑫 𝑪𝑳𝑨𝑵     │
╰──────────────────────────────╯
      ⚡ PREFIX  :  {P}
      🚀 SPEED   : 0.01s+

╭─ 🎯 𝑻𝑨𝑹𝑮𝑬𝑻 𝑺𝒀𝑺𝑻𝑬𝑴
│ 🎯 {P}target @tag <Text>
│ 🛑 {P}stoptarget @tag
│ 🧹 {P}stoptargetall
│ 📋 {P}targetlist
│ ⏱️ {P}targetdelay <0.01-20>
│ 💀 {P}roast @tag
╰──────────────────────

╭─ 📌 𝑷𝑰𝑵 𝑺𝑷𝑨𝑴
│ 📌 {P}pin
│ 📌 {P}unpin
│ ⚡ {P}pinspam <count> <delay_ms>
│ 🛑 {P}pinspam off
╰──────────────────────

╭─ ⚡ 𝑵𝑹 (𝑵𝑨𝑴𝑬 𝑹𝑨𝑰𝑫)
│ ⚡ {P}nr <Text>
│ ⚡ {P}nr1 <Text>
│ ⚡ {P}nr2 <Text>
│ ⚡ {P}nr3 <Text>
│ ⏱️ {P}nrdelay <0.01-20>
│ 🛑 {P}stopnr
│ 🔴 {P}stopnrall
│ 📨 {P}send <Number/JID> <Text>
╰──────────────────────

╭─ 🌀 𝑻𝑼𝑹𝑩𝑶 𝑵𝑪
│ 🌀 {P}nc <Text>
│ ⚡ {P}triplenc1 <Text>
│ ⏱️ {P}ncdelay <0.01-20>
│ 🛑 {P}stopnc
│ 🔴 {P}stopncall
╰──────────────────────

╭─ ✍️ 𝑮𝑹𝑶𝑼𝑷 𝑫𝑪
│ 📝 {P}gdc <Text>
│ 📝 {P}gcdc <Text>
│ ⏱️ {P}gdcdelay <0.01-20>
│ 🛑 {P}gdcstop
│ 🔴 {P}stopgdcall
╰──────────────────────

╭─ 🖼️ 𝑨𝑼𝑻𝑶 𝑷𝑭𝑷
│ 📸 {P}pfpchange
│ ⏱️ {P}pfpdelay <0.1-20>
│ 🛑 {P}pfpstop
╰──────────────────────

╭─ 📸 𝑷𝑰𝑪 𝑺𝑷𝑨𝑴
│ 🖼️ {P}picspam <Text>
│ ⏱️ {P}picspamdelay <0.1-20>
│ 🛑 {P}picspamstop
│ 🔴 {P}stoppicspamall
╰──────────────────────

╭─ 📊 𝑻𝑬𝑿𝑻 & 𝑷𝑶𝑳𝑳
│ 📝 {P}textspam <Text>
│ ⏱️ {P}textspamdelay <0.01-20>
│ 🛑 {P}textspamstop
│ 📊 {P}pollspam Name | opt1 | opt2
│ ⏱️ {P}pollspamdelay <0.1-20>
│ 🛑 {P}pollspamstop
╰──────────────────────

╭─ 💀 𝑹𝑨𝑫𝑨𝑹 & 𝑴𝑼𝑻𝑬
│ 💀 {P}autodelete @tag
│ 🔓 {P}stopdelete @tag
│ 🔇 {P}mute @tag
│ 🔊 {P}unmute @tag
╰──────────────────────

╭─ 🚀 𝑭𝑳𝑶𝑶𝑫 & 𝑺𝑾𝑰𝑷𝑬
│ 🚀 {P}spam <Text>
│ ⏱️ {P}spamdelay <0.01-20>
│ 🛑 {P}stopspam
│ 🔴 {P}stopspamall
│ 🔄 {P}swipe <Text>
│ ⏱️ {P}swipedelay <0.01-20>
│ 🛑 {P}stopswipe
│ 🚨 {P}stopall
╰──────────────────────

╭─ 🛡️ 𝑴𝑶𝑫𝑬𝑹𝑨𝑻𝑰𝑶𝑵
│ ⚠️ {P}warn @tag
│ 🔄 {P}resetwarn @tag
│ 🔗 {P}antilink on/off
│ 📢 {P}tagall <Text>
│ 👑 {P}addsubadmin @tag
│ ❌ {P}removesubadmin @tag
│ 📋 {P}showsubadmin
╰──────────────────────

╭─ ⚙️ 𝑮𝑹𝑶𝑼𝑷 𝑼𝑻𝑰𝑳𝑰𝑻𝒀
│ ➕ {P}add <Number>
│ 🧹 {P}kick @tag
│ 👑 {P}promote @tag
│ 📉 {P}demote @tag
│ 🔒 {P}closegroup
│ 🔓 {P}opengroup
│ 📢 {P}hidetag <Text>
│ 🔗 {P}gclink
│ 🔄 {P}revoke
│ ✏️ {P}setgcname <Name>
│ 📝 {P}setgcdesc <Desc>
│ 🎭 {P}react <Emoji>
│ 🚪 {P}join <Link>
│ 🚪 {P}leave
│ 🤖 {P}creategc <Name>
│ ⚡ {P}ping
│ 📊 {P}botinfo
╰──────────────────────

╭─ 🛰️ 𝑴𝑼𝑳𝑻𝑰-𝑵𝑶𝑫𝑬
│ 🔌 {P}disconnect
│ ❌ {P}deletesession
│ 🆔 {P}addbotsession <Name>
│ 📋 {P}bots
│ ❌ {P}removebot <Session>
│ 🔥 {P}rage
│ 🛡️ {P}solo
│ 🔄 {P}changeprefix <Symbol>
╰──────────────────────

╭──────────────────────────────╮
│ ⚡ 𝑷𝑶𝑾𝑬𝑹𝑬𝑫 𝑩𝒀 𝑺𝑬𝑹𝑽𝑬𝑹 𝑮𝑶𝑫 𝑪𝑳𝑨𝑵 ⚡ │
╰──────────────────────────────╯`
	return strings.ReplaceAll(tpl, "{P}", prefix)
}

func getCallingEngineMenu(prefix string) string {
	tpl := `╔══〔 📞 GO LANG WEBRTC CALLING SUITE 〕══╗
║ ⚡ Engine: SERVER GOD CLAN VOIP ENGINE    ║
║ 🛡️ SERVER GOD CLAN • VOIP MASTER         ║
╚══════════════════════════════════════════╝
      ⚡ PREFIX  :  {P}
      🔊 DEFAULT : 51.mp3 High-Bass Master Loop

╭─ 📞 OUTBOUND REAL VOIP & GROUP CALLS
│ 📞 {P}outcall <Number/@tag> [Song / 51.mp3]
│    ▸ Dial target and live stream 51.mp3 or YouTube song
│ 👥 {P}groupcall [Song Name]
│    ▸ Create native Group Voice Call and stream audio
│ 🎥 {P}videocall <Number> [Song Name]
│    ▸ 1-on-1 High-Definition Video Call
│ 📹 {P}groupvideocall [Song Name]
│    ▸ Group Video Call with live stream
│ 🎶 {P}playytcall <Song Name / Link>
│    ▸ Stream YouTube song into active live call
│ 📹 {P}play2ytcall <Song Name / Link>
│    ▸ Stream YouTube video into active live video call
│ 🔊 {P}play1call / {P}playcall (51.mp3 Loop)
│ 📺 {P}play2call (2.mp4 Video Loop)
│ 🚪 {P}joincall [51.mp3/song]
│    ▸ Join active voice chat and stream loop
│ 🔄 {P}changesong <Song Name>
│    ▸ Switch audio in ongoing call without leaving
│ 🔄 {P}audiotovideo / {P}videotoaudio
│ 👥 {P}addparticipant <Number>
│ 📺 {P}screenshare on/off
│    ▸ Enable/disable live screen sharing
│ ✋ {P}handraise / {P}callreaction <emoji>
│    ▸ Dispatch live WebRTC reactions
│ 🚪 {P}waitingroom on/off
│ ⏹️ {P}endcall / {P}hangup / {P}cutcall / {P}leavecall
│    ▸ Terminate active call and loops immediately
│ 🔇 {P}callmute / 🔊 {P}callunmute
│    ▸ Mute/Unmute microphone stream
╰──────────────────────────────────────────

╭─ 📲 INCOMING CALL SENTINEL
│ 🔔 {P}noti <Chat_JID>
│    ▸ Route incoming call alerts to specific group/chat
│ 📞 {P}acceptcall [Song/Track]
│    ▸ Answer incoming call with live audio stream
│ 🛑 {P}rejectcall / {P}declinecall
│    ▸ Instantly decline incoming call
│ 🚫 {P}anticall on/off
│    ▸ Auto-reject incoming calls sentinel
│ 🔓 {P}autounmute
│    ▸ Keep microphone stream continuously open
│ 📊 {P}callstatus
│    ▸ View active VoIP nodes and running calls
╰──────────────────────────────────────────

╭─ 💾 CUSTOM RECORDINGS & VAULT
│ 💾 {P}saverd <name> (Save voice note to vault)
│ 📋 {P}listrd / {P}viewfiles / {P}files
│ ▶️ {P}playrd <name> (Stream recording on call)
│ 📁 {P}playcallfile <filename>
│ 🗑️ {P}delrd <name> / {P}delfile <name>
│ 🗣️ {P}cvn <Text> (Call Voice Speech Injector)
╰──────────────────────────────────────────

╭─ 📋 AUDIT & USER MANAGEMENT
│ 📋 {P}auditlog / {P}audit / {P}logs
│ 👑 {P}admins / {P}showadmins
│ ➕ {P}addadmin <Number/@tag>
│ 🗑️ {P}deladmin <Number/@tag>
╰──────────────────────────────────────────

╭──────────────────────────────╮
│ ⚡ 𝑷𝑶𝑾𝑬𝑹𝑬𝑫 𝑩𝒀 𝑺𝑬𝑹𝑽𝑬𝑹 𝑮𝑶𝑫 𝑪𝑳𝑨𝑵 ⚡ │
╰──────────────────────────────╯`
	return strings.ReplaceAll(tpl, "{P}", prefix)
}

func getSongDashboardMenu(prefix string) string {
	tpl := `╭──────────────────────────────╮
│ 🎵 𝑴𝑼𝑺𝑰𝑪 & 𝑽𝑰𝑫𝑬𝑶 𝑬𝑵𝑮𝑰𝑵𝑬 🎶   │
│ 🛡️ 𝑺𝑬𝑹𝑽𝑬𝑹 𝑮𝑶𝑫 𝑪𝑳𝑨𝑵     │
╰──────────────────────────────╯
      ⚡ PREFIX  :  {P}
      🚀 SPEED   :  Ultra-Fast Non-Blocking
      🎧 ENGINES :  YouTube • JioSaavn • Spotify • Audius

╭─ ▶️ 𝒀𝑶𝑼𝑻𝑼𝑩𝑬 𝑽𝑰𝑫𝑬𝑶 & 𝑨𝑼𝑫𝑰𝑶
│ 🎥 {P}playvideo <Song/Link> (or {P}play2)
│    ▸ Instant 720p HD MP4 Video with H.264 Universal Mobile Codec
│ 🎵 {P}song <Song/Link> (or {P}play1 / {P}music)
│    ▸ Instant 320kbps MP3 Audio Download & Play
│ ⏱️ {P}playsec <seconds> [Song/Link]
│    ▸ Cut and send precise high-speed video clip
│ 🔁 {P}play5video
│    ▸ Continuous 5s High-Energy Loop in chat

╭─ 📞 𝑪𝑨𝑳𝑳 𝒀𝑶𝑼𝑻𝑼𝑩𝑬 𝑺𝑻𝑹𝑬𝑨𝑴𝑬𝑹
│ 🎶 {P}playytcall <Song/Link>
│    ▸ Stream YouTube Audio into Live Call in real-time
│ 📹 {P}play2ytcall <Song/Link>
│    ▸ Stream YouTube Video & Audio into Live Video Call
│ 🔊 {P}play1call (or {P}playcall)
│    ▸ Stream 51.mp3 high-bass loop directly into Call
│ 📺 {P}play2call
│    ▸ Stream 2.mp4 video loop directly into Video Call

╭─ 🎵 𝑱𝑰𝑶𝑺𝑨𝑨𝑽𝑵 & 𝑺𝑷𝑶𝑻𝑰𝑭𝒀
│ 🎧 {P}gana <Song Name>
│    ▸ Spotify official metadata + HD JioSaavn audio
│ 🎶 {P}songplay <Song Name>
│    ▸ Instant voice note (PTT) player
│ 🔁 {P}songloop <Song Name>
│    ▸ Continuous audio loop in chat
│ 🛑 {P}stopsong
│    ▸ Stop any ongoing chat audio loop

╭─ 💾 𝑪𝑼𝑺𝑻𝑶𝑴 𝑹𝑬𝑪𝑶𝑹𝑫𝑰𝑵𝑮𝑺
│ 💾 {P}saverd <name> / ▶️ {P}playrd <name>
│    ▸ Save and replay custom audio on VoIP Call

╭──────────────────────────────╮
│ ⚡ 𝑷𝑶𝑾𝑬𝑹𝑬𝑫 𝑩𝒀 𝑺𝑬𝑹𝑽𝑬𝑹 𝑮𝑶𝑫 𝑪𝑳𝑨𝑵 ⚡ │
╰──────────────────────────────╯`
	return strings.ReplaceAll(tpl, "{P}", prefix)
}

func getVoiceStudioMenu(prefix string) string {
	tpl := `╭──────────────────────────────╮
│ 🎙️ 𝑨𝑰 𝑽𝑶𝑰𝑪𝑬 𝑺𝑻𝑼𝑫𝑰𝑶 & 𝑪𝑳𝑶𝑵𝑬 👑 │
│ 🛡️ 𝑺𝑬𝑹𝑽𝑬𝑹 𝑮𝑶𝑫 𝑪𝑳𝑨𝑵     │
╰──────────────────────────────╯
      ⚡ PREFIX  :  {P}
      🧠 ENGINE  :  OpenVoice V2 + Neural TTS
      🎙️ OUTPUT  :  Native Voice Note (PTT) / HD Audio

╭─ 🎤 𝑨𝑰 𝑽𝑶𝑰𝑪𝑬 𝑵𝑶𝑻𝑬 (𝑻𝑻𝑺)
│ 🎙️ {P}vn <Text> (or {P}say <Text> / {P}tts <Text>)
│ 🤖 {P}robotvn <Text>
│ 🗣️ {P}clonevoice <Text>
╰──────────────────────

╭─ 📞 𝑽𝑶𝑰𝑷 𝑪𝑨𝑳𝑳 𝑽𝑶𝑰𝑪𝑬 𝑰𝑵𝑱𝑬𝑪𝑻𝑶𝑹
│ 🗣️ {P}cvn <Speech Text>
│ 💾 {P}saverd <name> / ▶️ {P}playrd <name>
╰──────────────────────

╭──────────────────────────────╮
│ ⚡ 𝑷𝑶𝑾𝑬𝑹𝑬𝑫 𝑩𝒀 𝑺𝑬𝑹𝑽𝑬𝑹 𝑮𝑶𝑫 𝑪𝑳𝑨𝑵 ⚡ │
╰──────────────────────────────╯`
	return strings.ReplaceAll(tpl, "{P}", prefix)
}
// ── Raid, Target & Utility Implementations in Go ──

var (
	raidMu          sync.Mutex
	targetList      = map[string]string{}
	muteList        = map[string]bool{}
	warnList        = map[string]int{}
	targetDelayMs   = 150
	nrDelayMs       = 50
	ncDelayMs       = 50
	spamDelayMs     = 50
	swipeDelayMs    = 100
	pfpDelayMs      = 1000
	picSpamDelayMs  = 1000
	pollSpamDelayMs = 1000
	antiLinkEnabled = false
	activeLoops     = map[string]chan struct{}{}
	emoji50Pool     = []string{
		"⚡", "🔥", "👑", "💀", "🛡️", "⚔️", "🦁", "🦅", "💣", "🩸",
		"🌪️", "💥", "🔱", "💎", "🚀", "☠️", "👹", "👺", "🥶", "😈",
		"🦇", "🐉", "☣️", "⚠️", "🚨", "🪐", "🌟", "✨", "🏆", "🎯",
		"🥇", "💫", "🖤", "🤍", "🤎", "💜", "💙", "💚", "💛", "🧡",
		"❤️", "🌹", "🐅", "🐆", "🐺", "🦂", "🕷️", "🎲", "🃏", "🚩",
	}
	roastList = []string{
		"😂 Beta King Bot ke aage aukaat me raha karo!",
		"🔥 Server God Clan ka rule hai — zyada uchloge to direct gayab ho jaoge!",
		"💀 Tu jis class me padh raha hai na, uska principal King Bot Ultra hai!",
		"⚡ Aukaat 2 paise ki nahi aur baatein aisi jaise group ke owner ho!",
		"👑 Chup chap kone me baith, warna group me spam flood aa jayega!",
		"💣 King Bot Ultra active hai, ek click me teri puri chat sweep ho jayegi!",
		"🤡 Shakal dekhi hai apni aaine me? DP lagane layak to hai nahi!",
		"🌪️ Hawa me mat ud, King Bot ke aage bade bade sher bheegi billi ban jate hain!",
		"🎯 Target locked ho chuka hai tera, ab chat chhod ke bhagne ka rasta dhoondh!",
		"⚡ Server God Clan ke sher jab bolte hain, to kutte apne aap chup ho jate hain!",
		"🔥 0.01s ki speed se typing chalti hai yahan, tu backspace dabate reh jayega!",
		"🏆 King Bot Ultra se ladne chala tha, khud ki aukaat dekh ke aana pehle!",
		"💀 R.I.P Teri Chat — King Bot Ultra has arrived!",
		"💥 Teri aukaat King Bot ke ek notification barabar bhi nahi hai!",
		"👑 Badshah se mukabla karne ke liye aukaat aur dam dono chahiye!",
	}
)

func handleWarn(ctx context.Context, evt *events.Message, args string) {
	targetNum := strings.NewReplacer("@", "", "+", "", " ", "", "-", "").Replace(strings.TrimSpace(args))
	if targetNum == "" {
		sendText(ctx, evt.Info.Chat, "❌ Usage: `-warn @mention`")
		return
	}
	raidMu.Lock()
	warnList[targetNum]++
	cnt := warnList[targetNum]
	raidMu.Unlock()
	sendText(ctx, evt.Info.Chat, fmt.Sprintf("⚠️ *[USER WARNED]*\n• Target: `@%s`\n• Warnings: *%d/3*", targetNum, cnt))
	if cnt >= 3 {
		sendText(ctx, evt.Info.Chat, fmt.Sprintf("🚨 `@%s` reached max warnings (3/3). Removing from group...", targetNum))
		handleKickParticipant(ctx, evt, targetNum)
	}
}

func handleResetWarn(ctx context.Context, evt *events.Message, args string) {
	targetNum := strings.NewReplacer("@", "", "+", "", " ", "", "-", "").Replace(strings.TrimSpace(args))
	raidMu.Lock()
	delete(warnList, targetNum)
	raidMu.Unlock()
	sendText(ctx, evt.Info.Chat, fmt.Sprintf("🔄 *Warnings reset for `@%s`*", targetNum))
}

func handlePFPChange(ctx context.Context, evt *events.Message) {
	if !evt.Info.IsGroup {
		return
	}
	stopChan := make(chan struct{})
	chatKey := evt.Info.Chat.String() + "_pfp"
	raidMu.Lock()
	if old, exists := activeLoops[chatKey]; exists {
		close(old)
	}
	activeLoops[chatKey] = stopChan
	raidMu.Unlock()
	sendText(ctx, evt.Info.Chat, "📸 *[AUTO PFP STARTED]* Group icon rotation running...")
}

func handleStopPFP(ctx context.Context, evt *events.Message) {
	chatKey := evt.Info.Chat.String() + "_pfp"
	raidMu.Lock()
	if stop, ok := activeLoops[chatKey]; ok {
		close(stop)
		delete(activeLoops, chatKey)
	}
	raidMu.Unlock()
	sendText(ctx, evt.Info.Chat, "🛑 *Auto PFP Stopped!*")
}

func handlePicSpam(ctx context.Context, evt *events.Message, caption string) {
	if caption == "" {
		caption = "👑 KING BOT ULTRA PIC SPAM ⚡"
	}
	stopChan := make(chan struct{})
	chatKey := evt.Info.Chat.String() + "_picspam"
	raidMu.Lock()
	if old, exists := activeLoops[chatKey]; exists {
		close(old)
	}
	activeLoops[chatKey] = stopChan
	raidMu.Unlock()
	sendText(ctx, evt.Info.Chat, "🖼️ *[PIC SPAM STARTED]* Picture spam loop running...")
}

func handleStopPicSpam(ctx context.Context, evt *events.Message) {
	chatKey := evt.Info.Chat.String() + "_picspam"
	raidMu.Lock()
	if stop, ok := activeLoops[chatKey]; ok {
		close(stop)
		delete(activeLoops, chatKey)
	}
	raidMu.Unlock()
	sendText(ctx, evt.Info.Chat, "🛑 *Pic Spam Stopped!*")
}

func handlePollSpam(ctx context.Context, evt *events.Message, args string) {
	parts := strings.Split(args, "|")
	title := "👑 SERVER GOD CLAN POLL ⚡"
	if len(parts) > 0 && strings.TrimSpace(parts[0]) != "" {
		title = strings.TrimSpace(parts[0])
	}
	opts := []string{"Option 1 🔥", "Option 2 ⚡", "Option 3 👑"}
	if len(parts) > 1 {
		opts = nil
		for _, o := range parts[1:] {
			if strings.TrimSpace(o) != "" {
				opts = append(opts, strings.TrimSpace(o))
			}
		}
	}
	stopChan := make(chan struct{})
	chatKey := evt.Info.Chat.String() + "_pollspam"
	raidMu.Lock()
	if old, exists := activeLoops[chatKey]; exists {
		close(old)
	}
	activeLoops[chatKey] = stopChan
	raidMu.Unlock()
	sendText(ctx, evt.Info.Chat, "📊 *[POLL SPAM STARTED]* Poll spam flood running...")
	go func() {
		for {
			select {
			case <-stopChan:
				return
			default:
				_, _ = waClient.SendMessage(ctx, evt.Info.Chat, waClient.BuildPollCreation(title, opts, 1))
				time.Sleep(time.Duration(pollSpamDelayMs) * time.Millisecond)
			}
		}
	}()
}

func handleStopPollSpam(ctx context.Context, evt *events.Message) {
	chatKey := evt.Info.Chat.String() + "_pollspam"
	raidMu.Lock()
	if stop, ok := activeLoops[chatKey]; ok {
		close(stop)
		delete(activeLoops, chatKey)
	}
	raidMu.Unlock()
	sendText(ctx, evt.Info.Chat, "🛑 *Poll Spam Stopped!*")
}

func handleCreateGC(ctx context.Context, evt *events.Message, name string) {
	if name == "" {
		name = "👑 KING BOT GROUP ⚡"
	}
	resp, err := waClient.CreateGroup(ctx, whatsmeow.ReqCreateGroup{
		Subject: name,
	})
	if err != nil {
		sendText(ctx, evt.Info.Chat, fmt.Sprintf("❌ Failed to create group: %v", err))
		return
	}
	sendText(ctx, evt.Info.Chat, fmt.Sprintf("🎉 *Group Created Successfully!*\n• Name: *%s*\n• JID: `%s`", name, resp.JID.String()))
}

func handleTarget(ctx context.Context, evt *events.Message, args string) {
	parts := strings.Fields(args)
	if len(parts) == 0 {
		sendText(ctx, evt.Info.Chat, "❌ Usage: `+target @mention <Custom Text>`")
		return
	}
	targetNum := strings.NewReplacer("@", "", "+", "", " ", "", "-", "").Replace(parts[0])
	replyText := "Tera Baap King Bot Ultra hai!"
	if len(parts) > 1 {
		replyText = strings.Join(parts[1:], " ")
	}
	raidMu.Lock()
	targetList[targetNum] = replyText
	raidMu.Unlock()
	reactMsg(ctx, evt, "🎯")
	sendText(ctx, evt.Info.Chat, fmt.Sprintf("🎯 *[TARGET LOCKED]*\n• Target: `@%s`\n• Auto-Reply: *%s*\n• Status: *Active 0.01s instant counter*", targetNum, replyText))
}

func handleStopTarget(ctx context.Context, evt *events.Message, args string) {
	targetNum := strings.NewReplacer("@", "", "+", "", " ", "", "-", "").Replace(strings.TrimSpace(args))
	raidMu.Lock()
	delete(targetList, targetNum)
	raidMu.Unlock()
	reactMsg(ctx, evt, "🛑")
	sendText(ctx, evt.Info.Chat, fmt.Sprintf("🛑 Target unlocked for `@%s`", targetNum))
}

func handleStopTargetAll(ctx context.Context, evt *events.Message) {
	raidMu.Lock()
	targetList = map[string]string{}
	raidMu.Unlock()
	reactMsg(ctx, evt, "🧹")
	sendText(ctx, evt.Info.Chat, "🧹 *All targets cleared!*")
}

func handleTargetList(ctx context.Context, evt *events.Message) {
	raidMu.Lock()
	defer raidMu.Unlock()
	if len(targetList) == 0 {
		sendText(ctx, evt.Info.Chat, "📋 *Target List is empty.*")
		return
	}
	var b strings.Builder
	fmt.Fprintf(&b, "🎯 *ACTIVE TARGET MATRIX (%d)*\n\n", len(targetList))
	for num, txt := range targetList {
		fmt.Fprintf(&b, "• `@%s` ➔ %s\n", num, txt)
	}
	sendText(ctx, evt.Info.Chat, b.String())
}

func handleRoast(ctx context.Context, evt *events.Message, args string) {
	target := strings.TrimSpace(args)
	rIndex := int(time.Now().UnixNano()) % len(roastList)
	roastMsg := roastList[rIndex]
	if target != "" {
		sendText(ctx, evt.Info.Chat, fmt.Sprintf("💀 %s\n%s", target, roastMsg))
	} else {
		sendText(ctx, evt.Info.Chat, fmt.Sprintf("💀 %s", roastMsg))
	}
}

func handleNameRaid(ctx context.Context, evt *events.Message, baseName string) {
	if !evt.Info.IsGroup {
		sendText(ctx, evt.Info.Chat, "❌ NR only works in Groups!")
		return
	}
	if baseName == "" {
		baseName = "KING BOT ULTRA"
	}
	stopChan := make(chan struct{})
	chatKey := evt.Info.Chat.String() + "_nr"
	raidMu.Lock()
	if old, exists := activeLoops[chatKey]; exists {
		close(old)
	}
	activeLoops[chatKey] = stopChan
	raidMu.Unlock()

	reactMsg(ctx, evt, "⚡")
	sendText(ctx, evt.Info.Chat, fmt.Sprintf("⚡ *[50-EMOJI NR STARTED]*\n• Base: *%s*\n• Status: *Continuous 50-Emoji Rotation*\n_Use `+stopnr` to stop._", baseName))

	go func() {
		idx := 0
		zw := []string{"", "\u200B", "\u200C", "\u200D", "\uFEFF"}
		for {
			select {
			case <-stopChan:
				return
			default:
				em1 := emoji50Pool[idx%len(emoji50Pool)]
				em2 := emoji50Pool[(idx+1)%len(emoji50Pool)]
				z := zw[idx%len(zw)]
				title := fmt.Sprintf("%s %s %s%s", em1, baseName, em2, z)
				if len(title) > 25 {
					title = title[:25]
				}
				_ = waClient.SetGroupName(ctx, evt.Info.Chat, title)
				idx++
				time.Sleep(time.Duration(nrDelayMs) * time.Millisecond)
			}
		}
	}()
}

func handleStopNR(ctx context.Context, evt *events.Message) {
	chatKey := evt.Info.Chat.String() + "_nr"
	raidMu.Lock()
	if stop, ok := activeLoops[chatKey]; ok {
		close(stop)
		delete(activeLoops, chatKey)
	}
	raidMu.Unlock()
	reactMsg(ctx, evt, "🛑")
	sendText(ctx, evt.Info.Chat, "🛑 *NR (Name Raid) Stopped!*")
}

func handleNameChange(ctx context.Context, evt *events.Message, baseName string) {
	if !evt.Info.IsGroup {
		sendText(ctx, evt.Info.Chat, "❌ NC only works in Groups!")
		return
	}
	if baseName == "" {
		baseName = "SERVER GOD CLAN"
	}
	stopChan := make(chan struct{})
	chatKey := evt.Info.Chat.String() + "_nc"
	raidMu.Lock()
	if old, exists := activeLoops[chatKey]; exists {
		close(old)
	}
	activeLoops[chatKey] = stopChan
	raidMu.Unlock()

	reactMsg(ctx, evt, "🌀")
	sendText(ctx, evt.Info.Chat, fmt.Sprintf("🌀 *[50-EMOJI TURBO NC STARTED]*\n• Base: *%s*\n• Status: *Active*\n_Use `+stopnc` to stop._", baseName))

	go func() {
		idx := 0
		for {
			select {
			case <-stopChan:
				return
			default:
				em := emoji50Pool[idx%len(emoji50Pool)]
				title := fmt.Sprintf("%s %s %s", em, baseName, em)
				if len(title) > 25 {
					title = title[:25]
				}
				_ = waClient.SetGroupName(ctx, evt.Info.Chat, title)
				idx++
				time.Sleep(time.Duration(ncDelayMs) * time.Millisecond)
			}
		}
	}()
}

func handleStopNC(ctx context.Context, evt *events.Message) {
	chatKey := evt.Info.Chat.String() + "_nc"
	raidMu.Lock()
	if stop, ok := activeLoops[chatKey]; ok {
		close(stop)
		delete(activeLoops, chatKey)
	}
	raidMu.Unlock()
	reactMsg(ctx, evt, "🛑")
	sendText(ctx, evt.Info.Chat, "🛑 *NC (Name Change) Stopped!*")
}

func handleGDC(ctx context.Context, evt *events.Message, desc string) {
	if !evt.Info.IsGroup {
		return
	}
	if desc == "" {
		desc = "👑 POWERED BY SERVER GOD CLAN ⚡"
	}
	stopChan := make(chan struct{})
	chatKey := evt.Info.Chat.String() + "_gdc"
	raidMu.Lock()
	if old, exists := activeLoops[chatKey]; exists {
		close(old)
	}
	activeLoops[chatKey] = stopChan
	raidMu.Unlock()

	sendText(ctx, evt.Info.Chat, "📝 *[GDC STARTED]* Continuous group description raid running...")
	go func() {
		idx := 0
		for {
			select {
			case <-stopChan:
				return
			default:
				em := emoji50Pool[idx%len(emoji50Pool)]
				_ = waClient.SetGroupTopic(ctx, evt.Info.Chat, "", "", fmt.Sprintf("%s %s %s", em, desc, em))
				idx++
				time.Sleep(100 * time.Millisecond)
			}
		}
	}()
}

func handleStopGDC(ctx context.Context, evt *events.Message) {
	chatKey := evt.Info.Chat.String() + "_gdc"
	raidMu.Lock()
	if stop, ok := activeLoops[chatKey]; ok {
		close(stop)
		delete(activeLoops, chatKey)
	}
	raidMu.Unlock()
	sendText(ctx, evt.Info.Chat, "🛑 *GDC Stopped!*")
}

func handleSendDM(ctx context.Context, evt *events.Message, args string) {
	parts := strings.Fields(args)
	if len(parts) < 2 {
		sendText(ctx, evt.Info.Chat, "❌ Usage: `+send <Phone Number> <Message>`")
		return
	}
	targetNum := strings.NewReplacer("+", "", " ", "", "-", "").Replace(parts[0])
	targetJID := types.NewJID(targetNum, types.DefaultUserServer)
	msgText := strings.Join(parts[1:], " ")
	sendText(ctx, targetJID, msgText)
	reactMsg(ctx, evt, "📨")
	sendText(ctx, evt.Info.Chat, fmt.Sprintf("✅ *Delivered message to `+%s`!*", targetNum))
}

func handleSpam(ctx context.Context, evt *events.Message, text string) {
	if text == "" {
		text = "👑 KING BOT ULTRA ⚡ SERVER GOD CLAN 🛡️"
	}
	stopChan := make(chan struct{})
	chatKey := evt.Info.Chat.String() + "_spam"
	raidMu.Lock()
	if old, exists := activeLoops[chatKey]; exists {
		close(old)
	}
	activeLoops[chatKey] = stopChan
	raidMu.Unlock()

	reactMsg(ctx, evt, "🚀")
	go func() {
		for {
			select {
			case <-stopChan:
				return
			default:
				sendText(ctx, evt.Info.Chat, text)
				time.Sleep(50 * time.Millisecond)
			}
		}
	}()
}

func handleStopSpam(ctx context.Context, evt *events.Message) {
	chatKey := evt.Info.Chat.String() + "_spam"
	raidMu.Lock()
	if stop, ok := activeLoops[chatKey]; ok {
		close(stop)
		delete(activeLoops, chatKey)
	}
	raidMu.Unlock()
	reactMsg(ctx, evt, "🛑")
	sendText(ctx, evt.Info.Chat, "🛑 *Spam Stopped!*")
}

func handleSwipe(ctx context.Context, evt *events.Message, text string) {
	if text == "" {
		text = "🌊 SWIPE FLOOD BY KING BOT ULTRA ⚡"
	}
	stopChan := make(chan struct{})
	chatKey := evt.Info.Chat.String() + "_swipe"
	raidMu.Lock()
	if old, exists := activeLoops[chatKey]; exists {
		close(old)
	}
	activeLoops[chatKey] = stopChan
	raidMu.Unlock()

	go func() {
		for {
			select {
			case <-stopChan:
				return
			default:
				sendText(ctx, evt.Info.Chat, text)
				time.Sleep(100 * time.Millisecond)
			}
		}
	}()
}

func handleStopSwipe(ctx context.Context, evt *events.Message) {
	chatKey := evt.Info.Chat.String() + "_swipe"
	raidMu.Lock()
	if stop, ok := activeLoops[chatKey]; ok {
		close(stop)
		delete(activeLoops, chatKey)
	}
	raidMu.Unlock()
	sendText(ctx, evt.Info.Chat, "🛑 *Swipe Stopped!*")
}

func handleStopAllLoops(ctx context.Context, evt *events.Message) {
	raidMu.Lock()
	for _, stop := range activeLoops {
		close(stop)
	}
	activeLoops = map[string]chan struct{}{}
	targetList = map[string]string{}
	raidMu.Unlock()
	reactMsg(ctx, evt, "🚨")
	sendText(ctx, evt.Info.Chat, "🚨 *[MASTER ABORT]* All active loops & targets terminated!")
}

func handlePin(ctx context.Context, evt *events.Message, unpin bool) {
	ctxInfo := evt.Message.GetExtendedTextMessage().GetContextInfo()
	if ctxInfo.GetStanzaID() == "" {
		sendText(ctx, evt.Info.Chat, "❌ Reply to a message with `+pin` or `+unpin`")
		return
	}
	reactMsg(ctx, evt, "📌")
	sendText(ctx, evt.Info.Chat, "📌 *Pin action dispatched!*")
}

func handlePinSpam(ctx context.Context, evt *events.Message, args string) {
	if strings.ToLower(args) == "off" || strings.ToLower(args) == "stop" {
		chatKey := evt.Info.Chat.String() + "_pinspam"
		raidMu.Lock()
		if stop, ok := activeLoops[chatKey]; ok {
			close(stop)
			delete(activeLoops, chatKey)
		}
		raidMu.Unlock()
		sendText(ctx, evt.Info.Chat, "🛑 *Pin spam stopped!*")
		return
	}
	stopChan := make(chan struct{})
	chatKey := evt.Info.Chat.String() + "_pinspam"
	raidMu.Lock()
	if old, exists := activeLoops[chatKey]; exists {
		close(old)
	}
	activeLoops[chatKey] = stopChan
	raidMu.Unlock()

	reactMsg(ctx, evt, "📌")
	sendText(ctx, evt.Info.Chat, "📌 *Pin Spam Active!* _Type `+pinspam off` to stop._")
}

func handleMute(ctx context.Context, evt *events.Message, args string, mute bool) {
	target := strings.NewReplacer("@", "", "+", "", " ", "", "-", "").Replace(strings.TrimSpace(args))
	if target == "" {
		sendText(ctx, evt.Info.Chat, "❌ Usage: `+mute @mention` / `+unmute @mention`")
		return
	}
	raidMu.Lock()
	if mute {
		muteList[target] = true
	} else {
		delete(muteList, target)
	}
	raidMu.Unlock()
	if mute {
		reactMsg(ctx, evt, "🔇")
		sendText(ctx, evt.Info.Chat, fmt.Sprintf("🔇 *Auto-delete/Mute active for `@%s`*", target))
	} else {
		reactMsg(ctx, evt, "🔊")
		sendText(ctx, evt.Info.Chat, fmt.Sprintf("🔊 *Unmuted `@%s`*", target))
	}
}

func handleViewFiles(ctx context.Context, evt *events.Message) {
	var filesList []string
	if entries, err := os.ReadDir("recordings"); err == nil {
		for _, e := range entries {
			if !e.IsDir() {
				if info, err := e.Info(); err == nil {
					sz := float64(info.Size()) / 1024.0
					filesList = append(filesList, fmt.Sprintf("🎵 *%s* (`%.1f KB` | `./recordings/`)", e.Name(), sz))
				}
			}
		}
	}
	if entries, err := os.ReadDir("."); err == nil {
		for _, e := range entries {
			if !e.IsDir() && (strings.HasSuffix(e.Name(), ".mp3") || strings.HasSuffix(e.Name(), ".mp4") || strings.HasSuffix(e.Name(), ".opus")) {
				if info, err := e.Info(); err == nil {
					sz := float64(info.Size()) / 1024.0
					filesList = append(filesList, fmt.Sprintf("🎵 *%s* (`%.1f KB` | `./`)", e.Name(), sz))
				}
			}
		}
	}
	if len(filesList) == 0 {
		sendText(ctx, evt.Info.Chat, "📁 *No saved media or audio files found.*")
		return
	}
	txt := fmt.Sprintf("╔══〔 📁 *SAVED FILES VAULT (%d)* 〕══╗\n", len(filesList))
	for i, f := range filesList {
		txt += fmt.Sprintf("┃ %d. %s\n", i+1, f)
	}
	txt += "╚════════════════════════════════════╝\n💡 *Actions:*\n• Stream on call: `+playrd <name>`\n• Delete file: `+delfile <filename>`"
	sendText(ctx, evt.Info.Chat, txt)
}

func handleDelFile(ctx context.Context, evt *events.Message, args string) {
	fileName := strings.TrimSpace(args)
	if fileName == "" {
		sendText(ctx, evt.Info.Chat, "❌ Usage: `+delfile <filename>`")
		return
	}
	paths := []string{
		filepath.Join("recordings", fileName),
		fileName,
		filepath.Join("recordings", fileName+".mp3"),
	}
	for _, p := range paths {
		if _, err := os.Stat(p); err == nil {
			_ = os.Remove(p)
			reactMsg(ctx, evt, "🗑️")
			sendText(ctx, evt.Info.Chat, fmt.Sprintf("🗑️ *[FILE REMOVED]* Successfully deleted `%s`", filepath.Base(p)))
			return
		}
	}
	sendText(ctx, evt.Info.Chat, fmt.Sprintf("❌ File `%s` not found.", fileName))
}
