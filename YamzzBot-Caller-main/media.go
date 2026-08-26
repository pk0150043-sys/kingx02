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

	// If title query, resolve video ID/URL first
	if !isURL {
		if vidID := resolveYouTubeVideoID(cleanTarget); vidID != "" {
			target = fmt.Sprintf("https://www.youtube.com/watch?v=%s", vidID)
			isURL = true
		} else {
			target = fmt.Sprintf("ytsearch1:%s", cleanTarget)
		}
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

	runExtractor := func(playerClient string) bool {
		var args []string
		if pyBin == "yt-dlp" {
			args = []string{
				"--no-playlist",
				"--socket-timeout", "30",
				"--no-warnings",
				"--geo-bypass",
				"--user-agent", "Mozilla/5.0 (Android 14; Mobile; rv:128.0) Gecko/128.0 Firefox/128.0",
			}
		} else {
			args = []string{
				"-m", "yt_dlp",
				"--no-playlist",
				"--socket-timeout", "30",
				"--no-warnings",
				"--geo-bypass",
				"--user-agent", "Mozilla/5.0 (Android 14; Mobile; rv:128.0) Gecko/128.0 Firefox/128.0",
			}
		}

		if playerClient != "" {
			args = append(args, "--extractor-args", fmt.Sprintf("youtube:player_client=%s;player_skip=configs,webpage", playerClient))
		}

		if mediaType == "video" {
			args = append(args,
				"-f", "best[height<=720]/bestvideo[height<=720]+bestaudio/best",
				"--merge-output-format", "mp4",
				"--postprocessor-args", "ffmpeg:-c:v libx264 -pix_fmt yuv420p -profile:v main -c:a aac -b:a 128k -ar 44100 -movflags +faststart",
			)
		} else {
			args = append(args,
				"-f", "bestaudio/best",
				"-x", "--audio-format", "mp3",
				"--postprocessor-args", "ffmpeg:-c:a libmp3lame -b:a 192k -ar 44100",
			)
		}

		args = append(args, "-o", outTmpl, target)
		cmd := exec.Command(pyBin, args...)
		_ = cmd.Run()
		return findGeneratedFile(baseNoExt) != ""
	}

	// Attempt 1: JioSaavn direct high-speed download for audio queries
	if mediaType == "audio" && !isURL {
		jioFile, jioTitle, jioArtist, err := downloadJioSaavnSong(cleanTarget, baseNoExt+".mp3")
		if err == nil && jioFile != "" && fileExists(jioFile) {
			fi, _ := os.Stat(jioFile)
			return &MediaDownloadResult{
				FilePath: jioFile,
				Title:    fmt.Sprintf("%s - %s", jioTitle, jioArtist),
				Artist:   jioArtist,
				FileSize: fi.Size(),
			}, nil
		}
	}

	// Attempt 2: yt-dlp android_creator,tv_embedded,ios,android (best for datacenter IPs)
	if runExtractor("android_creator,tv_embedded,ios,android") {
		found := findGeneratedFile(baseNoExt)
		if found != "" {
			fi, _ := os.Stat(found)
			return &MediaDownloadResult{FilePath: found, Title: cleanTarget, FileSize: fi.Size()}, nil
		}
	}

	// Attempt 3: yt-dlp ios,tv_embedded
	if runExtractor("ios,tv_embedded") {
		found := findGeneratedFile(baseNoExt)
		if found != "" {
			fi, _ := os.Stat(found)
			return &MediaDownloadResult{FilePath: found, Title: cleanTarget, FileSize: fi.Size()}, nil
		}
	}

	// Attempt 4: Invidious API fallback for video/audio
	if invFile := downloadInvidiousStream(cleanTarget, mediaType, baseNoExt); invFile != "" {
		fi, _ := os.Stat(invFile)
		return &MediaDownloadResult{FilePath: invFile, Title: cleanTarget, FileSize: fi.Size()}, nil
	}

	return nil, fmt.Errorf("media download failed across all fallback strategies")
}

func resolveYouTubeVideoID(query string) string {
	// Search Invidious or JioSaavn or Piped for video ID
	apiURL := fmt.Sprintf("https://inv.tux.pizza/api/v1/search?q=%s&type=video", url.QueryEscape(query))
	client := &http.Client{Timeout: 6 * time.Second}
	resp, err := client.Get(apiURL)
	if err == nil {
		defer resp.Body.Close()
		var res []struct {
			VideoID string `json:"videoId"`
		}
		if json.NewDecoder(resp.Body).Decode(&res) == nil && len(res) > 0 {
			return res[0].VideoID
		}
	}
	return ""
}

func downloadInvidiousStream(query string, mediaType string, baseNoExt string) string {
	vidID := resolveYouTubeVideoID(query)
	if vidID == "" {
		return ""
	}
	instances := []string{"https://inv.tux.pizza", "https://invidious.nerdvpn.de", "https://invidious.jing.rocks"}
	client := &http.Client{Timeout: 20 * time.Second}

	for _, inst := range instances {
		apiURL := fmt.Sprintf("%s/api/v1/videos/%s", inst, vidID)
		resp, err := client.Get(apiURL)
		if err != nil {
			continue
		}
		var vData struct {
			FormatStreams []struct {
				Resolution string `json:"resolution"`
				Url        string `json:"url"`
			} `json:"formatStreams"`
		}
		if json.NewDecoder(resp.Body).Decode(&vData) == nil && len(vData.FormatStreams) > 0 {
			resp.Body.Close()
			streamURL := vData.FormatStreams[0].Url
			ext := ".mp4"
			if mediaType == "audio" {
				ext = ".mp3"
			}
			outFilePath := baseNoExt + ext
			dlResp, err := client.Get(streamURL)
			if err == nil {
				defer dlResp.Body.Close()
				outF, err := os.Create(outFilePath)
				if err == nil {
					_, _ = io.Copy(outF, dlResp.Body)
					outF.Close()
					if fi, err := os.Stat(outFilePath); err == nil && fi.Size() > 1000 {
						return outFilePath
					}
				}
			}
		} else {
			resp.Body.Close()
		}
	}
	return ""
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
	client := &http.Client{Timeout: 10 * time.Second}
	resp, err := client.Get(apiURL)
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

	if err := json.NewDecoder(resp.Body).Decode(&data); err != nil || !data.Success || len(data.Data.Results) == 0 {
		return "", "", "", fmt.Errorf("song not found")
	}

	res := data.Data.Results[0]
	var audioURL string
	for _, d := range res.DownloadUrl {
		if d.Quality == "320kbps" || d.Quality == "160kbps" {
			audioURL = d.Url
			break
		}
	}
	if audioURL == "" && len(res.DownloadUrl) > 0 {
		audioURL = res.DownloadUrl[len(res.DownloadUrl)-1].Url
	}
	if audioURL == "" {
		return "", "", "", fmt.Errorf("no download url")
	}

	dlResp, err := client.Get(audioURL)
	if err != nil {
		return "", "", "", err
	}
	defer dlResp.Body.Close()

	outF, err := os.Create(outPath)
	if err != nil {
		return "", "", "", err
	}
	defer outF.Close()

	_, err = io.Copy(outF, dlResp.Body)
	if err != nil {
		return "", "", "", err
	}

	var artistName string
	if len(res.Artists.Primary) > 0 {
		artistName = res.Artists.Primary[0].Name
	}

	return outPath, res.Name, artistName, nil
}
