package main

import (
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"time"
)

type MediaDownloadResult struct {
	FilePath string
	Title    string
	Artist   string
	Duration string
	FileSize int64
}

// DownloadYouTubeMediaGo downloads video or audio with bot-bypass extractor args and fallbacks
func DownloadYouTubeMediaGo(queryOrUrl string, mediaType string, outPath string) (*MediaDownloadResult, error) {
	cleanTarget := strings.TrimSpace(queryOrUrl)
	isURL := strings.HasPrefix(cleanTarget, "http://") || strings.HasPrefix(cleanTarget, "https://")
	target := cleanTarget
	if !isURL {
		target = fmt.Sprintf("ytsearch1:%s", cleanTarget)
	}

	baseNoExt := strings.TrimSuffix(outPath, filepath.Ext(outPath))
	outTmpl := baseNoExt + ".%(ext)s"

	// Find python/yt-dlp binary
	pyBin := "python3"
	if _, err := exec.LookPath("python3"); err != nil {
		if _, err2 := exec.LookPath("python"); err2 == nil {
			pyBin = "python"
		} else if _, err3 := exec.LookPath("yt-dlp"); err3 == nil {
			pyBin = "yt-dlp"
		}
	}

	// Strategy 1: Anti-bot bypass extractor args
	var args []string
	if pyBin == "yt-dlp" {
		args = []string{
			"--no-playlist",
			"--socket-timeout", "25",
			"--no-warnings",
			"--geo-bypass",
			"--user-agent", "Mozilla/5.0 (Android 14; Mobile; rv:128.0) Gecko/128.0 Firefox/128.0",
			"--extractor-args", "youtube:player_client=android_creator,tv_embedded,ios,android;player_skip=configs,webpage",
		}
	} else {
		args = []string{
			"-m", "yt_dlp",
			"--no-playlist",
			"--socket-timeout", "25",
			"--no-warnings",
			"--geo-bypass",
			"--user-agent", "Mozilla/5.0 (Android 14; Mobile; rv:128.0) Gecko/128.0 Firefox/128.0",
			"--extractor-args", "youtube:player_client=android_creator,tv_embedded,ios,android;player_skip=configs,webpage",
		}
	}

	if mediaType == "video" {
		args = append(args,
			"-f", "best[height<=720][ext=mp4]/bestvideo[height<=720]+bestaudio/best[height<=720]/best",
			"--merge-output-format", "mp4",
			"--postprocessor-args", "ffmpeg:-c:v libx264 -pix_fmt yuv420p -profile:v main -c:a aac -b:a 128k -ar 44100 -movflags +faststart",
		)
	} else {
		args = append(args,
			"-f", "bestaudio[ext=m4a]/bestaudio/best",
			"-x", "--audio-format", "mp3",
			"--postprocessor-args", "ffmpeg:-c:a libmp3lame -b:a 192k -ar 44100",
		)
	}

	args = append(args, "-o", outTmpl, target)

	cmd := exec.Command(pyBin, args...)
	_ = cmd.Run()

	// Check if file exists
	found := findGeneratedFile(baseNoExt)
	if found != "" {
		fi, _ := os.Stat(found)
		return &MediaDownloadResult{
			FilePath: found,
			Title:    cleanTarget,
			FileSize: fi.Size(),
		}, nil
	}

	// Strategy 2: Fallback to JioSaavn for audio
	if mediaType == "audio" {
		jioFile, jioTitle, jioArtist, err := downloadJioSaavnSong(cleanTarget, baseNoExt+".mp3")
		if err == nil && jioFile != "" {
			fi, _ := os.Stat(jioFile)
			return &MediaDownloadResult{
				FilePath: jioFile,
				Title:    jioTitle,
				Artist:   jioArtist,
				FileSize: fi.Size(),
			}, nil
		}
	}

	return nil, fmt.Errorf("media download failed")
}

func findGeneratedFile(baseNoExt string) string {
	dir := filepath.Dir(baseNoExt)
	base := filepath.Base(baseNoExt)
	entries, err := os.ReadDir(dir)
	if err != nil {
		return ""
	}
	for _, e := range entries {
		if strings.HasPrefix(e.Name(), base) && !strings.HasSuffix(e.Name(), ".part") && !strings.HasSuffix(e.Name(), ".ytdl") {
			full := filepath.Join(dir, e.Name())
			if fi, err := os.Stat(full); err == nil && fi.Size() > 1000 {
				return full
			}
		}
	}
	return ""
}

// downloadJioSaavnSong searches and downloads track from JioSaavn API
func downloadJioSaavnSong(query string, outPath string) (string, string, string, error) {
	apiURL := fmt.Sprintf("https://saavn.dev/api/search/songs?query=%s", url.QueryEscape(query))
	resp, err := http.Get(apiURL)
	if err != nil {
		return "", "", "", err
	}
	defer resp.Body.Close()

	var data struct {
		Success bool `json:"success"`
		Data    struct {
			Results []struct {
				Name    string `json:"name"`
				Artists struct {
					Primary []struct {
						Name string `json:"name"`
					} `json:"primary"`
				} `json:"artists"`
				DownloadUrl []struct {
					Quality string `json:"quality"`
					Url     string `json:"url"`
				} `json:"downloadUrl"`
			} `json:"results"`
		} `json:"data"`
	}

	if err := json.NewDecoder(resp.Body).Decode(&data); err != nil || len(data.Data.Results) == 0 {
		return "", "", "", fmt.Errorf("song not found")
	}

	track := data.Data.Results[0]
	var dlURL string
	for _, d := range track.DownloadUrl {
		if d.Quality == "320kbps" || d.Quality == "160kbps" {
			dlURL = d.Url
			break
		}
	}
	if dlURL == "" && len(track.DownloadUrl) > 0 {
		dlURL = track.DownloadUrl[len(track.DownloadUrl)-1].Url
	}
	if dlURL == "" {
		return "", "", "", fmt.Errorf("no download url")
	}

	dlResp, err := http.Get(dlURL)
	if err != nil {
		return "", "", "", err
	}
	defer dlResp.Body.Close()

	out, err := os.Create(outPath)
	if err != nil {
		return "", "", "", err
	}
	defer out.Close()

	_, err = io.Copy(out, dlResp.Body)
	if err != nil {
		return "", "", "", err
	}

	artist := "JioSaavn Artist"
	if len(track.Artists.Primary) > 0 {
		artist = track.Artists.Primary[0].Name
	}

	return outPath, track.Name, artist, nil
}
