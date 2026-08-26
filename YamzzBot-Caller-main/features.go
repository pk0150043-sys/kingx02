package main

import (
	"bytes"
	"context"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"

	"github.com/google/uuid"
	meowcaller "github.com/purpshell/meowcaller"
	"go.mau.fi/whatsmeow/types/events"
)

// ─── addsender ────────────────────────────────────────────────────────────────

// handleAddSender initializes a new sender and starts pairing. Returns pairing code for:
// WhatsApp → Linked Devices → Link a Device → Link with phone number.
func handleAddSender(ctx context.Context, evt *events.Message, args string) {
	chat := evt.Info.Chat
	phone := strings.NewReplacer(" ", "", "-", "", "+", "").Replace(strings.TrimSpace(args))
	if len(phone) < 8 {
		sendText(ctx, chat, fmt.Sprintf("❌ Format: *%saddsender <PhoneNumber>* (Country code + Phone Number)", Prefix))
		return
	}

	reactMsg(ctx, evt, "⏳")
	code, name, err := pool.addSender(ctx, phone)
	if err != nil {
		reactMsg(ctx, evt, "❌")
		sendText(ctx, chat, "❌ Pairing generation failed: "+err.Error())
		return
	}
	reactMsg(ctx, evt, "✅")
	sendText(ctx, chat, fmt.Sprintf(
		"🔗 *Pairing Code for Node %s* (+%s)\n\n🔑 *Code:* `%s`\n\n"+
			"📱 On your phone:\nWhatsApp → *Linked Devices* → *Link a Device* → "+
			"*Link with phone number* → enter the code above.\n\n"+
			"⏱️ Valid for 15 minutes. Check *%slistsender* to view active senders.",
		name, phone, code, Prefix,
	))
}

// ─── listsender ───────────────────────────────────────────────────────────────

func handleListSender(ctx context.Context, evt *events.Message) {
	senders := pool.list()
	if len(senders) == 0 {
		sendText(ctx, evt.Info.Chat, "📭 No active senders found.")
		return
	}

	var b strings.Builder
	fmt.Fprintf(&b, "🤖 *Active Bot Senders Pool* (%d Online)\n\n", len(senders))
	for _, s := range senders {
		status := "🔴 Offline"
		if s.connected() {
			status = "🟢 Online"
		}
		call := "Standby / Free"
		s.mu.Lock()
		if s.sess != nil && s.sess.active {
			call = "📞 In Call +" + s.sess.target
		} else if s.videoSess != nil && s.videoSess.isActive() {
			call = "🎬 Video Call Active"
		}
		s.mu.Unlock()
		fmt.Fprintf(&b, "• *%s* (+%s)\n  Status: %s | Mode: %s\n", s.name, s.number(), status, call)
	}
	sendText(ctx, evt.Info.Chat, b.String())
}

// ─── prank ────────────────────────────────────────────────────────────────────

// handlePrank: replies to an audio/voice-note + "m!prank sender1". Audio is swapped
// into the call of sender1, replacing the current track, then resuming afterwards.
func handlePrank(ctx context.Context, evt *events.Message, args string) {
	chat := evt.Info.Chat
	fields := strings.Fields(args)
	if len(fields) == 0 {
		sendText(ctx, chat, fmt.Sprintf("❌ Reply to an AUDIO message with *%sprank sender1*", Prefix))
		return
	}
	name := strings.ToLower(fields[0])

	sess, msg := pool.sessionFor(name)
	if sess == nil {
		sendText(ctx, chat, msg)
		return
	}

	ci := evt.Message.GetExtendedTextMessage().GetContextInfo()
	quoted := ci.GetQuotedMessage()
	if quoted == nil {
		sendText(ctx, chat, "❌ You must reply to an audio or voice note.")
		return
	}
	audio := quoted.GetAudioMessage()
	if audio == nil {
		sendText(ctx, chat, "❌ Quoted message is not an audio / voice note.")
		return
	}

	reactMsg(ctx, evt, "⏳")
	raw, err := waClient.Download(ctx, audio)
	if err != nil {
		reactMsg(ctx, evt, "❌")
		sendText(ctx, chat, "❌ Failed to download audio: "+err.Error())
		return
	}

	mp3Path, err := convertToMP3(raw)
	if err != nil {
		reactMsg(ctx, evt, "❌")
		sendText(ctx, chat, "❌ Audio conversion failed: "+err.Error())
		return
	}

	src, err := meowcaller.MP3File(mp3Path)
	if err != nil {
		os.Remove(mp3Path)
		reactMsg(ctx, evt, "❌")
		sendText(ctx, chat, "❌ Failed to load audio track: "+err.Error())
		return
	}

	sess.mu.Lock()
	if sess.player == nil {
		sess.mu.Unlock()
		os.Remove(mp3Path)
		sendText(ctx, chat, "❌ No active audio player connected on this call.")
		return
	}
	sess.pranking = true
	p := sess.player
	orig := sess.prankTitle
	sess.mu.Unlock()

	reactMsg(ctx, evt, "😹")
	sendText(ctx, chat, fmt.Sprintf("😹 *AUDIO INJECTED* into call %s!\n(Track *%s* will resume after finish)", name, orig))
	p.Play(src)
}

// convertToMP3 writes raw audio to temp and converts to mp3 mono 16k via ffmpeg.
func convertToMP3(raw []byte) (string, error) {
	tmpDir := os.TempDir()
	inPath := filepath.Join(tmpDir, "in_"+uuid.New().String()+".ogg")
	outPath := filepath.Join(tmpDir, "out_"+uuid.New().String()+".mp3")

	if err := os.WriteFile(inPath, raw, 0600); err != nil {
		return "", err
	}
	defer os.Remove(inPath)

	cmd := exec.Command("ffmpeg", "-y", "-i", inPath, "-ar", "16000", "-ac", "1", outPath)
	var errBuf bytes.Buffer
	cmd.Stderr = &errBuf
	if err := cmd.Run(); err != nil {
		return "", fmt.Errorf("%v: %s", err, errBuf.String())
	}
	return outPath, nil
}
