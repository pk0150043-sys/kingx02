package main

import (
	"context"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"

	meowcaller "github.com/purpshell/meowcaller"
	"go.mau.fi/whatsmeow/types/events"
)

// handleGroupCall handles +groupcall / +gcall / +playcallgc / +joincall
func handleGroupCall(ctx context.Context, evt *events.Message, args string, isVideo bool) {
	chat := evt.Info.Chat
	if !evt.Info.IsGroup {
		sendText(ctx, chat, "❌ This command can only be used inside a *WhatsApp Group*.")
		return
	}

	reactMsg(ctx, evt, "⏳")
	title := strings.TrimSpace(args)

	// 1. FIRST: Check if an active call already exists on any sender node.
	// If active, immediately search/download the song and HOT-SWAP it directly into the active call!
	for _, s := range pool.list() {
		s.mu.Lock()
		curSess := s.sess
		s.mu.Unlock()
		if curSess != nil && curSess.active && curSess.player != nil {
			if title == "" {
				sendText(ctx, chat, "ℹ️ *A call is already active!* To change song, send `"+getPrefix()+"groupcall <song name>` or `"+getPrefix()+"cyt <song name>`.")
				return
			}

			sendText(ctx, chat, fmt.Sprintf("🔍 _Searching JioSaavn & YouTube for '%s'..._", title))

			var filePath, trackTitle, trackArtist string
			// Priority 1: JioSaavn
			jTmp := fmt.Sprintf("tmp_gc_swap_jio_%d.mp3", time.Now().UnixMilli())
			if jPath, jName, jArt, jerr := downloadJioSaavnSong(title, jTmp); jerr == nil && jPath != "" && fileExists(jPath) {
				filePath = jPath
				trackTitle = jName
				trackArtist = jArt
			} else {
				// Priority 2: YouTube fallback
				yTmp := fmt.Sprintf("tmp_gc_swap_yt_%d.mp3", time.Now().UnixMilli())
				if res, err := DownloadYouTubeMediaGo(title, "audio", yTmp); err == nil && res != nil && fileExists(res.FilePath) {
					filePath = res.FilePath
					trackTitle = res.Title
					trackArtist = res.Artist
				}
			}

			if filePath == "" {
				reactMsg(ctx, evt, "❌")
				sendText(ctx, chat, fmt.Sprintf("❌ Failed to download audio for '%s'.", title))
				return
			}

			if err := curSess.PlayAudioFile(filePath, true); err != nil {
				reactMsg(ctx, evt, "❌")
				sendText(ctx, chat, fmt.Sprintf("❌ Failed to play audio in active call: %v", err))
				return
			}

			reactMsg(ctx, evt, "🎶")
			sendText(ctx, chat, fmt.Sprintf("🎶 *[LIVE GROUP CALL SONG CHANGED]* ⚡\n▶️ Now Streaming: *%s* (%s)\n🔁 Looping continuously on active call.", trackTitle, trackArtist))
			return
		}
	}

	// 2. NO ACTIVE CALL: Acquire free sender node and initiate new group call
	snd := pool.acquireFree()
	if snd == nil {
		reactMsg(ctx, evt, "❌")
		sendText(ctx, chat, "❌ All calling nodes are currently busy or offline.")
		return
	}

	var filePath string
	var trackTitle, trackArtist string

	if title != "" {
		sendText(ctx, chat, fmt.Sprintf("🔍 _Searching JioSaavn & YouTube for '%s'..._", title))
		// Priority 1: High quality JioSaavn instant audio stream
		jPath, jName, jArt, jerr := downloadJioSaavnSong(title, fmt.Sprintf("tmp_gc_jio_%d.mp3", time.Now().UnixMilli()))
		if jerr == nil && jPath != "" && fileExists(jPath) {
			filePath = jPath
			trackTitle = jName
			trackArtist = jArt
		} else {
			// Priority 2: yt-dlp / YouTube fallback
			res, err := DownloadYouTubeMediaGo(title, "audio", fmt.Sprintf("tmp_gc_%d.mp3", time.Now().UnixMilli()))
			if err == nil && res != nil && fileExists(res.FilePath) {
				filePath = res.FilePath
				trackTitle = res.Title
				trackArtist = res.Artist
			}
		}
	}

	if filePath == "" {
		if fileExists("51.mp3") {
			filePath = "51.mp3"
			trackTitle = "51.mp3 High-Bass Master Loop"
			trackArtist = "Server God Clan"
		} else if fileExists("../51.mp3") {
			filePath = "../51.mp3"
			trackTitle = "51.mp3 High-Bass Master Loop"
			trackArtist = "Server God Clan"
		}
	}

	sendText(ctx, chat, fmt.Sprintf("📞 *%s* starting Group %s in this group...", snd.name, map[bool]string{true: "Video Call 🎥", false: "Voice Call 📞"}[isVideo]))

	callCtx, cancel := context.WithTimeout(context.Background(), 45*time.Second)
	defer cancel()

	call, err := snd.call.GroupCallByIDWithOptions(callCtx, chat.String(), meowcaller.GroupCallOptions{
		Video: isVideo,
	})
	if err != nil {
		reactMsg(ctx, evt, "❌")
		sendText(ctx, chat, fmt.Sprintf("❌ Failed to initiate group call: %v", err))
		if filePath != "" && strings.HasPrefix(filepath.Base(filePath), "tmp_") {
			os.Remove(filePath)
		}
		return
	}

	reactMsg(ctx, evt, "📞")
	shortID := call.ID()
	if len(shortID) > 8 {
		shortID = shortID[:8]
	}

	sess := &callSession{
		sender:    snd,
		active:    true,
		target:    chat.String(),
		shortID:   shortID,
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

		sendText(ctx, chat, fmt.Sprintf("🎉 *Group %s Connected!*\n🤖 %s | 🔖 `%s`\n🔊 Auto-Unmute: *ACTIVE (LIVE)*\n▶️ Stream: *%s* by *%s*", map[bool]string{true: "Video Call", false: "Voice Call"}[isVideo], snd.name, shortID, trackTitle, trackArtist))
		reactMsg(ctx, evt, "🎉")

		if filePath != "" {
			_ = sess.PlayAudioFile(filePath, true)
		}
	})

	call.OnMuteState(func(muted bool) {
		sess.mu.Lock()
		isMan := sess.manualMute
		sess.mu.Unlock()

		if muted && !isMan && IsAutoUnmuteEnabled() {
			sess.Unmute(snd.wa)
			sendText(ctx, chat, fmt.Sprintf("🔊 *[AUTO-UNMUTE]* Group call audio unmuted automatically on (`%s`)!", shortID))
		}
	})

	call.OnEnd(func(reason string) {
		sendText(ctx, chat, fmt.Sprintf("📴 *Group Call Ended* (ID: `%s`)", shortID))
		reactMsg(ctx, evt, "📴")
		sess.mu.Lock()
		curF := sess.curFile
		sess.mu.Unlock()
		if curF != "" && strings.HasPrefix(filepath.Base(curF), "tmp_") {
			os.Remove(curF)
		}
		snd.mu.Lock()
		sess.reset()
		snd.sess = nil
		snd.mu.Unlock()
		sess.stopAll()
	})
}
