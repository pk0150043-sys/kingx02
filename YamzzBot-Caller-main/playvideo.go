package main

import (
	"context"
	"fmt"
	"os"
	"strings"
	"sync"
	"time"

	meowcaller "github.com/purpshell/meowcaller"
	"go.mau.fi/whatsmeow/types/events"
)

// videoSession = satu video call, nempel ke SATU sender (lihat Sender.videoSess).
// `gen` naik tiap sesi baru; `stop`/`closeStop` per-sesi. Aset (accessUnits+audioPath)
// disiapin DULUAN (download+encode) sebelum call dilempar, jadi pas peer angkat video
// langsung siap streaming — gak ada delay.
type videoSession struct {
	mu          sync.Mutex
	sender      *Sender
	active      bool
	target      string
	requester   string // user yang manggil .playvideo — dipake buat validasi tap tombol
	call        *meowcaller.Call
	gen         uint64
	stop        chan struct{}
	closeStop   func()
	accessUnits [][]byte
	audioPath   string
	title       string
	streamOnce  sync.Once
}

func (v *videoSession) isActive() bool {
	v.mu.Lock()
	defer v.mu.Unlock()
	return v.active
}

// endSession clear state sesi (cuma kalau gen cocok) & hapus file audio.
func (v *videoSession) endSession(gen uint64) {
	v.mu.Lock()
	if v.gen != gen {
		v.mu.Unlock()
		return
	}
	p := v.audioPath
	v.active = false
	v.target = ""
	v.call = nil
	v.accessUnits = nil
	v.audioPath = ""
	v.title = ""
	v.mu.Unlock()
	if p != "" {
		os.Remove(p)
	}
	go advanceVideoQueue() // otomatis lanjut ke antrian berikutnya (kalau ada)
}

// mine cek apakah sesi ini (gen) masih yang aktif.
func (v *videoSession) mine(gen uint64) bool {
	v.mu.Lock()
	defer v.mu.Unlock()
	return v.active && v.gen == gen
}

// videoQueueItem = 1 permintaan .playvideo yang nunggu SEMUA sender sibuk.
// Begitu ada sender nganggur (dari mana pun — call biasa atau video kelar),
// antrian ini otomatis dicoba lagi lewat advanceVideoQueue.
type videoQueueItem struct {
	ctx  context.Context
	evt  *events.Message
	args string
}

var (
	videoQueueMu   sync.Mutex
	videoQueueList []videoQueueItem
)

// advanceVideoQueue ambil item paling depan (kalau ada) & coba mulai lagi.
// Kalau semua sender masih sibuk, otomatis balik masuk antrian lagi lewat
// handlePlayVideo (gak ilang, cuma nunggu giliran berikutnya).
func advanceVideoQueue() {
	videoQueueMu.Lock()
	if len(videoQueueList) == 0 {
		videoQueueMu.Unlock()
		return
	}
	next := videoQueueList[0]
	videoQueueList = videoQueueList[1:]
	videoQueueMu.Unlock()
	handlePlayVideo(next.ctx, next.evt, next.args)
}

// handleStopVideo: hangup TOTAL video call in sender
func handleStopVideo(ctx context.Context, evt *events.Message, senderArg string) {
	vs, msg := pool.videoSessionFor(strings.TrimSpace(senderArg))
	videoQueueMu.Lock()
	cleared := len(videoQueueList)
	videoQueueList = nil
	videoQueueMu.Unlock()

	if vs == nil {
		if cleared > 0 {
			sendText(ctx, evt.Info.Chat, fmt.Sprintf("%s Video queue cleared (%d items).", msg, cleared))
		} else {
			sendText(ctx, evt.Info.Chat, msg)
		}
		return
	}

	vs.mu.Lock()
	call := vs.call
	closeStop := vs.closeStop
	gen := vs.gen
	vs.mu.Unlock()

	reactMsg(ctx, evt, "🛑")
	if cleared > 0 {
		sendText(ctx, evt.Info.Chat, fmt.Sprintf("🛑 Video call ended. Video queue cleared (%d items).", cleared))
	} else {
		sendText(ctx, evt.Info.Chat, "🛑 Video call ended.")
	}
	if call != nil {
		_ = call.Hangup()
	} else {
		if closeStop != nil {
			closeStop()
		}
		vs.endSession(gen)
	}
}

// handleSkipVideo: skip current video
func handleSkipVideo(ctx context.Context, evt *events.Message, senderArg string) {
	vs, msg := pool.videoSessionFor(strings.TrimSpace(senderArg))
	if vs == nil {
		sendText(ctx, evt.Info.Chat, msg)
		return
	}

	vs.mu.Lock()
	call := vs.call
	closeStop := vs.closeStop
	gen := vs.gen
	vs.mu.Unlock()

	videoQueueMu.Lock()
	hasNext := len(videoQueueList) > 0
	videoQueueMu.Unlock()

	reactMsg(ctx, evt, "⏭️")
	if hasNext {
		sendText(ctx, evt.Info.Chat, "⏭️ Skipped, advancing to next video in queue...")
	} else {
		sendText(ctx, evt.Info.Chat, "⏭️ Skipped. Queue empty, video call ended.")
	}
	if call != nil {
		_ = call.Hangup()
	} else {
		if closeStop != nil {
			closeStop()
		}
		vs.endSession(gen)
	}
}

func handleVideoQueue(ctx context.Context, evt *events.Message) {
	var b strings.Builder

	anyActive := false
	for _, s := range pool.list() {
		s.mu.Lock()
		vs := s.videoSess
		s.mu.Unlock()
		if vs == nil {
			continue
		}
		vs.mu.Lock()
		active, title, target := vs.active, vs.title, vs.target
		vs.mu.Unlock()
		if active {
			anyActive = true
			fmt.Fprintf(&b, "🎬 *%s*: %s → +%s\n", s.name, title, target)
		}
	}
	if !anyActive {
		fmt.Fprintf(&b, "📭 No active video streaming.\n")
	}
	b.WriteString("\n")

	videoQueueMu.Lock()
	items := append([]videoQueueItem(nil), videoQueueList...)
	videoQueueMu.Unlock()

	if len(items) == 0 {
		fmt.Fprintf(&b, "📜 *Video Queue:* _empty_")
	} else {
		fmt.Fprintf(&b, "📜 *Video Queue:*\n")
		for i, it := range items {
			fmt.Fprintf(&b, "%d. %s\n", i+1, strings.TrimSpace(it.args))
		}
	}
	sendText(ctx, evt.Info.Chat, b.String())
}

func handlePlayVideo(ctx context.Context, evt *events.Message, args string) {
	reactMsg(ctx, evt, "⏳")
	chat := evt.Info.Chat

	if err := checkFFmpeg(); err != nil {
		reactMsg(ctx, evt, "❌")
		sendText(ctx, chat, "❌ "+err.Error())
		return
	}

	target, ytURL, err := resolveTarget(ctx, evt, args)
	if err != nil {
		reactMsg(ctx, evt, "❌")
		sendText(ctx, chat, "❌ "+err.Error())
		return
	}
	cleanTarget := cleanJIDNumber(target)

	snd := pool.acquireFree()
	if snd == nil {
		videoQueueMu.Lock()
		videoQueueList = append(videoQueueList, videoQueueItem{ctx: ctx, evt: evt, args: args})
		pos := len(videoQueueList)
		videoQueueMu.Unlock()
		reactMsg(ctx, evt, "📋")
		sendText(ctx, chat, fmt.Sprintf(
			"📋 All calling nodes busy. Added to video queue (#%d) — will launch as soon as a node is free.",
			pos,
		))
		return
	}
	vs := snd.videoSession()

	stop := make(chan struct{})
	var stopOnce sync.Once
	closeStop := func() { stopOnce.Do(func() { close(stop) }) }

	vs.mu.Lock()
	vs.gen++
	myGen := vs.gen
	vs.active = true
	vs.target = cleanTarget
	vs.requester = senderUser(evt)
	vs.stop = stop
	vs.closeStop = closeStop
	vs.streamOnce = sync.Once{}
	vs.accessUnits = nil
	vs.audioPath = ""
	vs.title = ""
	vs.call = nil
	vs.mu.Unlock()

	sendText(ctx, chat, fmt.Sprintf("⏳ Preparing video via %s (download + stream encode)...", snd.name))
	aus, audioPath, title, err := buildVideoAssets(ytURL)
	if err != nil {
		reactMsg(ctx, evt, "❌")
		sendText(ctx, chat, "❌ Failed to prepare video stream: "+err.Error())
		vs.endSession(myGen)
		return
	}
	if !vs.mine(myGen) {
		os.Remove(audioPath)
		return
	}
	vs.mu.Lock()
	vs.accessUnits = aus
	vs.audioPath = audioPath
	vs.title = title
	vs.mu.Unlock()

	sendText(ctx, chat, fmt.Sprintf(
		"🎬 *%s*\n📞 %s video calling *+%s*...\n📲 Video stream ready.",
		title, snd.name, cleanTarget,
	))

	var call *meowcaller.Call
	for attempt := 1; attempt <= 3; attempt++ {
		callCtx, cancel := context.WithTimeout(context.Background(), 25*time.Second)
		call, err = snd.call.CallWithOptions(callCtx, target, meowcaller.CallOptions{Video: true})
		cancel()
		if err == nil {
			break
		}
		if attempt < 3 {
			time.Sleep(2 * time.Second)
		}
	}
	if err != nil {
		reactMsg(ctx, evt, "❌")
		sendText(ctx, chat, "❌ Failed to call +"+cleanTarget+": "+err.Error())
		vs.endSession(myGen)
		return
	}

	vs.mu.Lock()
	vs.call = call
	vs.mu.Unlock()

	go keepCallAlive(snd.wa, call.ID(), stop)

	connected := make(chan struct{}, 1)
	player := meowcaller.NewPlayer()
	call.Subscribe(player)

	var playAudioLoop func()
	playAudioLoop = func() {
		if !vs.mine(myGen) {
			return
		}
		src, e := meowcaller.MP3File(audioPath)
		if e != nil {
			sendText(ctx, chat, "❌ Failed to load audio stream: "+e.Error())
			return
		}
		player.OnFinish(playAudioLoop)
		player.Play(src)
	}

	call.OnReady(func() {
		select {
		case connected <- struct{}{}:
		default:
		}
		reactMsg(ctx, evt, "✅")
		startVideoStream(vs, call, myGen, stop)
		playAudioLoop()
		sendText(ctx, chat, fmt.Sprintf(
			"✅ *Video Call Connected to +%s*\n▶️ *%s*\n\n⏭️ Skip: *%sskipvideo %s* | 🛑 Stop: *%sstopvideo %s*",
			cleanTarget, title, Prefix, snd.name, Prefix, snd.name,
		))
	})

	call.OnEnd(func(reason string) {
		label := map[string]string{
			"timeout":      "timeout (unanswered)",
			"media_failed": "media connection failed",
			"hangup":       "call hung up",
			"":             "call finished",
		}[reason]
		if label == "" {
			label = reason
		}
		sendText(ctx, chat, fmt.Sprintf("📴 *Video Call Finished* | %s", label))
		reactMsg(ctx, evt, "📴")
		closeStop()
		vs.endSession(myGen)
	})

	go func() {
		select {
		case <-connected:
		case <-stop:
		case <-time.After(90 * time.Second):
			sendText(ctx, chat, fmt.Sprintf("📵 *+%s* did not answer (90s timeout)", cleanTarget))
			_ = call.Hangup()
		}
	}()

	<-stop
}

// buildVideoAssets fetch link (theresav) → download mp4 → encode (h264 + mp3) → pecah
// jadi access unit. Balikin juga title.
func buildVideoAssets(ytURL string) (aus [][]byte, audioPath, title string, err error) {
	// First try local high-performance yt-dlp extraction
	tempVid := fmt.Sprintf("tmp_vstream_%d.mp4", time.Now().UnixMilli())
	res, yerr := DownloadYouTubeMediaGo(ytURL, "video", tempVid)
	var mp4Path string
	if yerr == nil && res != nil && fileExists(res.FilePath) {
		mp4Path = res.FilePath
		title = res.Title
	} else {
		// Fallback to theresav API
		track, ferr := fetchVideoPlay(ytURL)
		if ferr != nil {
			return nil, "", "", fmt.Errorf("video resolve failed: %w", ferr)
		}
		title = track.Title
		mp4Path, err = downloadVideo(track.DownloadURL)
		if err != nil {
			return nil, "", title, fmt.Errorf("download: %w", err)
		}
	}

	h264Path, audioPath, err := extractVideoAssets(mp4Path)
	os.Remove(mp4Path)
	if err != nil {
		return nil, "", title, err
	}
	aus, err = loadAccessUnits(h264Path)
	os.Remove(h264Path)
	if err != nil {
		os.Remove(audioPath)
		return nil, "", title, fmt.Errorf("parse H.264: %w", err)
	}

	// Diagnostic: video (dari jumlah frame) vs audio (ffprobe) durasinya beda gak?
	// Kalau beda >1 detik, itu penyebab audio/video "gak sinkron" pas sama-sama loop
	// independent (video loop by frame count, audio loop by OnFinish real EOF).
	videoDur := float64(len(aus)) / float64(videoFPS)
	if audioDur, perr := probeDuration(audioPath); perr == nil {
		diff := videoDur - audioDur
		if diff < 0 {
			diff = -diff
		}
		fmt.Printf("[playvideo] durasi video=%.1fs (%d frame @%dfps) audio=%.1fs selisih=%.1fs\n",
			videoDur, len(aus), videoFPS, audioDur, diff)
		if diff > 1.0 {
			fmt.Printf("[playvideo] ⚠️ selisih durasi >1s — audio/video bakal keliatan gak sinkron pas loop\n")
		}
	}

	return aus, audioPath, title, nil
}

// startVideoStream mulai loop kirim frame video (sekali doang per sesi, dijaga
// streamOnce). Aset udah siap sebelum call, jadi langsung stream; loop dari IDR
// pertama sampai call/stop berakhir.
func startVideoStream(vs *videoSession, call *meowcaller.Call, gen uint64, stop <-chan struct{}) {
	vs.streamOnce.Do(func() {
		go func() {
			if !vs.mine(gen) {
				return
			}
			vs.mu.Lock()
			aus := vs.accessUnits
			vs.mu.Unlock()
			if len(aus) == 0 {
				return
			}
			fmt.Printf("[playvideo] mulai stream %d frames @%dfps (loop)\n", len(aus), videoFPS)

			frameDur := time.Second / time.Duration(videoFPS)
			ticker := time.NewTicker(frameDur)
			defer ticker.Stop()
			idx := 0
			for {
				select {
				case <-stop:
					return
				case <-ticker.C:
				}
				if idx >= len(aus) {
					idx = 0
				}
				au := aus[idx]
				idx++
				if err := call.SendVideo(au); err != nil {
					fmt.Printf("[playvideo] SendVideo stop: %v\n", err)
					return
				}
			}
		}()
	})
}
