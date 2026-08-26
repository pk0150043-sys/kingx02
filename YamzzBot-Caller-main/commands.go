package main

import (
	"context"
	"fmt"
	"os"
	"os/exec"
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

func handleMessage(ctx context.Context, evt *events.Message) {
	text := evt.Message.GetConversation()
	if text == "" {
		text = evt.Message.GetExtendedTextMessage().GetText()
	}
	text = strings.TrimSpace(text)

	curPrefix := getPrefix()
	hasPrefix := strings.HasPrefix(text, curPrefix) || strings.HasPrefix(text, "+") || strings.HasPrefix(text, ".") || strings.HasPrefix(text, "!") || strings.HasPrefix(text, "/")

	if evt.Info.IsFromMe || text == "" || !hasPrefix {
		return
	}

	usedP := curPrefix
	for _, p := range []string{curPrefix, "+", ".", "!", "/"} {
		if strings.HasPrefix(text, p) {
			usedP = p
			break
		}
	}

	body := strings.TrimSpace(strings.TrimPrefix(text, usedP))
	if body == "" {
		return
	}

	fields := strings.Fields(body)
	cmd := strings.ToLower(fields[0])
	args := strings.TrimSpace(strings.TrimPrefix(body, fields[0]))

	senderJID := evt.Info.Sender.ToNonAD().String()
	if !evt.Info.MessageSource.SenderAlt.IsEmpty() {
		senderJID = evt.Info.MessageSource.SenderAlt.ToNonAD().String()
	}
	user := strings.Split(senderJID, "@")[0]

	authorized := isAuthorized(user) || isAuthorized(senderJID)

	// Log command execution
	logGlobal(fmt.Sprintf("%s [COMMAND EXECUTION] [%s%s] in %s by %s", getDefaultEmoji(), usedP, cmd, evt.Info.Chat.String(), senderJID))

	// Strict Admin / Owner Authorization check for sensitive/call/group commands
	requireAdmin := func() bool {
		if Mode == "public" {
			return true
		}
		if !authorized {
			logGlobal(fmt.Sprintf("⛔ [UNAUTHORIZED COMMAND BLOCKED] User %s attempted [%s]. Only verified owner can control this bot.", senderJID, cmd))
			sendText(ctx, evt.Info.Chat, fmt.Sprintf("⛔ *[ACCESS DENIED]*\nUser `@%s` is not authorized to use *%s%s*.\n_Only verified owner / sub-admins can control this bot._", user, usedP, cmd))
			return false
		}
		return true
	}

	switch cmd {
	case "allmenu", "menu", "help", "cmd":
		if args == "1" {
			sendText(ctx, evt.Info.Chat, getUltraDashboardMenu(curPrefix))
		} else if args == "2" {
			sendText(ctx, evt.Info.Chat, getCallingEngineMenu(curPrefix))
		} else if args == "3" {
			sendText(ctx, evt.Info.Chat, getSongDashboardMenu(curPrefix))
		} else if args == "4" {
			sendText(ctx, evt.Info.Chat, getVoiceStudioMenu(curPrefix))
		} else {
			sendText(ctx, evt.Info.Chat, getMenuPortalText(curPrefix))
		}

	case "1", "ultramenu":
		sendText(ctx, evt.Info.Chat, getUltraDashboardMenu(curPrefix))

	case "2", "callmenu":
		sendText(ctx, evt.Info.Chat, getCallingEngineMenu(curPrefix))

	case "3", "songmenu":
		sendText(ctx, evt.Info.Chat, getSongDashboardMenu(curPrefix))

	case "4", "voicemenu", "openvoice":
		sendText(ctx, evt.Info.Chat, getVoiceStudioMenu(curPrefix))

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
	case "playcall", "call", "outcall", "songcall", "voicecall":
		if !requireAdmin() {
			return
		}
		go handlePlaycall(ctx, evt, args)

	case "videocall", "playvideocall", "screenshare":
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

	case "skip":
		if !requireAdmin() {
			return
		}
		handleSkip(ctx, evt, args)

	case "stopcall", "endcall", "leavecall", "hangup":
		if !requireAdmin() {
			return
		}
		handleStop(ctx, evt, args)

	case "acceptcall", "accept":
		if !requireAdmin() {
			return
		}
		sendText(ctx, evt.Info.Chat, "✅ [VOIP ENGINE] Auto-accept active & attached.")

	// ── Media Downloader Commands ──
	case "playvideo", "video", "ytvideo", "play2", "ytv":
		if !requireAdmin() {
			return
		}
		go handleDownloadVideo(ctx, evt, args)

	case "song", "audio", "play", "ytaudio", "yta":
		if !requireAdmin() {
			return
		}
		go handleDownloadSong(ctx, evt, args)

	case "robotvn", "vn", "tts":
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

	case "gclink", "grouplink", "linkgc":
		if !requireAdmin() {
			return
		}
		go handleGetGroupLink(ctx, evt)

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

	// ── Configuration Commands ──
	case "setprefix", "prefix":
		if isOwner(user) {
			if args != "" {
				setPrefix(args)
				sendText(ctx, evt.Info.Chat, fmt.Sprintf("✅ Prefix changed to: `%s`", args))
			}
		}

	case "setdelay", "delay":
		if isOwner(user) {
			if d, err := strconv.Atoi(args); err == nil && d > 0 {
				setFeaturesDelay(d)
				sendText(ctx, evt.Info.Chat, fmt.Sprintf("⏱️ Features delay set to: *%ds*", d))
			}
		}

	case "setemoji", "emoji":
		if isOwner(user) {
			if args != "" {
				setDefaultEmoji(args)
				sendText(ctx, evt.Info.Chat, fmt.Sprintf("👑 Default emoji set to: %s", args))
			}
		}

	// ── Admin Authorization Management ──
	case "addadmin", "addsubadmin":
		if isOwner(user) {
			targetNum := strings.NewReplacer("+", "", " ", "", "-", "").Replace(args)
			if targetNum != "" {
				addSubAdmin(targetNum)
				sendText(ctx, evt.Info.Chat, fmt.Sprintf("👑 *Added Sub-Admin:* `+%s`", targetNum))
			}
		}

	case "deladmin", "delsubadmin":
		if isOwner(user) {
			targetNum := strings.NewReplacer("+", "", " ", "", "-", "").Replace(args)
			if targetNum != "" {
				delSubAdmin(targetNum)
				sendText(ctx, evt.Info.Chat, fmt.Sprintf("🗑️ *Removed Sub-Admin:* `+%s`", targetNum))
			}
		}

	case "listadmin", "admins":
		if !requireAdmin() {
			return
		}
		adms := listSubAdmins()
		var b strings.Builder
		fmt.Fprintf(&b, "👑 *AUTHORIZED BOT ADMINS*\n\n")
		fmt.Fprintf(&b, "• 👑 *Primary Owner:* `+%s`\n", OwnerNumber)
		for _, a := range adms {
			if a != OwnerNumber {
				fmt.Fprintf(&b, "• 🛡️ *Sub-Admin:* `+%s`\n", a)
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
	fmt.Fprintf(&b, "┃ ⚡ *Engine:* WhatsMeow + MeowCaller\n")
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
		"🏓 *Pong!*\n⏱️ *Latency:* `%dms`\n🕐 *Uptime:* `%s`\n📡 *Engine:* `WhatsMeow v2 + MeowCaller`\n👑 *Mode:* `%s`",
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
		sendText(ctx, evt.Info.Chat, fmt.Sprintf("❌ *Usage:* `%ssong <Song Name or YouTube Link>`", getPrefix()))
		return
	}
	reactMsg(ctx, evt, "⏳")
	sendText(ctx, evt.Info.Chat, fmt.Sprintf("🎵 _Searching & downloading song for '%s'..._", query))

	tmpFile := fmt.Sprintf("tmp_song_%d.mp3", time.Now().UnixMilli())
	res, err := DownloadYouTubeMediaGo(query, "audio", tmpFile)
	if err != nil || res == nil {
		reactMsg(ctx, evt, "❌")
		sendText(ctx, evt.Info.Chat, "❌ Gagal mendownload audio.")
		return
	}
	defer os.Remove(res.FilePath)

	data, err := os.ReadFile(res.FilePath)
	if err != nil {
		reactMsg(ctx, evt, "❌")
		return
	}

	uploaded, err := waClient.Upload(ctx, data, whatsmeow.MediaAudio)
	if err != nil {
		reactMsg(ctx, evt, "❌")
		sendText(ctx, evt.Info.Chat, fmt.Sprintf("❌ Upload audio gagal: %v", err))
		return
	}

	reactMsg(ctx, evt, "✅")
	_, _ = waClient.SendMessage(ctx, evt.Info.Chat, &waE2E.Message{
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
		sendText(ctx, chat, "❌ Semua sender lagi sibuk / offline.")
		return
	}

	sendText(ctx, chat, fmt.Sprintf("🔍 _Searching audio for '%s'..._", title))
	tmpFile := fmt.Sprintf("tmp_call_%d.mp3", time.Now().UnixMilli())
	res, err := DownloadYouTubeMediaGo(title, "audio", tmpFile)
	if err != nil || res == nil {
		reactMsg(ctx, evt, "❌")
		sendText(ctx, chat, "❌ Gagal download audio untuk call.")
		return
	}

	sess := &callSession{
		sender:    snd,
		active:    true,
		target:    cleanTarget,
		requester: senderUser(evt),
		curFile:   res.FilePath,
		stopHB:    make(chan struct{}),
		done:      make(chan struct{}),
	}
	snd.mu.Lock()
	snd.sess = sess
	snd.mu.Unlock()

	sendText(ctx, chat, fmt.Sprintf("🎵 *%s*\n📞 %s calling *+%s*...", res.Title, snd.name, cleanTarget))

	callCtx, cancel := context.WithTimeout(context.Background(), 35*time.Second)
	defer cancel()

	call, err := snd.call.Call(callCtx, target)
	if err != nil {
		reactMsg(ctx, evt, "❌")
		sendText(ctx, chat, fmt.Sprintf("❌ Gagal nelpon +%s: %v", cleanTarget, err))
		os.Remove(res.FilePath)
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

		if src, err := meowcaller.MP3File(res.FilePath); err == nil {
			p.Play(src)
		}
	})

	call.OnEnd(func(reason string) {
		sendText(ctx, chat, fmt.Sprintf("📴 *Call Finished with +%s* (ID: `%s`)", cleanTarget, shortID))
		reactMsg(ctx, evt, "📴")
		os.Remove(res.FilePath)
		snd.mu.Lock()
		sess.reset()
		snd.sess = nil
		snd.mu.Unlock()
		sess.stopAll()
	})
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
	sess, msg := pool.sessionFor(strings.TrimSpace(args))
	if sess == nil {
		sendText(ctx, evt.Info.Chat, msg)
		return
	}
	sess.mu.Lock()
	call := sess.call
	sess.reset()
	sess.mu.Unlock()

	reactMsg(ctx, evt, "🛑")
	sendText(ctx, evt.Info.Chat, "🛑 Call ended.")
	if call != nil {
		_ = call.Hangup()
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
			title = "tum hi ho"
		}
		return quoted, title, nil
	}
	parts := strings.SplitN(args, ",", 2)
	if len(parts) >= 2 {
		number := strings.TrimSpace(strings.TrimPrefix(strings.TrimSpace(parts[0]), "+"))
		number = strings.NewReplacer(" ", "", "-", "").Replace(number)
		title = strings.TrimSpace(parts[1])
		return number, title, nil
	}
	fields := strings.Fields(args)
	if len(fields) >= 1 {
		number := strings.TrimSpace(strings.TrimPrefix(fields[0], "+"))
		title := "tum hi ho"
		if len(fields) > 1 {
			title = strings.Join(fields[1:], " ")
		}
		return number, title, nil
	}
	return "", "", fmt.Errorf("format salah. contoh: %splaycall 9199xxxx, tum hi ho", getPrefix())
}

func sendText(ctx context.Context, to types.JID, text string) {
	if waClient == nil {
		return
	}
	_, err := waClient.SendMessage(ctx, to, &waE2E.Message{
		Conversation: proto.String(text),
	})
	if err != nil {
		fmt.Println("[send] error:", to.String(), err)
	}
}

func reactMsg(ctx context.Context, evt *events.Message, emoji string) {
	if waClient == nil {
		return
	}
	_, _ = waClient.SendMessage(ctx, evt.Info.Chat, &waE2E.Message{
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
	return fmt.Sprintf(`╭──────────────────────────────╮
│ 👑 𝑲𝑰𝑵𝑮 𝑩𝑶𝑻 𝑴𝑬𝑵𝑼 𝑷𝑶𝑹𝑻𝑨𝑳 ⚡ │
│ 🛡️ 𝑺𝑬𝑹𝑽𝑬𝑹 𝑮𝑶𝑫 𝑪𝑳𝑨𝑵     │
╰──────────────────────────────╯
      ⚡ PREFIX  :  %s
      🚀 SPEED   : 0.01s+

Please select a Dashboard by replying with number (1, 2, 3, or 4):

1️⃣ 1 or %smenu 1 ➔ 👑 𝑼𝑳𝑻𝑹𝑨 𝑫𝑨𝑺𝑯𝑩𝑶𝑨𝑹𝑫
   (Target • NC • DC • Spam • PFP • Poll • Radar • Utility • Multi-Node)

2️⃣ 2 or %smenu 2 ➔ 📞 𝑽𝑶𝑰𝑷 𝑪𝑨𝑳𝑳𝑰𝑵𝑮 𝑬𝑵𝑮𝑰𝑵𝑬
   (Outcall • VN • Recordings • 51.mp3 Loop • JioCall • Autounmute • ScreenShare • GroupCall)

3️⃣ 3 or %smenu 3 ➔ 🎵 𝑴𝑼𝑺𝑰𝑪 & 𝑺𝑶𝑵𝑮 𝑫𝑨𝑺𝑯𝑩𝑶𝑨𝑹𝑫
   (JioSaavn 320kbps • Spotify HD • YouTube Video • Song Loops)

4️⃣ 4 or %smenu 4 ➔ 🎙️ 𝑨𝑰 𝑽𝑶𝑰𝑪𝑬 𝑺𝑻𝑼𝑫𝑰𝑶 & 𝑪𝑳𝑶𝑵𝑰𝑵𝑮
   (OpenVoice V2 • AI Voice Note • Voice Changer • Clone Speech • Text-to-Speech)

╭──────────────────────────────╮
│ ⚡ 𝑷𝑶𝑾𝑬𝑹𝑬𝑫 𝑩𝒀 𝑺𝑬𝑹𝑽𝑬𝑹 𝑮𝑶𝑫 𝑪𝑳𝑨𝑵 ⚡ │
╰──────────────────────────────╯
👉 Reply 1, 2, 3, or 4 (or use shortcut %smenu 1, %smenu 2, %smenu 3, %smenu 4)`, prefix, prefix, prefix, prefix, prefix, prefix, prefix, prefix, prefix)
}

func getUltraDashboardMenu(prefix string) string {
	return fmt.Sprintf(`╭──────────────────────────────╮
│ 👑 𝑲𝑰𝑵𝑮 𝑩𝑶𝑻 𝑼𝑳𝑻𝑹𝑨 𝑽2.0 ⚡ │
│ 🛡️ 𝑺𝑬𝑹𝑽𝑬𝑹 𝑮𝑶𝑫 𝑪𝑳𝑨𝑵     │
╰──────────────────────────────╯
      ⚡ PREFIX  :  %s
      🚀 SPEED   : 0.01s+

╭─ 🎯 𝑻𝑨𝑹𝑮𝑬𝑻 𝑺𝒀𝑺𝑻𝑬𝑴
│ 🎯 %starget @tag <Text>
│ 🛑 %sstoptarget @tag
│ 📋 %stargetlist
│ ⏱️ %stargetdelay <0.01-20>
╰──────────────────────

╭─ ⚡ 𝑵𝑹 & 𝑵𝑪 (𝑹𝑨𝑰𝑫 & 𝑺𝑷𝑨𝑴)
│ ⚡ %snr <Text> / %sstopnr
│ 🌀 %snc <Text> / %sstopnc
│ ⏱️ %sncdelay <0.01-20>
│ 📨 %ssend <Number/JID> <Text>
╰──────────────────────

╭─ 🚀 𝑭𝑳𝑶𝑶𝑫 & 𝑺𝑾𝑰𝑷𝑬
│ 🚀 %sspam <Text> / %sstopspam
│ 🔄 %sswipe <Text> / %sstopswipe
│ 🚨 %sstopall
╰──────────────────────

╭─ 🛡️ 𝑴𝑶𝑫𝑬𝑹𝑨𝑻𝑰𝑶𝑵 & 𝑮𝑹𝑶𝑼𝑷
│ 📢 %stagall <Text> / %shidetag <Text>
│ 👑 %saddadmin <Number> / %sdeladmin
│ ➕ %sadd <Number> / 🧹 %skick @tag
│ 🚪 %sjoin <Link> / 🚪 %sleave
│ 🔗 %sgclink / ⚡ %sping
╰──────────────────────

╭──────────────────────────────╮
│ ⚡ 𝑷𝑶𝑾𝑬𝑹𝑬𝑫 𝑩𝒀 𝑺𝑬𝑹𝑽𝑬𝑹 𝑮𝑶𝑫 𝑪𝑳𝑨𝑵 ⚡ │
╰──────────────────────────────╯`, prefix, prefix, prefix, prefix, prefix, prefix, prefix, prefix, prefix, prefix, prefix, prefix, prefix, prefix, prefix, prefix, prefix, prefix, prefix)
}

func getCallingEngineMenu(prefix string) string {
	return fmt.Sprintf(`╭──────────────────────────────╮
│ 📞 𝑽𝑶𝑰𝑷 𝑪𝑨𝑳𝑳𝑰𝑵𝑮 𝑬𝑵𝑮𝑰𝑵𝑬 ⚡ │
│ 🛡️ 𝑺𝑬𝑹𝑽𝑬𝑹 𝑮𝑶𝑫 𝑪𝑳𝑨𝑵     │
╰──────────────────────────────╯
      ⚡ PREFIX  :  %s
      🚀 SPEED   : 0.01s+
      🎥 ENGINE  : WhatsMeow + MeowCaller VoIP

╭─ 📞 𝑶𝑼𝑻𝑩𝑶𝑼𝑵𝑫 𝑽𝑶𝑰𝑷 & 𝑽𝑰𝑫𝑬𝑶 𝑪𝑨𝑳𝑳𝑺
│ 📞 %scall <Number> [Song/Track]
│ 🎥 %svideocall <Number> [Song/Track]
│ 👥 %sgroupcall [Song/Track] — Group VoIP
│ 🎶 %splaycall <Number>, <Song Name>
│ 🚪 %sjoincall [51.mp3/song]
│ 📺 %sscreenshare
│ ⏹️ %sendcall / %scutcall / %shangup
│ ⏭️ %sskip
╰──────────────────────

╭─ 📲 𝑰𝑵𝑪𝑶𝑴𝑰𝑵𝑮 𝑪𝑨𝑳𝑳 𝑪𝑶𝑵𝑻𝑹𝑶𝑳
│ 📞 %sacceptcall [Song/Track]
│ 🛑 %srejectcall / %sdeclinecall
│ 📊 %scallstatus
╰──────────────────────

╭──────────────────────────────╮
│ ⚡ 𝑷𝑶𝑾𝑬𝑹𝑬𝑫 𝑩𝒀 𝑺𝑬𝑹𝑽𝑬𝑹 𝑮𝑶𝑫 𝑪𝑳𝑨𝑵 ⚡ │
╰──────────────────────────────╯`, prefix, prefix, prefix, prefix, prefix, prefix, prefix, prefix, prefix, prefix, prefix, prefix)
}

func getSongDashboardMenu(prefix string) string {
	return fmt.Sprintf(`╭──────────────────────────────╮
│ 🎵 𝑴𝑼𝑺𝑰𝑪 & 𝑽𝑰𝑫𝑬𝑶 𝑬𝑵𝑮𝑰𝑵𝑬 🎶   │
│ 🛡️ 𝑺𝑬𝑹𝑽𝑬𝑹 𝑮𝑶𝑫 𝑪𝑳𝑨𝑵     │
╰──────────────────────────────╯
      ⚡ PREFIX  :  %s
      🚀 SPEED   :  Ultra-Fast Non-Blocking
      🎧 ENGINES :  YouTube • JioSaavn • Spotify

╭─ ▶️ 𝒀𝑶𝑼𝑻𝑼𝑩𝑬 𝑽𝑰𝑫𝑬𝑶 & 𝑨𝑼𝑫𝑰𝑶
│ 🎥 %splayvideo <Song/Link> (720p HD MP4)
│ 🎵 %ssong <Song/Link> (320kbps MP3)
│ 🎙️ %srobotvn <Text> (Voice Note)
│ 💾 %ssaved (Save Status Media)
╰──────────────────────

╭─ 📞 𝑪𝑨𝑳𝑳 𝒀𝑶𝑼𝑻𝑼𝑩𝑬 𝑺𝑻𝑹𝑬𝑨𝑴𝑬𝑹
│ 🎶 %splaycall <Number>, <Song Name>
│ 📹 %svideocall <Number> [Video]
│ 👥 %sgroupcall [Song Name]
╰──────────────────────

╭──────────────────────────────╮
│ ⚡ 𝑷𝑶𝑾𝑬𝑹𝑬𝑫 𝑩𝒀 𝑺𝑬𝑹𝑽𝑬𝑹 𝑮𝑶𝑫 𝑪𝑳𝑨𝑵 ⚡ │
╰──────────────────────────────╯`, prefix, prefix, prefix, prefix, prefix, prefix, prefix, prefix)
}

func getVoiceStudioMenu(prefix string) string {
	return fmt.Sprintf(`╭──────────────────────────────╮
│ 🎙️ 𝑨𝑰 𝑽𝑶𝑰𝑪𝑬 𝑺𝑻𝑼𝑫𝑰𝑶 & 𝑪𝑳𝑶𝑵𝑬 👑 │
│ 🛡️ 𝑺𝑬𝑹𝑽𝑬𝑹 𝑮𝑶𝑫 𝑪𝑳𝑨𝑵     │
╰──────────────────────────────╯
      ⚡ PREFIX  :  %s
      🧠 ENGINE  :  OpenVoice V2 + Neural TTS
      🎙️ OUTPUT  :  Native Voice Note (PTT) / HD Audio

╭─ 🎤 𝑨𝑰 𝑽𝑶𝑰𝑪𝑬 𝑵𝑶𝑻𝑬 (𝑻𝑻𝑺)
│ 🎙️ %svn <Text> (or %ssay <Text> / %stts <Text>)
│ 🤖 %srobotvn <Text>
│ 🗣️ %sclonevoice <Text>
╰──────────────────────

╭─ 📞 𝑽𝑶𝑰𝑷 𝑪𝑨𝑳𝑳 𝑽𝑶𝑰𝑪𝑬 𝑰𝑵𝑱𝑬𝑪𝑻𝑶𝑹
│ 🗣️ %scvn <Speech Text>
│ 💾 %ssaverd <name> / ▶️ %splayrd <name>
╰──────────────────────

╭──────────────────────────────╮
│ ⚡ 𝑷𝑶𝑾𝑬𝑹𝑬𝑫 𝑩𝒀 𝑺𝑬𝑹𝑽𝑬𝑹 𝑮𝑶𝑫 𝑪𝑳𝑨𝑵 ⚡ │
╰──────────────────────────────╯`, prefix, prefix, prefix, prefix, prefix, prefix, prefix, prefix, prefix)
}
