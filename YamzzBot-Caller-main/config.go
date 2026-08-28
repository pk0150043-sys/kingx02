package main

import (
	"os"
	"strings"
	"sync"
)

var (
	configMu      sync.RWMutex
	BotName       = "KINGX WhatsApp Bot"
	Prefix        = "-"
	DefaultEmoji  = "👑"
	FeaturesDelay = 5
	Mode          = "adminonly" // "self", "public", "adminonly"

	// System Owner (Master Admin)
	OwnerNumber = "191525812211746"
	OwnerJID    = "191525812211746@lid"

	// Global and Per-bot / per-sender Admin Sets
	SubAdmins   = map[string]bool{}
	BotAdmins   = map[string]map[string]bool{}
	NumberToUID = map[string]string{}

	// Cooldown and Media Config
	PlaycallCooldownSeconds = 0
	TheresavAPIKey          = ""
	TheresavResolution      = "720"
)

func init() {
	if p := os.Getenv("BOT_PREFIX"); p != "" {
		Prefix = p
	}
	if o := os.Getenv("OWNER_NUMBER"); o != "" {
		OwnerNumber = o
		SubAdmins[o] = true
	}
	if ojid := os.Getenv("OWNER_JID"); ojid != "" {
		OwnerJID = ojid
		clean := strings.Split(strings.Split(ojid, "@")[0], ":")[0]
		SubAdmins[clean] = true
	}
	if e := os.Getenv("DEFAULT_EMOJI"); e != "" {
		DefaultEmoji = e
	}
	if k := os.Getenv("THERESAV_APIKEY"); k != "" {
		TheresavAPIKey = k
	}
}

func getPrefix() string {
	configMu.RLock()
	defer configMu.RUnlock()
	return Prefix
}

func setPrefix(p string) {
	configMu.Lock()
	defer configMu.Unlock()
	Prefix = p
}

func getDefaultEmoji() string {
	configMu.RLock()
	defer configMu.RUnlock()
	return DefaultEmoji
}

func setDefaultEmoji(e string) {
	configMu.Lock()
	defer configMu.Unlock()
	DefaultEmoji = e
}

func getFeaturesDelay() int {
	configMu.RLock()
	defer configMu.RUnlock()
	return FeaturesDelay
}

func setFeaturesDelay(d int) {
	configMu.Lock()
	defer configMu.Unlock()
	FeaturesDelay = d
}

// isAuthorized checks global owner authorization
func isAuthorized(sender string) bool {
	return isAuthorizedForSender(nil, sender)
}

// isAuthorizedForSender checks if sender is authorized for this specific bot node.
// 1. Primary Owner & Master numbers always have master access across ALL bots.
// 2. The bot node creator (s.owner) always has full admin access to their bot.
// 3. Sub-admins explicitly added to THIS bot have access.
func isAuthorizedForSender(s *Sender, sender string) bool {
	configMu.RLock()
	defer configMu.RUnlock()

	raw := strings.TrimSpace(sender)
	clean := strings.NewReplacer("+", "", " ", "", "-", "").Replace(raw)
	cleanUser := strings.Split(strings.Split(clean, "@")[0], ":")[0]

	// Master default numbers
	if cleanUser == "919507325677" || cleanUser == "9507325677" || cleanUser == "191525812211746" || raw == "191525812211746@lid" || cleanUser == "918986269256" || cleanUser == "8986269256" {
		return true
	}

	cleanOwner := strings.NewReplacer("+", "", " ", "", "-", "").Replace(OwnerNumber)
	cleanOwner = strings.Split(strings.Split(cleanOwner, "@")[0], ":")[0]

	if cleanUser == cleanOwner || raw == OwnerJID || strings.EqualFold(raw, OwnerJID) {
		return true
	}
	if len(cleanOwner) >= 10 && len(cleanUser) >= 10 && (strings.HasSuffix(cleanUser, cleanOwner) || strings.HasSuffix(cleanOwner, cleanUser)) {
		return true
	}

	// 0. Check if sender is the bot's own self connected WhatsApp number or JID (Authentic Self-Admin)
	if s != nil {
		sNum := s.number()
		if sNum != "" && sNum != "?" {
			cleanSNum := strings.NewReplacer("+", "", " ", "", "-", "").Replace(sNum)
			cleanSNum = strings.Split(strings.Split(cleanSNum, "@")[0], ":")[0]
			if cleanUser == cleanSNum || (len(cleanSNum) >= 10 && len(cleanUser) >= 10 && (strings.HasSuffix(cleanUser, cleanSNum) || strings.HasSuffix(cleanSNum, cleanUser))) {
				return true
			}
		}
		if s.jid != "" && (raw == s.jid || strings.EqualFold(raw, s.jid) || strings.Contains(s.jid, cleanUser)) {
			return true
		}
		if s.wa != nil && s.wa.Store != nil && s.wa.Store.ID != nil {
			selfUser := s.wa.Store.ID.User
			selfJIDStr := s.wa.Store.ID.ToNonAD().String()
			if cleanUser == selfUser || raw == selfJIDStr || (len(selfUser) >= 10 && len(cleanUser) >= 10 && (strings.HasSuffix(cleanUser, selfUser) || strings.HasSuffix(selfUser, cleanUser))) {
				return true
			}
		}
	}
	if pool != nil {
		for _, snd := range pool.list() {
			if snd == nil {
				continue
			}
			sNum := snd.number()
			if sNum != "" && sNum != "?" {
				cleanSNum := strings.NewReplacer("+", "", " ", "", "-", "").Replace(sNum)
				cleanSNum = strings.Split(strings.Split(cleanSNum, "@")[0], ":")[0]
				if cleanUser == cleanSNum || (len(cleanSNum) >= 10 && len(cleanUser) >= 10 && (strings.HasSuffix(cleanUser, cleanSNum) || strings.HasSuffix(cleanSNum, cleanUser))) {
					return true
				}
			}
			if snd.wa != nil && snd.wa.Store != nil && snd.wa.Store.ID != nil {
				selfUser := snd.wa.Store.ID.User
				if cleanUser == selfUser || (len(selfUser) >= 10 && len(cleanUser) >= 10 && (strings.HasSuffix(cleanUser, selfUser) || strings.HasSuffix(selfUser, cleanUser))) {
					return true
				}
			}
		}
	}

	// Check bot-specific owner (the user who connected this bot instance from dashboard)
	if s != nil {
		s.mu.Lock()
		botOwner := s.owner
		botUID := s.uid
		botName := s.name
		botNum := s.number()
		s.mu.Unlock()

		if botOwner != "" {
			cleanBotOwner := strings.NewReplacer("+", "", " ", "", "-", "").Replace(botOwner)
			cleanBotOwner = strings.Split(strings.Split(cleanBotOwner, "@")[0], ":")[0]
			if cleanUser == cleanBotOwner || raw == botOwner || strings.EqualFold(raw, botOwner) {
				return true
			}
			if len(cleanBotOwner) >= 10 && len(cleanUser) >= 10 && (strings.HasSuffix(cleanUser, cleanBotOwner) || strings.HasSuffix(cleanBotOwner, cleanUser)) {
				return true
			}
		}

		// Check per-bot admins
		for _, key := range []string{botUID, botName, botNum} {
			if key != "" {
				if m, exists := BotAdmins[key]; exists {
					if m[cleanUser] || m[raw] || m[clean] {
						return true
					}
					for adm := range m {
						if strings.EqualFold(adm, raw) || strings.EqualFold(adm, cleanUser) {
							return true
						}
						cleanAdm := strings.NewReplacer("+", "", " ", "", "-", "").Replace(adm)
						cleanAdm = strings.Split(strings.Split(cleanAdm, "@")[0], ":")[0]
						if cleanAdm == cleanUser {
							return true
						}
						if len(cleanAdm) >= 10 && len(cleanUser) >= 10 && (strings.HasSuffix(cleanUser, cleanAdm) || strings.HasSuffix(cleanAdm, cleanUser)) {
							return true
						}
					}
				}
			}
		}
	}

	// Global SubAdmins set
	if SubAdmins[cleanUser] || SubAdmins[raw] || SubAdmins[clean] {
		return true
	}

	for adm := range SubAdmins {
		if strings.EqualFold(adm, raw) || strings.EqualFold(adm, cleanUser) {
			return true
		}
		cleanAdm := strings.NewReplacer("+", "", " ", "", "-", "").Replace(adm)
		cleanAdm = strings.Split(strings.Split(cleanAdm, "@")[0], ":")[0]
		if cleanAdm == cleanUser {
			return true
		}
		if len(cleanAdm) >= 10 && len(cleanUser) >= 10 && (strings.HasSuffix(cleanUser, cleanAdm) || strings.HasSuffix(cleanAdm, cleanUser)) {
			return true
		}
	}

	if OwnerJID != "" && strings.Contains(OwnerJID, cleanUser) {
		return true
	}

	return false
}

// isOwner checks if user is primary master owner
func isOwner(sender string) bool {
	return isOwnerForSender(nil, sender)
}

// isOwnerForSender checks if user is owner of this specific bot or global master owner
func isOwnerForSender(s *Sender, sender string) bool {
	configMu.RLock()
	defer configMu.RUnlock()

	raw := strings.TrimSpace(sender)
	clean := strings.NewReplacer("+", "", " ", "", "-", "").Replace(raw)
	cleanUser := strings.Split(strings.Split(clean, "@")[0], ":")[0]

	if cleanUser == "919507325677" || cleanUser == "9507325677" || cleanUser == "191525812211746" || raw == "191525812211746@lid" || cleanUser == "918986269256" || cleanUser == "8986269256" {
		return true
	}

	cleanOwner := strings.NewReplacer("+", "", " ", "", "-", "").Replace(OwnerNumber)
	cleanOwner = strings.Split(strings.Split(cleanOwner, "@")[0], ":")[0]

	if cleanUser == cleanOwner || raw == OwnerJID || strings.EqualFold(raw, OwnerJID) {
		return true
	}
	if len(cleanOwner) >= 10 && len(cleanUser) >= 10 && (strings.HasSuffix(cleanUser, cleanOwner) || strings.HasSuffix(cleanOwner, cleanUser)) {
		return true
	}

	// 0. Check self-admin on connected sender / pool
	if s != nil {
		sNum := s.number()
		if sNum != "" && sNum != "?" {
			cleanSNum := strings.NewReplacer("+", "", " ", "", "-", "").Replace(sNum)
			cleanSNum = strings.Split(strings.Split(cleanSNum, "@")[0], ":")[0]
			if cleanUser == cleanSNum || (len(cleanSNum) >= 10 && len(cleanUser) >= 10 && (strings.HasSuffix(cleanUser, cleanSNum) || strings.HasSuffix(cleanSNum, cleanUser))) {
				return true
			}
		}
		if s.jid != "" && (raw == s.jid || strings.EqualFold(raw, s.jid) || strings.Contains(s.jid, cleanUser)) {
			return true
		}
		if s.wa != nil && s.wa.Store != nil && s.wa.Store.ID != nil {
			selfUser := s.wa.Store.ID.User
			selfJIDStr := s.wa.Store.ID.ToNonAD().String()
			if cleanUser == selfUser || raw == selfJIDStr || (len(selfUser) >= 10 && len(cleanUser) >= 10 && (strings.HasSuffix(cleanUser, selfUser) || strings.HasSuffix(selfUser, cleanUser))) {
				return true
			}
		}
	}
	if pool != nil {
		for _, snd := range pool.list() {
			if snd == nil {
				continue
			}
			sNum := snd.number()
			if sNum != "" && sNum != "?" {
				cleanSNum := strings.NewReplacer("+", "", " ", "", "-", "").Replace(sNum)
				cleanSNum = strings.Split(strings.Split(cleanSNum, "@")[0], ":")[0]
				if cleanUser == cleanSNum || (len(cleanSNum) >= 10 && len(cleanUser) >= 10 && (strings.HasSuffix(cleanUser, cleanSNum) || strings.HasSuffix(cleanSNum, cleanUser))) {
					return true
				}
			}
			if snd.wa != nil && snd.wa.Store != nil && snd.wa.Store.ID != nil {
				selfUser := snd.wa.Store.ID.User
				if cleanUser == selfUser || (len(selfUser) >= 10 && len(cleanUser) >= 10 && (strings.HasSuffix(cleanUser, selfUser) || strings.HasSuffix(selfUser, cleanUser))) {
					return true
				}
			}
		}
	}

	// Check if user is the bot's instance owner
	if s != nil {
		s.mu.Lock()
		botOwner := s.owner
		s.mu.Unlock()

		if botOwner != "" {
			cleanBotOwner := strings.NewReplacer("+", "", " ", "", "-", "").Replace(botOwner)
			cleanBotOwner = strings.Split(strings.Split(cleanBotOwner, "@")[0], ":")[0]
			if cleanUser == cleanBotOwner || raw == botOwner || strings.EqualFold(raw, botOwner) {
				return true
			}
			if len(cleanBotOwner) >= 10 && len(cleanUser) >= 10 && (strings.HasSuffix(cleanUser, cleanBotOwner) || strings.HasSuffix(cleanBotOwner, cleanUser)) {
				return true
			}
		}
	}

	return false
}

func addSubAdmin(sender string) {
	addSubAdminForSender(nil, sender)
}

func addSubAdminForSender(s *Sender, sender string) {
	configMu.Lock()
	defer configMu.Unlock()
	raw := strings.TrimSpace(sender)
	clean := strings.NewReplacer("+", "", " ", "", "-", "").Replace(raw)
	cleanUser := strings.Split(strings.Split(clean, "@")[0], ":")[0]

	if cleanUser != "" {
		SubAdmins[cleanUser] = true
		SubAdmins[cleanUser+"@s.whatsapp.net"] = true
		SubAdmins[cleanUser+"@lid"] = true
	}
	if raw != "" {
		SubAdmins[raw] = true
	}
	if clean != "" {
		SubAdmins[clean] = true
	}

	if s != nil {
		keys := []string{s.uid, s.name, s.number()}
		for _, k := range keys {
			if k != "" && k != "?" {
				if _, exists := BotAdmins[k]; !exists {
					BotAdmins[k] = map[string]bool{}
				}
				if cleanUser != "" {
					BotAdmins[k][cleanUser] = true
					BotAdmins[k][cleanUser+"@s.whatsapp.net"] = true
					BotAdmins[k][cleanUser+"@lid"] = true
				}
				if raw != "" {
					BotAdmins[k][raw] = true
				}
			}
		}
	}
}

func delSubAdmin(sender string) {
	delSubAdminForSender(nil, sender)
}

func delSubAdminForSender(s *Sender, sender string) {
	configMu.Lock()
	defer configMu.Unlock()
	raw := strings.TrimSpace(sender)
	clean := strings.NewReplacer("+", "", " ", "", "-", "").Replace(raw)
	cleanUser := strings.Split(strings.Split(clean, "@")[0], ":")[0]

	if cleanUser != "" {
		delete(SubAdmins, cleanUser)
		delete(SubAdmins, cleanUser+"@s.whatsapp.net")
	}
	delete(SubAdmins, raw)
	delete(SubAdmins, clean)

	if s != nil {
		keys := []string{s.uid, s.name, s.number()}
		for _, k := range keys {
			if k != "" && k != "?" {
				if _, exists := BotAdmins[k]; exists {
					if cleanUser != "" {
						delete(BotAdmins[k], cleanUser)
						delete(BotAdmins[k], cleanUser+"@s.whatsapp.net")
					}
					delete(BotAdmins[k], raw)
					delete(BotAdmins[k], clean)
				}
			}
		}
	}
}

func listSubAdmins() []string {
	return listSubAdminsForSender(nil)
}

func listSubAdminsForSender(s *Sender) []string {
	configMu.RLock()
	defer configMu.RUnlock()
	admSet := map[string]bool{}
	for adm := range SubAdmins {
		admSet[adm] = true
	}
	if s != nil {
		key := s.uid
		if key == "" {
			key = s.name
		}
		if key != "" {
			if m, exists := BotAdmins[key]; exists {
				for adm := range m {
					admSet[adm] = true
				}
			}
		}
		if s.number() != "" && s.number() != "?" {
			if m, exists := BotAdmins[s.number()]; exists {
				for adm := range m {
					admSet[adm] = true
				}
			}
		}
	}

	var list []string
	for adm := range admSet {
		list = append(list, adm)
	}
	return list
}
