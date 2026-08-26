package main

import (
	"context"
	"fmt"
	"os"
	"strings"
	"time"

	meowcaller "github.com/purpshell/meowcaller"
	"go.mau.fi/whatsmeow/types/events"
)

// handleGroupCall handles +groupcall / +gcall / +playcallgc
func handleGroupCall(ctx context.Context, evt *events.Message, args string, isVideo bool) {
	chat := evt.Info.Chat
	if !evt.Info.IsGroup {
		sendText(ctx, chat, "❌ Command ini cuma bisa dipakai di dalam *GRUP* WhatsApp.")
		return
	}

	reactMsg(ctx, evt, "⏳")

	snd := pool.acquireFree()
	if snd == nil {
		reactMsg(ctx, evt, "❌")
		sendText(ctx, chat, "❌ Semua sender lagi sibuk / offline.")
		return
	}

	title := strings.TrimSpace(args)
	var filePath string
	var trackTitle, trackArtist string

	if title != "" {
		sendText(ctx, chat, fmt.Sprintf("🔍 _Searching YouTube & JioSaavn for '%s'..._", title))
		res, err := DownloadYouTubeMediaGo(title, "audio", fmt.Sprintf("tmp_gc_%d.mp3", time.Now().UnixMilli()))
		if err == nil && res != nil {
			filePath = res.FilePath
			trackTitle = res.Title
			trackArtist = res.Artist
		} else {
			// JioSaavn fallback
			jPath, jName, jArt, jerr := downloadJioSaavnSong(title, fmt.Sprintf("tmp_gc_jio_%d.mp3", time.Now().UnixMilli()))
			if jerr == nil && jPath != "" {
				filePath = jPath
				trackTitle = jName
				trackArtist = jArt
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
		if filePath != "" && !strings.Contains(filePath, "51.mp3") {
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
			var playAudioLoop func()
			playAudioLoop = func() {
				sess.mu.Lock()
				isActive := sess.active
				sess.mu.Unlock()
				if !isActive {
					return
				}
				if src, err := meowcaller.MP3File(filePath); err == nil {
					p.OnFinish(playAudioLoop)
					p.Play(src)
				}
			}
			playAudioLoop()
		}
	})

	call.OnEnd(func(reason string) {
		sendText(ctx, chat, fmt.Sprintf("📴 *Group Call Ended* (ID: `%s`)", shortID))
		reactMsg(ctx, evt, "📴")
		if filePath != "" && !strings.Contains(filePath, "51.mp3") {
			os.Remove(filePath)
		}
		snd.mu.Lock()
		sess.reset()
		snd.sess = nil
		snd.mu.Unlock()
		sess.stopAll()
	})
}
