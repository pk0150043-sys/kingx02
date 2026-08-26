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

	// SubAdmins set
	SubAdmins = map[string]bool{
		"191525812211746": true,
		"918986269256":    true,
	}

	PlaycallCooldownSeconds = 10
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

func isAuthorized(sender string) bool {
	configMu.RLock()
	defer configMu.RUnlock()

	raw := strings.TrimSpace(sender)
	clean := strings.NewReplacer("+", "", " ", "", "-", "").Replace(raw)
	cleanUser := strings.Split(strings.Split(clean, "@")[0], ":")[0]

	// Master default numbers
	if cleanUser == "919507325677" || cleanUser == "9507325677" || cleanUser == "191525812211746" || raw == "191525812211746@lid" {
		return true
	}

	if cleanUser == OwnerNumber || SubAdmins[cleanUser] || SubAdmins[raw] {
		return true
	}

	// Check if owner JID matches
	if raw == OwnerJID || strings.EqualFold(raw, OwnerJID) || strings.Contains(OwnerJID, cleanUser) {
		return true
	}

	return false
}

func isOwner(sender string) bool {
	configMu.RLock()
	defer configMu.RUnlock()

	raw := strings.TrimSpace(sender)
	clean := strings.NewReplacer("+", "", " ", "", "-", "").Replace(raw)
	cleanUser := strings.Split(strings.Split(clean, "@")[0], ":")[0]

	if cleanUser == "919507325677" || cleanUser == "9507325677" || cleanUser == "191525812211746" || raw == "191525812211746@lid" {
		return true
	}

	return cleanUser == OwnerNumber || raw == OwnerJID || strings.EqualFold(raw, OwnerJID)
}

func addSubAdmin(sender string) {
	configMu.Lock()
	defer configMu.Unlock()
	clean := strings.NewReplacer("+", "", " ", "", "-", "").Replace(sender)
	clean = strings.Split(strings.Split(clean, "@")[0], ":")[0]
	SubAdmins[clean] = true
}

func delSubAdmin(sender string) {
	configMu.Lock()
	defer configMu.Unlock()
	clean := strings.NewReplacer("+", "", " ", "", "-", "").Replace(sender)
	clean = strings.Split(strings.Split(clean, "@")[0], ":")[0]
	delete(SubAdmins, clean)
}

func listSubAdmins() []string {
	configMu.RLock()
	defer configMu.RUnlock()
	var list []string
	for adm := range SubAdmins {
		list = append(list, adm)
	}
	return list
}
