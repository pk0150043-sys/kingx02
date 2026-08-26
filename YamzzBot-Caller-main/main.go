package main

import (
	"context"
	"fmt"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/mdp/qrterminal/v3"
	meowcaller "github.com/purpshell/meowcaller"
	"github.com/rs/zerolog"
	"go.mau.fi/whatsmeow"
	"go.mau.fi/whatsmeow/store"
	"go.mau.fi/whatsmeow/store/sqlstore"
	"go.mau.fi/whatsmeow/types/events"
	waLog "go.mau.fi/whatsmeow/util/log"

	_ "modernc.org/sqlite"
)

var (
	waClient   *whatsmeow.Client
	callClient *meowcaller.Client
	startTime  = time.Now()
)

func main() {
	logger := zerolog.New(zerolog.ConsoleWriter{Out: os.Stdout, TimeFormat: "15:04:05"}).
		Level(zerolog.InfoLevel).
		With().Timestamp().Logger()

	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	ctx = logger.WithContext(ctx)

	// Start HTTP REST API server on port 20825 for 5.py Flask dashboard integration
	port := os.Getenv("WP_PORT")
	if port == "" {
		port = os.Getenv("GO_SERVICE_PORT")
	}
	if port == "" {
		port = "20825"
	}
	startHTTPServer(ctx, port)

	container, err := sqlstore.New(
		ctx, "sqlite",
		"file:wp_sessions.db?_pragma=foreign_keys(1)&_pragma=busy_timeout(5000)",
		waLog.Zerolog(logger).Sub("db"),
	)
	if err != nil {
		logger.Fatal().Err(err).Msg("failed to open session store (wp_sessions.db)")
	}

	pool.container = container
	pool.logger = logger

	// Load all existing devices from database
	devices, err := container.GetAllDevices(ctx)
	if err != nil {
		logger.Fatal().Err(err).Msg("failed to load devices from store")
	}

	pool.initFromDevices(ctx, devices)

	mainS := pool.main()
	if mainS != nil {
		waClient = mainS.wa
		callClient = mainS.call
	}

	// Connect all logged-in sender accounts
	pool.connectAll()

	logGlobal(fmt.Sprintf("👑 [WHATSMEOW GO ENGINE ONLINE] WhatsApp Go Bot Active (%d senders) with MeowCaller VoIP!", len(pool.list())))

	<-ctx.Done()
	for _, s := range pool.list() {
		s.wa.Disconnect()
	}
}

func firstTimeQRLogin(ctx context.Context, logger zerolog.Logger, device *store.Device) {
	cli := whatsmeow.NewClient(device, waLog.Zerolog(logger).Sub("qr"))
	qrChan, _ := cli.GetQRChannel(ctx)
	if err := cli.Connect(); err != nil {
		return
	}
	for evt := range qrChan {
		if evt.Event == "code" {
			fmt.Println("\n========================================")
			fmt.Println(" SCAN QR IN WHATSAPP > LINKED DEVICES ")
			fmt.Println("========================================")
			qrterminal.GenerateHalfBlock(evt.Code, qrterminal.L, os.Stdout)
		} else if evt.Event == "success" {
			break
		}
	}
}

func waitUntilReady(ctx context.Context, client *whatsmeow.Client, timeout time.Duration) error {
	ready := make(chan struct{}, 8)
	id := client.AddEventHandler(func(evt any) {
		if _, ok := evt.(*events.Connected); ok {
			select {
			case ready <- struct{}{}:
			default:
			}
		}
	})
	defer client.RemoveEventHandler(id)

	deadline := time.After(timeout)
	for !(client.IsConnected() && client.IsLoggedIn()) {
		select {
		case <-ready:
		case <-deadline:
			return fmt.Errorf("timed out waiting for connection")
		case <-ctx.Done():
			return ctx.Err()
		}
	}
	return nil
}
