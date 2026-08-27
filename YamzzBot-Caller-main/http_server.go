package main

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"os"
	"strings"
	"sync"
	"time"
)

type HTTPServer struct {
	mu         sync.RWMutex
	globalLogs []string
}

var serverState = &HTTPServer{
	globalLogs: []string{},
}

func logGlobal(msg string) {
	serverState.mu.Lock()
	defer serverState.mu.Unlock()
	entry := fmt.Sprintf("[%s] %s", time.Now().Format("3:04:05 PM"), msg)
	fmt.Println(entry)
	serverState.globalLogs = append(serverState.globalLogs, entry)
	if len(serverState.globalLogs) > 100 {
		serverState.globalLogs = serverState.globalLogs[len(serverState.globalLogs)-100:]
	}
}

func startHTTPServer(ctx context.Context, port string) {
	if port == "" {
		port = os.Getenv("WP_PORT")
		if port == "" {
			port = os.Getenv("BAILEYS_PORT")
		}
		if port == "" {
			port = "20824"
		}
	}

	mux := http.NewServeMux()

	// GET /health
	mux.HandleFunc("/health", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string]any{
			"status":  "ok",
			"service": "whatsapp_whatsmeow_meowcaller",
			"uptime":  int(time.Since(startTime).Seconds()),
			"senders": len(pool.list()),
		})
	})

	// GET /sessions/all
	mux.HandleFunc("/sessions/all", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		serverState.mu.RLock()
		logs := append([]string(nil), serverState.globalLogs...)
		serverState.mu.RUnlock()

		sessionsMap := map[string]any{}
		for _, s := range pool.list() {
			num := s.number()
			isOnline := s.connected()
			s.mu.Lock()
			pairingCode := s.pairingCode
			qrCode := s.qrCode
			sOwner := s.owner
			s.mu.Unlock()
			if sOwner == "" {
				sOwner = OwnerJID
			}

			status := "STANDBY"
			if isOnline {
				status = "ONLINE"
			} else if pairingCode != "" {
				status = "PAIRING"
			} else if qrCode != "" {
				status = "AWAITING_SCAN"
			}

			key := s.uid
			if key == "" {
				key = s.name
			}

			sessionsMap[key] = map[string]any{
				"status":          status,
				"isOnline":        isOnline,
				"connectedNumber": num,
				"ownerJid":        sOwner,
				"isWorkerRunning": isOnline,
				"uptime":          int(time.Since(startTime).Seconds()),
				"hasQr":           qrCode != "",
				"hasPairingCode":  pairingCode != "",
				"qr":              qrCode,
				"pairingCode":     pairingCode,
				"inCall":          s.inCall(),
			}
		}

		json.NewEncoder(w).Encode(map[string]any{
			"sessions":   sessionsMap,
			"globalLogs": logs,
		})
	})

	// Unified session handler
	mux.HandleFunc("/session/", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		path := strings.TrimPrefix(r.URL.Path, "/session/")
		parts := strings.Split(path, "/")

		if len(parts) == 1 && parts[0] == "init" && r.Method == http.MethodPost {
			var body struct {
				UID      string `json:"uid"`
				OwnerJID string `json:"owner_jid"`
			}
			json.NewDecoder(r.Body).Decode(&body)
			if body.UID != "" {
				s := pool.findByName(body.UID)
				if s == nil {
					dev := pool.container.NewDevice()
					pool.mu.Lock()
					idx := len(pool.senders)
					s = pool.buildSender(idx, dev)
					s.uid = body.UID
					s.owner = body.OwnerJID
					pool.senders = append(pool.senders, s)
					pool.mu.Unlock()
				} else {
					s.uid = body.UID
					s.owner = body.OwnerJID
				}
			}
			if body.OwnerJID != "" {
				OwnerJID = body.OwnerJID
				clean := strings.Split(strings.Split(body.OwnerJID, "@")[0], ":")[0]
				addSubAdmin(clean)
			}
			logGlobal(fmt.Sprintf("👑 [SESSION ALLOCATE/INIT] Allocated node %s (Owner: %s)", body.UID, body.OwnerJID))
			json.NewEncoder(w).Encode(map[string]any{"success": true, "uid": body.UID})
			return
		}

		if len(parts) < 2 {
			http.NotFound(w, r)
			return
		}

		uid := parts[0]
		action := parts[1]

		switch action {
		case "status":
			s := pool.findByName(uid)
			isOnline := s != nil && s.connected()
			num := ""
			pairingCode := ""
			qrCode := ""
			owner := OwnerJID
			if s != nil {
				num = s.number()
				s.mu.Lock()
				pairingCode = s.pairingCode
				qrCode = s.qrCode
				if s.owner != "" {
					owner = s.owner
				}
				s.mu.Unlock()
			}
			stat := "STANDBY"
			if isOnline {
				stat = "ONLINE"
			} else if pairingCode != "" {
				stat = "PAIRING"
			} else if qrCode != "" {
				stat = "AWAITING_SCAN"
			}
			json.NewEncoder(w).Encode(map[string]any{
				"status":          stat,
				"isOnline":        isOnline,
				"connectedNumber": num,
				"ownerJid":        owner,
				"qr":              qrCode,
				"pairingCode":     pairingCode,
			})

		case "pair":
			var body struct {
				Phone string `json:"phone"`
			}
			json.NewDecoder(r.Body).Decode(&body)
			phone := strings.NewReplacer("+", "", " ", "", "-", "").Replace(body.Phone)
			if phone == "" {
				w.WriteHeader(http.StatusBadRequest)
				json.NewEncoder(w).Encode(map[string]any{"success": false, "message": "phone required"})
				return
			}
			code, sName, err := pool.addSenderForUID(r.Context(), uid, phone)
			if err != nil {
				w.WriteHeader(http.StatusInternalServerError)
				json.NewEncoder(w).Encode(map[string]any{"success": false, "message": err.Error()})
				return
			}
			logGlobal(fmt.Sprintf("🔗 [PAIRING CODE] Generated code %s for %s (%s, node %s)", code, phone, sName, uid))
			json.NewEncoder(w).Encode(map[string]any{
				"success":     true,
				"pairingCode": code,
				"rawCode":     code,
				"phone":       phone,
				"expiresIn":   900,
			})

		case "set_owner":
			var body struct {
				OwnerJID string `json:"owner_jid"`
			}
			json.NewDecoder(r.Body).Decode(&body)
			if body.OwnerJID != "" {
				s := pool.findByName(uid)
				if s != nil {
					s.mu.Lock()
					s.owner = body.OwnerJID
					s.mu.Unlock()
				}
				clean := strings.Split(strings.Split(body.OwnerJID, "@")[0], ":")[0]
				addSubAdminForSender(s, clean)
			}
			json.NewEncoder(w).Encode(map[string]any{"success": true})

		case "set_admin", "add_admin":
			var body struct {
				Admin string `json:"admin"`
				Phone string `json:"phone"`
			}
			json.NewDecoder(r.Body).Decode(&body)
			adm := body.Admin
			if adm == "" {
				adm = body.Phone
			}
			if adm != "" {
				s := pool.findByName(uid)
				clean := strings.NewReplacer("+", "", " ", "", "-", "").Replace(adm)
				clean = strings.Split(strings.Split(clean, "@")[0], ":")[0]
				addSubAdminForSender(s, clean)
			}
			json.NewEncoder(w).Encode(map[string]any{"success": true})

		case "del_admin", "remove_admin":
			var body struct {
				Admin string `json:"admin"`
				Phone string `json:"phone"`
			}
			json.NewDecoder(r.Body).Decode(&body)
			adm := body.Admin
			if adm == "" {
				adm = body.Phone
			}
			if adm != "" {
				s := pool.findByName(uid)
				clean := strings.NewReplacer("+", "", " ", "", "-", "").Replace(adm)
				clean = strings.Split(strings.Split(clean, "@")[0], ":")[0]
				delSubAdminForSender(s, clean)
			}
			json.NewEncoder(w).Encode(map[string]any{"success": true})

		case "admins", "list_admins":
			s := pool.findByName(uid)
			adms := listSubAdminsForSender(s)
			json.NewEncoder(w).Encode(map[string]any{"success": true, "admins": adms})

		case "refresh_qr":
			qr, err := pool.startQRLogin(r.Context(), uid)
			if err != nil {
				json.NewEncoder(w).Encode(map[string]any{"success": false, "message": err.Error()})
				return
			}
			json.NewEncoder(w).Encode(map[string]any{"success": true, "qr": qr})

		case "start_worker", "stop_worker":
			json.NewEncoder(w).Encode(map[string]any{"success": true, "status": "ok"})

		case "disconnect":
			s := pool.findByName(uid)
			if s != nil && s.wa != nil {
				s.wa.Disconnect()
			}
			json.NewEncoder(w).Encode(map[string]any{"success": true})

		case "delete":
			s := pool.findByName(uid)
			if s != nil {
				if s.wa != nil {
					s.wa.Disconnect()
					if s.device != nil {
						_ = s.device.Delete(r.Context())
					}
				}
			}
			_ = pool.removeSender(uid)
			json.NewEncoder(w).Encode(map[string]any{"success": true})

		default:
			http.NotFound(w, r)
		}
	})

	server := &http.Server{
		Addr:    ":" + port,
		Handler: mux,
	}

	go func() {
		logGlobal(fmt.Sprintf("🚀 [REST API SERVER] Listening on http://127.0.0.1:%s", port))
		if err := server.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			fmt.Printf("[HTTP SERVER ERROR]: %v\n", err)
		}
	}()
}

func (p *senderPool) findByName(name string) *Sender {
	p.mu.Lock()
	defer p.mu.Unlock()
	for _, s := range p.senders {
		if strings.EqualFold(s.uid, name) || strings.EqualFold(s.name, name) || strings.EqualFold(s.number(), name) {
			return s
		}
	}
	return nil
}
