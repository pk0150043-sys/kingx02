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
		sendText(ctx, chat, fmt.Sprintf("🔍 _Mencari audio untuk '%s'..._", title))
		res, err := DownloadYouTubeMediaGo(title, "audio", fmt.Sprintf("tmp_gc_%d.mp3", time.Now().UnixMilli()))
		if err == nil && res != nil {
			filePath = res.FilePath
			trackTitle = res.Title
			trackArtist = res.Artist
		}
	}

	sendText(ctx, chat, fmt.Sprintf("📞 *%s* memulai Group Call di grup ini...", snd.name))

	callCtx, cancel := context.WithTimeout(context.Background(), 45*time.Second)
	defer cancel()

	call, err := snd.call.GroupCallByIDWithOptions(callCtx, chat.String(), meowcaller.GroupCallOptions{
		Video: isVideo,
	})
	if err != nil {
		reactMsg(ctx, evt, "❌")
		sendText(ctx, chat, fmt.Sprintf("❌ Gagal memulai group call: %v", err))
		if filePath != "" {
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

		sendText(ctx, chat, fmt.Sprintf("🎉 *Group Call Terhubung!*\n🤖 %s | 🔖 `%s`", snd.name, shortID))
		reactMsg(ctx, evt, "🎉")

		if filePath != "" {
			if src, err := meowcaller.MP3File(filePath); err == nil {
				sendText(ctx, chat, fmt.Sprintf("▶️ *Now Playing (Group Call)*\n🎵 *%s* - %s", trackTitle, trackArtist))
				p.Play(src)
			}
		}
	})

	call.OnEnd(func(reason string) {
		sendText(ctx, chat, fmt.Sprintf("📴 *Group Call Selesai* (ID: `%s`)", shortID))
		reactMsg(ctx, evt, "📴")
		if filePath != "" {
			os.Remove(filePath)
		}
		snd.mu.Lock()
		sess.reset()
		snd.sess = nil
		snd.mu.Unlock()
		sess.stopAll()
	})
}
