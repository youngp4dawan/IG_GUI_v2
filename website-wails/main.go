package main

import (
	"bufio"
	"context"
	"database/sql"
	"embed"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strings"
	"sync"
	"syscall"
	"time"

	"github.com/wailsapp/wails/v2"
	"github.com/wailsapp/wails/v2/pkg/options"
	"github.com/wailsapp/wails/v2/pkg/options/assetserver"
	"github.com/wailsapp/wails/v2/pkg/options/windows"
	"github.com/wailsapp/wails/v2/pkg/runtime"
	_ "modernc.org/sqlite"
)

//go:embed all:frontend
var assets embed.FS

// ══════════════════════════════════════════════════════════
// DEBUG LOG
// ══════════════════════════════════════════════════════════

var (
	logFilePath string
	logMu       sync.Mutex
)

func getLogPath() string {
	if logFilePath != "" {
		return logFilePath
	}
	exePath, _ := os.Executable()
	logFilePath = filepath.Join(filepath.Dir(exePath), "igdownloader_debug.log")
	return logFilePath
}

func LogDebug(msg string) {
	logMu.Lock()
	defer logMu.Unlock()

	fmt.Println(msg)

	f, err := os.OpenFile(getLogPath(), os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0644)
	if err != nil {
		return
	}
	defer f.Close()

	timestamp := time.Now().Format("15:04:05")
	f.WriteString("[" + timestamp + "] " + msg + "\n")
}

func LogClear() {
	logMu.Lock()
	defer logMu.Unlock()
	os.Remove(getLogPath())
}

// ══════════════════════════════════════════════════════════
// FILE LOADER MIDDLEWARE
// ══════════════════════════════════════════════════════════

var mimeTypes = map[string]string{
	".jpg": "image/jpeg", ".jpeg": "image/jpeg",
	".png": "image/png", ".gif": "image/gif", ".webp": "image/webp",
	".mp4": "video/mp4", ".webm": "video/webm", ".mov": "video/quicktime",
}

func FileLoaderMiddleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if !strings.HasPrefix(r.URL.Path, "/media/") {
			next.ServeHTTP(w, r)
			return
		}

		p := strings.TrimPrefix(r.URL.Path, "/media/")

		if decoded, err := url.PathUnescape(p); err == nil {
			p = decoded
		}

		p = strings.ReplaceAll(p, "/", "\\")

		if strings.HasPrefix(p, "\\") && !strings.HasPrefix(p, "\\\\") {
			p = p[1:]
		}

		file, err := os.Open(p)
		if err != nil {
			LogDebug(fmt.Sprintf("[FileLoader] ❌ Not found: %s (err: %v)", p, err))
			http.Error(w, "File not found", http.StatusNotFound)
			return
		}
		defer file.Close()

		stat, err := file.Stat()
		if err != nil {
			http.Error(w, "Stat error", http.StatusInternalServerError)
			return
		}

		ct := mimeTypes[strings.ToLower(filepath.Ext(p))]
		if ct == "" {
			ct = "application/octet-stream"
		}

		w.Header().Set("Content-Type", ct)
		w.Header().Set("Content-Length", fmt.Sprintf("%d", stat.Size()))
		w.Header().Set("Cache-Control", "max-age=31536000")
		io.Copy(w, file)
	})
}

// ══════════════════════════════════════════════════════════
// TYPES
// ══════════════════════════════════════════════════════════

type Media struct {
	ID        int      `json:"id"`
	Platform  string   `json:"platform"`
	Account   string   `json:"account"`
	Type      string   `json:"type"`
	Filename  string   `json:"filename"`
	Folder    string   `json:"folder"`
	FullPath  string   `json:"full_path"`
	Caption   string   `json:"caption"`
	Timestamp string   `json:"timestamp"`
	Year      string   `json:"year"`
	Tags      []string `json:"tags"`
	Thumbnail string   `json:"thumbnail"`
}

type Stats struct {
	Total  int `json:"total"`
	Images int `json:"images"`
	Videos int `json:"videos"`
	Tags   int `json:"tags"`
}

type FilterResult struct {
	Media []Media `json:"media"`
	Stats Stats   `json:"stats"`
	Total int     `json:"total"`
}

type AccountWithPlatform struct {
	Account  string `json:"account"`
	Platform string `json:"platform"`
}

type TagWithCount struct {
	Name  string `json:"name"`
	Count int    `json:"count"`
}

type ReindexResult struct {
	Success bool   `json:"success"`
	Message string `json:"message"`
	Total   int    `json:"total"`
}

type IndexProgress struct {
	Phase       string  `json:"phase"`
	Current     int     `json:"current"`
	Total       int     `json:"total"`
	Percent     float64 `json:"percent"`
	Elapsed     float64 `json:"elapsed"`
	Estimated   float64 `json:"estimated"`
	Remaining   float64 `json:"remaining"`
	ItemsPerSec float64 `json:"itemsPerSec"`
}

type PreparedStmts struct {
	Media    *sql.Stmt
	Tag      *sql.Stmt
	GetTag   *sql.Stmt
	MediaTag *sql.Stmt
}

type IGPostMeta struct {
	Caption   string
	Hashtags  []string
	Likes     int
	URL       string
	Thumbnail string
}

type TwitterMediaData struct {
	MediaData []struct {
		Filename  string `json:"filename"`
		Folder    string `json:"folder"`
		Year      int    `json:"year"`
		Timestamp string `json:"timestamp"`
		Caption   string `json:"caption"`
		Type      string `json:"type"`
	} `json:"media_data"`
}

type InstagramData struct {
	Posts []struct {
		Shortcode string   `json:"shortcode"`
		Year      string   `json:"year"`
		Type      string   `json:"type"`
		DateUTC   string   `json:"date_utc"`
		Caption   string   `json:"caption"`
		Hashtags  []string `json:"hashtags"`
		Likes     int      `json:"likes"`
		URL       string   `json:"url"`
		Thumbnail string   `json:"thumbnail"`
	} `json:"posts"`
}

type TikTokVideo struct {
	Filename   string   `json:"filename"`
	Folder     string   `json:"folder"`
	Thumbnail  string   `json:"thumbnail"`
	CreateTime string   `json:"create_time"`
	Caption    string   `json:"caption"`
	Tags       []string `json:"tags"`
}

// ══════════════════════════════════════════════════════════
// YOUTUBE QUEUE TYPES
// ══════════════════════════════════════════════════════════

type QueueItem struct {
	ID            int    `json:"id"`
	VideoPath     string `json:"video_path"`
	ThumbnailPath string `json:"thumbnail_path"`
	Platform      string `json:"platform"`
	Account       string `json:"account"`
	Title         string `json:"title"`
	Description   string `json:"description"`
	Tags          string `json:"tags"`
	Privacy       string `json:"privacy"`
	Status        string `json:"status"`
	YouTubeURL    string `json:"youtube_url"`
	Error         string `json:"error"`
	Attempts      int    `json:"attempts"`
	CreatedAt     string `json:"created_at"`
	StartedAt     string `json:"started_at"`
	FinishedAt    string `json:"finished_at"`
}

type QueueStats struct {
	Total     int `json:"total"`
	Pending   int `json:"pending"`
	Uploading int `json:"uploading"`
	Done      int `json:"done"`
	Failed    int `json:"failed"`
}

// ══════════════════════════════════════════════════════════
// IDOL GROUP TYPES
// ══════════════════════════════════════════════════════════

type GroupNode struct {
	ID        int           `json:"id"`
	Name      string        `json:"name"`
	Icon      string        `json:"icon"`
	Color     string        `json:"color"`
	ParentID  *int          `json:"parent_id"`
	SortOrder int           `json:"sort_order"`
	Children  []GroupNode   `json:"children"`
	Accounts  []IdolAccount `json:"accounts"`
}

type IdolAccount struct {
	ID             int    `json:"id"`
	GroupID        int    `json:"group_id"`
	Platform       string `json:"platform"`
	Username       string `json:"username"`
	Enabled        bool   `json:"enabled"`
	LastCheckAt    string `json:"last_check_at"`
	LastDownloadAt string `json:"last_download_at"`
}

type IdolRun struct {
	ID                 int    `json:"id"`
	GroupID            int    `json:"group_id"`
	Status             string `json:"status"`
	TotalAccounts      int    `json:"total_accounts"`
	CheckedAccounts    int    `json:"checked_accounts"`
	NewPostsFound      int    `json:"new_posts_found"`
	NewPostsDownloaded int    `json:"new_posts_downloaded"`
	Error              string `json:"error"`
	StartedAt          string `json:"started_at"`
	FinishedAt         string `json:"finished_at"`
}
type GroupOption struct {
	ID       int    `json:"id"`
	Name     string `json:"name"`
	Icon     string `json:"icon"`
	ParentID *int   `json:"parent_id"`
}

// ══════════════════════════════════════════════════════════
// MANUAL DOWNLOAD CONFIG
// ══════════════════════════════════════════════════════════

type ManualDownloadConfig struct {
	Platform   string   `json:"platform"`
	Usernames  []string `json:"usernames"`
	Quality    string   `json:"quality"`
	Delay      float64  `json:"delay"`
	UseArchive bool     `json:"use_archive"`
	MaxWorkers int      `json:"max_workers"`
}

// ══════════════════════════════════════════════════════════
// PATH CONFIG
// ══════════════════════════════════════════════════════════

type PathConfig struct {
	PythonDownload string
	OldTwitter     string
	OldInstagram   string
	OldTikTok      string
	Facebook       string // ✅ NEW
}

func loadPathsConfig(exeDir string) PathConfig {
	cfg := PathConfig{}
	path := filepath.Join(exeDir, "paths.txt")

	f, err := os.Open(path)
	if err != nil {
		LogDebug("❌ paths.txt tidak ditemukan di: " + path)
		// ⚡ Fallback: coba derive dari exeDir
		return deriveDefaults(cfg, exeDir)
	}
	defer f.Close()

	LogDebug("📄 Loading paths.txt: " + path)
	scanner := bufio.NewScanner(f)
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}
		parts := strings.SplitN(line, "=", 2)
		if len(parts) != 2 {
			continue
		}
		key := strings.TrimSpace(parts[0])
		val := strings.TrimSpace(parts[1])
		val = strings.ReplaceAll(val, "\\", "/")

		switch key {
		case "python_download":
			cfg.PythonDownload = val
		case "old_twitter":
			cfg.OldTwitter = val
		case "old_instagram":
			cfg.OldInstagram = val
		case "old_tiktok":
			cfg.OldTikTok = val
		case "facebook_download":
			cfg.Facebook = val
		}
	}

	// ⚡ AUTO-DERIVE: Kalau facebook_download kosong tapi python_download di-set,
	// coba derive dari {python_download}/facebook
	if cfg.Facebook == "" && cfg.PythonDownload != "" {
		candidate := cfg.PythonDownload + "/facebook"
		if _, err := os.Stat(candidate); err == nil {
			cfg.Facebook = candidate
			LogDebug("   ✅ Facebook auto-derived: " + candidate)
		}
	}

	LogDebug("   python_download = " + cfg.PythonDownload)
	LogDebug("   old_twitter = " + cfg.OldTwitter)
	LogDebug("   old_instagram = " + cfg.OldInstagram)
	LogDebug("   old_tiktok = " + cfg.OldTikTok)
	LogDebug("   facebook_download = " + cfg.Facebook)
	return cfg
}

// deriveDefaults — dipakai kalau paths.txt tidak ada sama sekali
func deriveDefaults(cfg PathConfig, exeDir string) PathConfig {
	// Coba beberapa lokasi standar untuk python_download
	candidates := []string{
		filepath.Join(exeDir, "..", "IG_GUI_v2", "Download"),
		filepath.Join(exeDir, "..", "..", "IG_GUI_v2", "Download"),
		filepath.Join(exeDir, "..", "..", "..", "IG_GUI_v2", "Download"),
		`C:\Users\User\karil\IG_GUI_v2\Download`,
	}
	for _, c := range candidates {
		if _, err := os.Stat(c); err == nil {
			cfg.PythonDownload = c
			fbCandidate := filepath.Join(c, "facebook")
			if _, err := os.Stat(fbCandidate); err == nil {
				cfg.Facebook = fbCandidate
			}
			break
		}
	}
	return cfg
}

func resolvePath(p string) string {
	if p == "" {
		return ""
	}
	if _, err := os.Stat(p); err == nil {
		return p
	}
	return ""
}

func findFolder(candidates ...string) string {
	for _, c := range candidates {
		if c == "" {
			continue
		}
		if _, err := os.Stat(c); err == nil {
			return c
		}
	}
	return ""
}

// ══════════════════════════════════════════════════════════
// APP
// ══════════════════════════════════════════════════════════

type App struct {
	ctx               context.Context
	db                *sql.DB
	translateCache    map[string]string
	translateCacheMu  sync.RWMutex
	lastTranslateTime time.Time
	translateMu       sync.Mutex
	cacheFilePath     string

	ytWorkerCmd *exec.Cmd
	ytWorkerMu  sync.Mutex

	groupWorkerCmd     *exec.Cmd
	groupWorkerMu      sync.Mutex
	groupWorkerRunID   int
	groupWorkerGroupID int

	manualDlCmd *exec.Cmd
	manualDlMu  sync.Mutex

	// ⚡ NEW: mencegah concurrent reindex
	reindexMu sync.Mutex
}

func NewApp() *App {
	return &App{translateCache: make(map[string]string)}
}

func main() {
	app := NewApp()
	err := wails.Run(&options.App{
		Title:     "Media Viewer",
		Width:     1400,
		Height:    900,
		MinWidth:  800,
		MinHeight: 600,
		AssetServer: &assetserver.Options{
			Assets:     assets,
			Middleware: FileLoaderMiddleware,
		},
		BackgroundColour: &options.RGBA{R: 26, G: 26, B: 46, A: 1},
		OnStartup:        app.startup,
		OnShutdown:       app.shutdown,
		Bind:             []interface{}{app},
		Windows: &windows.Options{
			WebviewIsTransparent: false,
			WindowIsTranslucent:  false,
			DisableWindowIcon:    false,
		},
	})
	if err != nil {
		fmt.Println("Error:", err.Error())
	}
}

func (a *App) startup(ctx context.Context) {
	a.ctx = ctx
	a.connectDB()
	a.ensureQueueTable()
	a.migrateAddUniquePath() // ✅ NEW: Migrasi unique constraint

	if r := a.CleanupOrphanGroups(); r["ok"] == true {
		if g, _ := r["groups"].(int64); g > 0 {
			LogDebug(fmt.Sprintf("🧹 Cleaned %d orphan groups saat startup", g))
		}
	}

	a.loadTranslationCache()
}

func (a *App) shutdown(ctx context.Context) {
	a.ytWorkerMu.Lock()
	if a.ytWorkerCmd != nil && a.ytWorkerCmd.Process != nil {
		pid := a.ytWorkerCmd.Process.Pid
		exec.Command("taskkill", "/F", "/T", "/PID", fmt.Sprintf("%d", pid)).Run()
	}
	a.ytWorkerMu.Unlock()

	a.groupWorkerMu.Lock()
	if a.groupWorkerCmd != nil && a.groupWorkerCmd.Process != nil {
		pid := a.groupWorkerCmd.Process.Pid
		exec.Command("taskkill", "/F", "/T", "/PID", fmt.Sprintf("%d", pid)).Run()
	}
	a.groupWorkerMu.Unlock()

	a.manualDlMu.Lock()
	if a.manualDlCmd != nil && a.manualDlCmd.Process != nil {
		pid := a.manualDlCmd.Process.Pid
		exec.Command("taskkill", "/F", "/T", "/PID", fmt.Sprintf("%d", pid)).Run()
	}
	a.manualDlMu.Unlock()

	if a.db != nil {
		a.db.Close()
	}
	a.saveTranslationCache()
}

func (a *App) connectDB() error {
	exePath, _ := os.Executable()
	exeDir := filepath.Dir(exePath)

	dbPaths := []string{
		filepath.Join(exeDir, "media_library.db"),
		filepath.Join(exeDir, "..", "media_library.db"),
		"media_library.db",
		filepath.Join(exeDir, "..", "..", "media_library.db"),
	}
	for _, p := range dbPaths {
		if _, err := os.Stat(p); err == nil {
			if db, err := sql.Open("sqlite", p); err == nil {
				a.db = db
				fmt.Println("Connected to:", p)
				return nil
			}
		}
	}
	return fmt.Errorf("database not found")
}

// migrateAddUniquePath — Senior approach: aman, idempotent, tidak destroy data
func (a *App) migrateAddUniquePath() {
	if a.db == nil {
		return
	}

	// Cek apakah index unique sudah ada
	var count int
	err := a.db.QueryRow(`SELECT COUNT(*) FROM sqlite_master 
		WHERE type='index' AND name='idx_media_fullpath_unique'`).Scan(&count)
	if err == nil && count > 0 {
		return // sudah ada
	}

	LogDebug("🔧 Migration: adding UNIQUE constraint on full_path...")

	// Hapus duplikat dulu (keep yang terkecil id-nya)
	_, err = a.db.Exec(`DELETE FROM media WHERE id NOT IN (
		SELECT MIN(id) FROM media GROUP BY full_path
	)`)
	if err != nil {
		LogDebug("⚠️  Dedup error: " + err.Error())
	}

	// Buat unique index
	_, err = a.db.Exec(`CREATE UNIQUE INDEX IF NOT EXISTS idx_media_fullpath_unique 
		ON media(full_path)`)
	if err != nil {
		LogDebug("⚠️  Unique index error: " + err.Error())
	} else {
		LogDebug("✅ Unique index created")
	}
}

func (a *App) ensureQueueTable() {
	if a.db == nil {
		return
	}
	sqls := []string{
		`CREATE TABLE IF NOT EXISTS youtube_queue (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			video_path TEXT UNIQUE NOT NULL,
			thumbnail_path TEXT,
			platform TEXT,
			account TEXT,
			title TEXT,
			description TEXT,
			tags TEXT,
			privacy TEXT DEFAULT 'public',
			made_for_kids INTEGER DEFAULT 0,
			playlist TEXT,
			status TEXT DEFAULT 'pending',
			youtube_url TEXT,
			error TEXT,
			attempts INTEGER DEFAULT 0,
			created_at TEXT,
			started_at TEXT,
			finished_at TEXT
		)`,
		`CREATE INDEX IF NOT EXISTS idx_youtube_status ON youtube_queue(status)`,
		`CREATE INDEX IF NOT EXISTS idx_youtube_created ON youtube_queue(created_at DESC)`,

		`CREATE TABLE IF NOT EXISTS idol_groups (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			name TEXT NOT NULL,
			parent_id INTEGER,
			icon TEXT DEFAULT '👤',
			color TEXT DEFAULT '#4a9eff',
			sort_order INTEGER DEFAULT 0,
			created_at TEXT,
			FOREIGN KEY (parent_id) REFERENCES idol_groups(id) ON DELETE CASCADE
		)`,
		`CREATE TABLE IF NOT EXISTS idol_accounts (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			group_id INTEGER NOT NULL,
			platform TEXT NOT NULL,
			username TEXT NOT NULL,
			enabled INTEGER DEFAULT 1,
			last_check_at TEXT,
			last_download_at TEXT,
			created_at TEXT,
			UNIQUE(group_id, platform, username),
			FOREIGN KEY (group_id) REFERENCES idol_groups(id) ON DELETE CASCADE
		)`,
		`CREATE TABLE IF NOT EXISTS idol_group_runs (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			group_id INTEGER NOT NULL,
			status TEXT DEFAULT 'running',
			total_accounts INTEGER DEFAULT 0,
			checked_accounts INTEGER DEFAULT 0,
			new_posts_found INTEGER DEFAULT 0,
			new_posts_downloaded INTEGER DEFAULT 0,
			error TEXT,
			started_at TEXT,
			finished_at TEXT,
			FOREIGN KEY (group_id) REFERENCES idol_groups(id) ON DELETE CASCADE
		)`,
		`CREATE TABLE IF NOT EXISTS app_settings (
			key TEXT PRIMARY KEY,
			value TEXT,
			updated_at TEXT
		)`,
		`CREATE INDEX IF NOT EXISTS idx_idol_groups_parent ON idol_groups(parent_id)`,
		`CREATE INDEX IF NOT EXISTS idx_idol_accounts_group ON idol_accounts(group_id)`,
		`CREATE INDEX IF NOT EXISTS idx_idol_runs_group ON idol_group_runs(group_id)`,
	}
	for _, s := range sqls {
		a.db.Exec(s)
	}
}

// ══════════════════════════════════════════════════════════
// QUERIES — MEDIA
// ══════════════════════════════════════════════════════════

func (a *App) GetMedia(platform, mediaType, account, year, month, day, tag, search, sortOrder string, groupID, page, limit int) FilterResult {
	result := FilterResult{Media: []Media{}, Stats: Stats{}}
	if a.db == nil {
		return result
	}

	var conds []string
	var args []interface{}

	if platform != "" && platform != "All" {
		conds = append(conds, "platform = ?")
		args = append(args, platform)
	}
	if mediaType == "Image" {
		conds = append(conds, "type IN ('image','photo')")
	} else if mediaType == "Video" {
		conds = append(conds, "type = 'video'")
	}
	if account != "" && account != "All" {
		if strings.Contains(account, "|") {
			parts := strings.SplitN(account, "|", 2)
			if len(parts) == 2 {
				conds = append(conds, "platform = ? AND account = ?")
				args = append(args, parts[0], parts[1])
			}
		} else {
			conds = append(conds, "account = ?")
			args = append(args, account)
		}
	}
	if year != "" && year != "All" {
		conds = append(conds, "year = ?")
		args = append(args, year)
	}
	if month != "" && month != "All" {
		conds = append(conds, "substr(timestamp,6,2) = ?")
		args = append(args, month)
	}
	if day != "" && day != "All" {
		conds = append(conds, "substr(timestamp,9,2) = ?")
		args = append(args, day)
	}
	if tag != "" {
		tag = strings.TrimPrefix(tag, "#")
		conds = append(conds, `id IN (SELECT mt.media_id FROM media_tags mt
			JOIN tags t ON mt.tag_id=t.id WHERE t.name = ?)`)
		args = append(args, tag)
	}
	if search != "" {
		conds = append(conds, `(caption LIKE ? OR account LIKE ? OR
			id IN (SELECT mt.media_id FROM media_tags mt
				JOIN tags t ON mt.tag_id=t.id WHERE t.name LIKE ?))`)
		p := "%" + search + "%"
		args = append(args, p, p, p)
	}
	if groupID > 0 {
		groupIDs := a.getDescendantGroupIDs(groupID)
		if len(groupIDs) > 0 {
			ph := make([]string, len(groupIDs))
			for i, id := range groupIDs {
				ph[i] = "?"
				args = append(args, id)
			}
			conds = append(conds, fmt.Sprintf(`
				EXISTS (
					SELECT 1 FROM idol_accounts ia
					WHERE ia.group_id IN (%s)
					  AND ia.platform = platform
					  AND ia.username = account
				)`, strings.Join(ph, ",")))
		}
	}
	where := "1=1"
	if len(conds) > 0 {
		where = strings.Join(conds, " AND ")
	}

	a.db.QueryRow(fmt.Sprintf("SELECT COUNT(*) FROM media WHERE %s", where), args...).Scan(&result.Total)

	a.db.QueryRow(fmt.Sprintf(`SELECT COUNT(*),
		SUM(CASE WHEN type IN ('image','photo') THEN 1 ELSE 0 END),
		SUM(CASE WHEN type='video' THEN 1 ELSE 0 END)
		FROM media WHERE %s`, where), args...).Scan(
		&result.Stats.Total, &result.Stats.Images, &result.Stats.Videos)

	orderBy := "timestamp DESC"
	if sortOrder == "oldest" || sortOrder == "Oldest" {
		orderBy = "timestamp ASC"
	}

	q := fmt.Sprintf(`SELECT id,platform,account,type,filename,folder,full_path,
		COALESCE(caption,''),COALESCE(timestamp,''),COALESCE(year,''),COALESCE(thumbnail,'')
		FROM media WHERE %s ORDER BY %s LIMIT ? OFFSET ?`, where, orderBy)

	rows, err := a.db.Query(q, append(args, limit, page*limit)...)
	if err != nil {
		fmt.Println("Query error:", err)
		return result
	}
	defer rows.Close()

	for rows.Next() {
		var m Media
		if err := rows.Scan(&m.ID, &m.Platform, &m.Account, &m.Type, &m.Filename,
			&m.Folder, &m.FullPath, &m.Caption, &m.Timestamp, &m.Year, &m.Thumbnail); err != nil {
			continue
		}
		tagRows, _ := a.db.Query(`SELECT t.name FROM tags t
			JOIN media_tags mt ON t.id=mt.tag_id WHERE mt.media_id = ?`, m.ID)
		if tagRows != nil {
			for tagRows.Next() {
				var n string
				tagRows.Scan(&n)
				m.Tags = append(m.Tags, n)
			}
			tagRows.Close()
		}
		result.Media = append(result.Media, m)
	}
	return result
}

func (a *App) GetAccounts(platform string) []AccountWithPlatform {
	accounts := []AccountWithPlatform{{Account: "All", Platform: ""}}
	if a.db == nil {
		return accounts
	}
	var rows *sql.Rows
	var err error
	if platform != "" && platform != "All" {
		rows, err = a.db.Query("SELECT DISTINCT account,platform FROM media WHERE platform=? ORDER BY account", platform)
	} else {
		rows, err = a.db.Query("SELECT DISTINCT account,platform FROM media ORDER BY platform,account")
	}
	if err != nil {
		return accounts
	}
	defer rows.Close()
	for rows.Next() {
		var acc AccountWithPlatform
		rows.Scan(&acc.Account, &acc.Platform)
		accounts = append(accounts, acc)
	}
	return accounts
}

func (a *App) GetAccountsForPlatform(platform string) []string {
	accounts := []string{}
	if a.db == nil || platform == "" || platform == "All" {
		return accounts
	}
	rows, err := a.db.Query(`
		SELECT DISTINCT account FROM media
		WHERE platform = ? AND account IS NOT NULL AND account != ''
		ORDER BY account`, platform)
	if err != nil {
		return accounts
	}
	defer rows.Close()
	for rows.Next() {
		var acc string
		rows.Scan(&acc)
		if acc != "" {
			accounts = append(accounts, acc)
		}
	}
	return accounts
}

func (a *App) GetYears() []string {
	years := []string{"All"}
	if a.db == nil {
		return years
	}
	rows, err := a.db.Query("SELECT DISTINCT year FROM media WHERE year IS NOT NULL ORDER BY year DESC")
	if err != nil {
		return years
	}
	defer rows.Close()
	for rows.Next() {
		var y string
		rows.Scan(&y)
		if y != "" {
			years = append(years, y)
		}
	}
	return years
}

func (a *App) GetMonths(year string) []string {
	months := []string{"All"}
	if a.db == nil {
		return months
	}
	var rows *sql.Rows
	var err error
	if year != "" && year != "All" {
		rows, err = a.db.Query(`SELECT DISTINCT substr(timestamp,6,2) FROM media
			WHERE year=? AND timestamp IS NOT NULL AND timestamp != ''
			ORDER BY 1 DESC`, year)
	} else {
		rows, err = a.db.Query(`SELECT DISTINCT substr(timestamp,6,2) FROM media
			WHERE timestamp IS NOT NULL AND timestamp != '' ORDER BY 1 DESC`)
	}
	if err != nil {
		return months
	}
	defer rows.Close()
	for rows.Next() {
		var m string
		rows.Scan(&m)
		if m != "" {
			months = append(months, m)
		}
	}
	return months
}

func (a *App) GetDays(year, month string) []string {
	days := []string{"All"}
	if a.db == nil {
		return days
	}
	conds := []string{"timestamp IS NOT NULL", "timestamp != ''"}
	var args []interface{}
	if year != "" && year != "All" {
		conds = append(conds, "year = ?")
		args = append(args, year)
	}
	if month != "" && month != "All" {
		conds = append(conds, "substr(timestamp,6,2) = ?")
		args = append(args, month)
	}
	q := fmt.Sprintf(`SELECT DISTINCT substr(timestamp,9,2) FROM media
		WHERE %s ORDER BY 1 DESC`, strings.Join(conds, " AND "))
	rows, err := a.db.Query(q, args...)
	if err != nil {
		return days
	}
	defer rows.Close()
	for rows.Next() {
		var d string
		rows.Scan(&d)
		if d != "" {
			days = append(days, d)
		}
	}
	return days
}

func (a *App) GetPopularTags(limit int) []TagWithCount {
	tags := []TagWithCount{}
	if a.db == nil {
		return tags
	}
	rows, err := a.db.Query(`SELECT t.name, COUNT(*) as cnt FROM tags t
		JOIN media_tags mt ON t.id=mt.tag_id GROUP BY t.name
		ORDER BY cnt DESC LIMIT ?`, limit)
	if err != nil {
		return tags
	}
	defer rows.Close()
	for rows.Next() {
		var tag TagWithCount
		rows.Scan(&tag.Name, &tag.Count)
		tags = append(tags, tag)
	}
	return tags
}

func (a *App) OpenFile(path string) error {
	path = strings.ReplaceAll(path, "/", "\\")
	if _, err := os.Stat(path); os.IsNotExist(err) {
		return fmt.Errorf("file not found: %s", path)
	}
	cmd := exec.Command("cmd", "/c", "start", "", path)
	cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true}
	return cmd.Start()
}

func (a *App) OpenFolder(path string) error {
	if _, err := os.Stat(path); os.IsNotExist(err) {
		return fmt.Errorf("file not found: %s", path)
	}
	return exec.Command("explorer", "/select,", path).Start()
}

func (a *App) SaveVideoThumbnail(videoPath, base64Data string) string {
	base64Data = strings.TrimPrefix(base64Data, "data:image/jpeg;base64,")
	base64Data = strings.TrimPrefix(base64Data, "data:image/png;base64,")

	imageData, err := base64.StdEncoding.DecodeString(base64Data)
	if err != nil {
		return ""
	}

	videoDir := filepath.Dir(videoPath)
	userDir := filepath.Dir(filepath.Dir(videoDir))
	thumbDir := filepath.Join(userDir, "thumbnails")
	os.MkdirAll(thumbDir, 0755)

	videoName := filepath.Base(videoPath)
	ext := filepath.Ext(videoName)
	thumbName := strings.TrimSuffix(videoName, ext) + "_thumb.jpg"
	thumbPath := filepath.Join(thumbDir, thumbName)

	if err := os.WriteFile(thumbPath, imageData, 0644); err != nil {
		return ""
	}

	if a.db != nil {
		a.db.Exec("UPDATE media SET thumbnail=? WHERE full_path=?", thumbPath, videoPath)
	}
	return thumbPath
}

// ══════════════════════════════════════════════════════════
// YOUTUBE QUEUE
// ══════════════════════════════════════════════════════════

func (a *App) GetYouTubeQueue(statusFilter string) []QueueItem {
	items := []QueueItem{}
	if a.db == nil {
		return items
	}

	where := "1=1"
	args := []interface{}{}
	if statusFilter != "" && statusFilter != "all" {
		where = "status = ?"
		args = append(args, statusFilter)
	}

	rows, err := a.db.Query(`
		SELECT id, COALESCE(video_path,''), COALESCE(thumbnail_path,''),
		       COALESCE(platform,''), COALESCE(account,''),
		       COALESCE(title,''), COALESCE(description,''),
		       COALESCE(tags,''), COALESCE(privacy,'public'),
		       COALESCE(status,'pending'), COALESCE(youtube_url,''),
		       COALESCE(error,''), COALESCE(attempts,0),
		       COALESCE(created_at,''), COALESCE(started_at,''),
		       COALESCE(finished_at,'')
		FROM youtube_queue WHERE `+where+`
		ORDER BY 
			CASE status 
				WHEN 'uploading' THEN 1 
				WHEN 'pending' THEN 2 
				WHEN 'failed' THEN 3 
				WHEN 'done' THEN 4 
				ELSE 5 
			END,
			created_at DESC
		LIMIT 500
	`, args...)
	if err != nil {
		return items
	}
	defer rows.Close()

	for rows.Next() {
		var q QueueItem
		rows.Scan(&q.ID, &q.VideoPath, &q.ThumbnailPath, &q.Platform, &q.Account,
			&q.Title, &q.Description, &q.Tags, &q.Privacy, &q.Status,
			&q.YouTubeURL, &q.Error, &q.Attempts, &q.CreatedAt,
			&q.StartedAt, &q.FinishedAt)
		items = append(items, q)
	}
	return items
}

func (a *App) GetYouTubeQueueStats() QueueStats {
	stats := QueueStats{}
	if a.db == nil {
		return stats
	}
	rows, err := a.db.Query(`SELECT status, COUNT(*) FROM youtube_queue GROUP BY status`)
	if err != nil {
		return stats
	}
	defer rows.Close()
	for rows.Next() {
		var s string
		var c int
		rows.Scan(&s, &c)
		stats.Total += c
		switch s {
		case "pending":
			stats.Pending = c
		case "uploading":
			stats.Uploading = c
		case "done":
			stats.Done = c
		case "failed":
			stats.Failed = c
		}
	}
	return stats
}

func (a *App) AddToYouTubeQueue(videoPaths []string, privacy string) map[string]interface{} {
	result := map[string]interface{}{"added": 0, "skipped": 0, "errors": []string{}}
	if a.db == nil {
		result["errors"] = []string{"DB tidak connect"}
		return result
	}
	if privacy == "" {
		privacy = "public"
	}

	added := 0
	skipped := 0
	errs := []string{}

	for _, path := range videoPaths {
		var platform, account, caption, thumbnail string
		a.db.QueryRow(`
			SELECT platform, account, COALESCE(caption,''), COALESCE(thumbnail,'')
			FROM media WHERE full_path = ?`, path,
		).Scan(&platform, &account, &caption, &thumbnail)

		title := firstLine(caption, 100)
		if title == "" {
			base := filepath.Base(path)
			title = strings.TrimSuffix(base, filepath.Ext(base))
			if len(title) > 100 {
				title = title[:100]
			}
		}

		tags := extractHashtags(caption)
		tagsJSON, _ := json.Marshal(tags)

		res, err := a.db.Exec(`
			INSERT OR IGNORE INTO youtube_queue
			(video_path, thumbnail_path, platform, account,
			 title, description, tags, privacy, status, created_at)
			VALUES (?,?,?,?,?,?,?,?, 'pending', datetime('now'))`,
			path, thumbnail, platform, account,
			title, caption, string(tagsJSON), privacy)

		if err != nil {
			errs = append(errs, err.Error())
			continue
		}
		n, _ := res.RowsAffected()
		if n > 0 {
			added++
		} else {
			skipped++
		}
	}

	result["added"] = added
	result["skipped"] = skipped
	result["errors"] = errs
	return result
}

// ══════════════════════════════════════════════════════════
// APP SETTINGS — Global key-value store
// ══════════════════════════════════════════════════════════

func (a *App) GetYouTubeHashtags() string {
	if a.db == nil {
		return ""
	}
	var val string
	err := a.db.QueryRow(
		"SELECT value FROM app_settings WHERE key='youtube_custom_hashtags'",
	).Scan(&val)
	if err != nil {
		return ""
	}
	return val
}

func (a *App) SetYouTubeHashtags(hashtags string) map[string]interface{} {
	res := map[string]interface{}{"ok": false, "msg": ""}
	if a.db == nil {
		res["msg"] = "DB not connected"
		return res
	}

	// Normalisasi: trim, buang spasi berlebih
	hashtags = strings.TrimSpace(hashtags)
	// Batasi panjang wajar (biar tidak abuse)
	if len(hashtags) > 500 {
		hashtags = hashtags[:500]
	}

	_, err := a.db.Exec(`
		INSERT INTO app_settings (key, value, updated_at)
		VALUES ('youtube_custom_hashtags', ?, datetime('now'))
		ON CONFLICT(key) DO UPDATE SET
			value = excluded.value,
			updated_at = excluded.updated_at
	`, hashtags)

	if err != nil {
		res["msg"] = err.Error()
		return res
	}

	res["ok"] = true
	res["msg"] = "Saved"
	res["value"] = hashtags
	return res
}

func firstLine(s string, maxLen int) string {
	if s == "" {
		return ""
	}
	if i := strings.IndexAny(s, "\n\r"); i >= 0 {
		s = s[:i]
	}
	s = strings.TrimSpace(s)
	if len(s) > maxLen {
		s = s[:maxLen]
	}
	return s
}

func (a *App) UpdateQueueItem(id int, title, desc, tags, privacy string) error {
	if a.db == nil {
		return fmt.Errorf("DB not connected")
	}
	_, err := a.db.Exec(`
		UPDATE youtube_queue
		SET title=?, description=?, tags=?, privacy=?
		WHERE id=?`, title, desc, tags, privacy, id)
	return err
}

func (a *App) RemoveQueueItem(id int) error {
	if a.db == nil {
		return fmt.Errorf("DB not connected")
	}
	_, err := a.db.Exec("DELETE FROM youtube_queue WHERE id=?", id)
	return err
}

func (a *App) ClearYouTubeQueue(onlyDone bool) int {
	if a.db == nil {
		return 0
	}
	var res sql.Result
	var err error
	if onlyDone {
		res, err = a.db.Exec("DELETE FROM youtube_queue WHERE status IN ('done','failed')")
	} else {
		res, err = a.db.Exec("DELETE FROM youtube_queue WHERE status != 'uploading'")
	}
	if err != nil {
		return 0
	}
	n, _ := res.RowsAffected()
	return int(n)
}

func (a *App) RetryFailedQueue() int {
	if a.db == nil {
		return 0
	}
	res, err := a.db.Exec(`
		UPDATE youtube_queue
		SET status='pending', error='', started_at=NULL, finished_at=NULL
		WHERE status='failed'`)
	if err != nil {
		return 0
	}
	n, _ := res.RowsAffected()
	return int(n)
}

func (a *App) StartYouTubeWorker() map[string]interface{} {
	result := map[string]interface{}{"ok": false, "msg": ""}

	a.ytWorkerMu.Lock()
	defer a.ytWorkerMu.Unlock()

	if a.ytWorkerCmd != nil && a.ytWorkerCmd.Process != nil {
		result["msg"] = "Worker sudah jalan"
		return result
	}

	exePath, _ := os.Executable()
	exeDir := filepath.Dir(exePath)
	cfg := loadPathsConfig(exeDir)

	pythonDir := filepath.Dir(cfg.PythonDownload)
	scriptPath := filepath.Join(pythonDir, "youtube_service.py")

	if _, err := os.Stat(scriptPath); err != nil {
		alt := filepath.Join(exeDir, "youtube_service.py")
		if _, err2 := os.Stat(alt); err2 == nil {
			scriptPath = alt
			pythonDir = exeDir
		} else {
			result["msg"] = "youtube_service.py tidak ditemukan di: " + scriptPath
			return result
		}
	}

	cmd := exec.Command("python", scriptPath)
	cmd.Dir = pythonDir

	stdout, err := cmd.StdoutPipe()
	if err != nil {
		result["msg"] = "Pipe error: " + err.Error()
		return result
	}
	cmd.Stderr = cmd.Stdout

	if err := cmd.Start(); err != nil {
		result["msg"] = "Start error: " + err.Error()
		return result
	}

	a.ytWorkerCmd = cmd
	LogDebug("🎬 YouTube worker started (PID: " + fmt.Sprintf("%d", cmd.Process.Pid) + ")")

	go func() {
		scanner := bufio.NewScanner(stdout)
		scanner.Buffer(make([]byte, 64*1024), 1024*1024)
		for scanner.Scan() {
			line := scanner.Text()
			LogDebug("[PY] " + line)
			runtime.EventsEmit(a.ctx, "youtubeWorkerLog", line)
		}
		cmd.Wait()
		a.ytWorkerMu.Lock()
		a.ytWorkerCmd = nil
		a.ytWorkerMu.Unlock()
		runtime.EventsEmit(a.ctx, "youtubeWorkerStopped", true)
		LogDebug("🎬 YouTube worker stopped")
	}()

	result["ok"] = true
	result["msg"] = "Worker started (PID " + fmt.Sprintf("%d", cmd.Process.Pid) + ")"
	return result
}

func (a *App) StopYouTubeWorker() map[string]interface{} {
	result := map[string]interface{}{"ok": false, "msg": ""}

	a.ytWorkerMu.Lock()
	cmd := a.ytWorkerCmd
	a.ytWorkerMu.Unlock()

	if cmd == nil || cmd.Process == nil {
		result["msg"] = "Worker tidak jalan"
		return result
	}

	pid := cmd.Process.Pid
	LogDebug(fmt.Sprintf("🛑 Stopping YouTube worker (PID %d)...", pid))

	exec.Command("taskkill", "/F", "/T", "/PID", fmt.Sprintf("%d", pid)).Run()

	for i := 0; i < 30; i++ {
		time.Sleep(100 * time.Millisecond)
		a.ytWorkerMu.Lock()
		stillRunning := a.ytWorkerCmd != nil
		a.ytWorkerMu.Unlock()
		if !stillRunning {
			break
		}
	}

	a.ytWorkerMu.Lock()
	a.ytWorkerCmd = nil
	a.ytWorkerMu.Unlock()

	cleanupTempCookies()

	if a.db != nil {
		res, _ := a.db.Exec(`
			UPDATE youtube_queue
			SET status='pending',
			    error='reset: worker stopped during upload'
			WHERE status='uploading'`)
		if res != nil {
			n, _ := res.RowsAffected()
			if n > 0 {
				LogDebug(fmt.Sprintf("♻️  Reset %d orphan uploading → pending", n))
			}
		}
	}

	runtime.EventsEmit(a.ctx, "youtubeWorkerStopped", true)

	result["ok"] = true
	result["msg"] = "Worker stopped"
	return result
}

func cleanupTempCookies() {
	tempDir := os.TempDir()
	entries, err := os.ReadDir(tempDir)
	if err != nil {
		return
	}
	count := 0
	for _, e := range entries {
		name := e.Name()
		if strings.HasPrefix(name, "igc_") && strings.HasSuffix(name, ".txt") {
			if err := os.Remove(filepath.Join(tempDir, name)); err == nil {
				count++
			}
		}
	}
	if count > 0 {
		LogDebug(fmt.Sprintf("🧹 Removed %d temp cookie files", count))
	}
}

func (a *App) GetYouTubeWorkerStatus() map[string]interface{} {
	a.ytWorkerMu.Lock()
	defer a.ytWorkerMu.Unlock()

	running := a.ytWorkerCmd != nil && a.ytWorkerCmd.Process != nil
	pid := 0
	if running {
		pid = a.ytWorkerCmd.Process.Pid
	}
	return map[string]interface{}{"running": running, "pid": pid}
}

func (a *App) getDescendantGroupIDs(rootID int) []int {
	ids := []int{rootID}
	if a.db == nil {
		return ids
	}
	stack := []int{rootID}
	for len(stack) > 0 {
		cur := stack[len(stack)-1]
		stack = stack[:len(stack)-1]
		rows, err := a.db.Query("SELECT id FROM idol_groups WHERE parent_id = ?", cur)
		if err != nil {
			continue
		}
		for rows.Next() {
			var id int
			rows.Scan(&id)
			ids = append(ids, id)
			stack = append(stack, id)
		}
		rows.Close()
	}
	return ids
}

func (a *App) GetGroupOptions() []GroupOption {
	opts := []GroupOption{}
	if a.db == nil {
		return opts
	}
	rows, err := a.db.Query(`
		SELECT id, name, COALESCE(icon,'👥'), parent_id
		FROM idol_groups
		ORDER BY sort_order, name
	`)
	if err != nil {
		return opts
	}
	defer rows.Close()
	for rows.Next() {
		var o GroupOption
		var pid sql.NullInt64
		rows.Scan(&o.ID, &o.Name, &o.Icon, &pid)
		if pid.Valid {
			p := int(pid.Int64)
			o.ParentID = &p
		}
		opts = append(opts, o)
	}
	return opts
}

// ══════════════════════════════════════════════════════════
// IDOL GROUPS — CRUD
// ══════════════════════════════════════════════════════════

func (a *App) GetGroupTree() []GroupNode {
	roots := []GroupNode{}
	if a.db == nil {
		return roots
	}

	rows, err := a.db.Query(`
		SELECT id, name, COALESCE(icon,'👤'), COALESCE(color,'#4a9eff'),
		       parent_id, COALESCE(sort_order,0)
		FROM idol_groups
		ORDER BY sort_order, name
	`)
	if err != nil {
		return roots
	}

	groups := map[int]*GroupNode{}
	order := []int{}
	childIDs := map[int][]int{}

	for rows.Next() {
		g := &GroupNode{}
		var pid sql.NullInt64
		rows.Scan(&g.ID, &g.Name, &g.Icon, &g.Color, &pid, &g.SortOrder)
		if pid.Valid {
			p := int(pid.Int64)
			g.ParentID = &p
		}
		g.Children = []GroupNode{}
		g.Accounts = []IdolAccount{}
		groups[g.ID] = g
		order = append(order, g.ID)
	}
	rows.Close()

	accRows, err := a.db.Query(`
		SELECT id, group_id, platform, username, COALESCE(enabled,1),
		       COALESCE(last_check_at,''), COALESCE(last_download_at,'')
		FROM idol_accounts
		ORDER BY platform, username
	`)
	if err == nil {
		for accRows.Next() {
			var acc IdolAccount
			var enabled int
			accRows.Scan(&acc.ID, &acc.GroupID, &acc.Platform, &acc.Username,
				&enabled, &acc.LastCheckAt, &acc.LastDownloadAt)
			acc.Enabled = enabled == 1
			if g, ok := groups[acc.GroupID]; ok {
				g.Accounts = append(g.Accounts, acc)
			}
		}
		accRows.Close()
	}

	for _, id := range order {
		g := groups[id]
		if g.ParentID != nil {
			childIDs[*g.ParentID] = append(childIDs[*g.ParentID], id)
		}
	}

	var buildNode func(id int) GroupNode
	buildNode = func(id int) GroupNode {
		g := groups[id]
		node := GroupNode{
			ID:        g.ID,
			Name:      g.Name,
			Icon:      g.Icon,
			Color:     g.Color,
			ParentID:  g.ParentID,
			SortOrder: g.SortOrder,
			Children:  []GroupNode{},
			Accounts:  g.Accounts,
		}
		for _, childID := range childIDs[id] {
			node.Children = append(node.Children, buildNode(childID))
		}
		return node
	}

	for _, id := range order {
		g := groups[id]
		if g.ParentID == nil {
			roots = append(roots, buildNode(id))
		} else if _, ok := groups[*g.ParentID]; !ok {
			roots = append(roots, buildNode(id))
		}
	}

	return roots
}

func (a *App) CreateGroup(name string, parentID int) map[string]interface{} {
	res := map[string]interface{}{"ok": false, "msg": "", "id": 0}
	if a.db == nil {
		res["msg"] = "DB not connected"
		return res
	}
	name = strings.TrimSpace(name)
	if name == "" {
		res["msg"] = "Nama group tidak boleh kosong"
		return res
	}

	var pid interface{}
	if parentID > 0 {
		pid = parentID
	}

	icon := "👥"
	if parentID > 0 {
		icon = "👤"
	}

	r, err := a.db.Exec(`
		INSERT INTO idol_groups (name, parent_id, icon, sort_order, created_at)
		VALUES (?, ?, ?, 0, datetime('now'))`,
		name, pid, icon)
	if err != nil {
		res["msg"] = err.Error()
		return res
	}
	id, _ := r.LastInsertId()
	res["ok"] = true
	res["id"] = int(id)
	res["msg"] = "Created"
	return res
}

func (a *App) UpdateGroup(id int, name, icon, color string) error {
	if a.db == nil {
		return fmt.Errorf("DB not connected")
	}
	_, err := a.db.Exec(`
		UPDATE idol_groups
		SET name = ?, icon = ?, color = ?
		WHERE id = ?`, name, icon, color, id)
	return err
}

func (a *App) DeleteGroup(id int) error {
	if a.db == nil {
		return fmt.Errorf("DB not connected")
	}

	descendants := a.getDescendantGroupIDs(id)

	LogDebug(fmt.Sprintf("🗑️  Delete group %d + %d descendants: %v",
		id, len(descendants)-1, descendants))

	for _, gid := range descendants {
		a.db.Exec("DELETE FROM idol_accounts WHERE group_id = ?", gid)
	}

	for _, gid := range descendants {
		a.db.Exec("DELETE FROM idol_group_runs WHERE group_id = ?", gid)
	}

	for i := len(descendants) - 1; i >= 0; i-- {
		a.db.Exec("DELETE FROM idol_groups WHERE id = ?", descendants[i])
	}

	LogDebug(fmt.Sprintf("✅ Group %d deleted", id))
	return nil
}

func (a *App) CleanupOrphanGroups() map[string]interface{} {
	res := map[string]interface{}{"ok": false, "groups": 0, "accounts": 0, "runs": 0}

	if a.db == nil {
		res["msg"] = "DB not connected"
		return res
	}

	r1, _ := a.db.Exec(`
		DELETE FROM idol_accounts
		WHERE group_id NOT IN (SELECT id FROM idol_groups)
	`)
	n1 := int64(0)
	if r1 != nil {
		n1, _ = r1.RowsAffected()
	}

	r2, _ := a.db.Exec(`
		DELETE FROM idol_group_runs
		WHERE group_id NOT IN (SELECT id FROM idol_groups)
	`)
	n2 := int64(0)
	if r2 != nil {
		n2, _ = r2.RowsAffected()
	}

	r3, _ := a.db.Exec(`
		DELETE FROM idol_groups
		WHERE parent_id IS NOT NULL
		  AND parent_id NOT IN (SELECT id FROM idol_groups)
	`)
	n3 := int64(0)
	if r3 != nil {
		n3, _ = r3.RowsAffected()
	}

	res["ok"] = true
	res["accounts"] = n1
	res["runs"] = n2
	res["groups"] = n3
	res["msg"] = fmt.Sprintf("Removed %d accounts, %d runs, %d orphan groups",
		n1, n2, n3)

	if n1+n2+n3 > 0 {
		LogDebug(fmt.Sprintf("🧹 Cleanup orphans: %s", res["msg"]))
	}
	return res
}

// ══════════════════════════════════════════════════════════
// IDOL ACCOUNTS — CRUD
// ══════════════════════════════════════════════════════════

func (a *App) AddAccount(groupID int, platform, username string) map[string]interface{} {
	res := map[string]interface{}{"ok": false, "msg": ""}
	if a.db == nil {
		res["msg"] = "DB not connected"
		return res
	}
	username = strings.TrimSpace(strings.TrimPrefix(username, "@"))
	if username == "" {
		res["msg"] = "Username kosong"
		return res
	}
	platform = strings.ToLower(strings.TrimSpace(platform))
	validPlatforms := map[string]bool{
		"instagram": true,
		"tiktok":    true,
		"facebook":  true,
		"twitter":   true,
	}
	if !validPlatforms[platform] {
		res["msg"] = "Platform tidak valid: " + platform
		return res
	}

	_, err := a.db.Exec(`
		INSERT OR IGNORE INTO idol_accounts
		(group_id, platform, username, enabled, created_at)
		VALUES (?, ?, ?, 1, datetime('now'))`,
		groupID, platform, username)
	if err != nil {
		res["msg"] = err.Error()
		return res
	}
	res["ok"] = true
	res["msg"] = "Added"
	return res
}

func (a *App) UpdateAccount(id int, username string, enabled bool) error {
	if a.db == nil {
		return fmt.Errorf("DB not connected")
	}
	username = strings.TrimSpace(strings.TrimPrefix(username, "@"))
	e := 0
	if enabled {
		e = 1
	}
	_, err := a.db.Exec(`
		UPDATE idol_accounts SET username = ?, enabled = ? WHERE id = ?`,
		username, e, id)
	return err
}

func (a *App) RemoveAccount(id int) error {
	if a.db == nil {
		return fmt.Errorf("DB not connected")
	}
	_, err := a.db.Exec("DELETE FROM idol_accounts WHERE id = ?", id)
	return err
}

func (a *App) GetGroupAccounts(groupID int) []IdolAccount {
	items := []IdolAccount{}
	if a.db == nil {
		return items
	}
	rows, err := a.db.Query(`
		SELECT id, group_id, platform, username, COALESCE(enabled,1),
		       COALESCE(last_check_at,''), COALESCE(last_download_at,'')
		FROM idol_accounts
		WHERE group_id = ?
		ORDER BY platform, username`, groupID)
	if err != nil {
		return items
	}
	defer rows.Close()
	for rows.Next() {
		var acc IdolAccount
		var enabled int
		rows.Scan(&acc.ID, &acc.GroupID, &acc.Platform, &acc.Username,
			&enabled, &acc.LastCheckAt, &acc.LastDownloadAt)
		acc.Enabled = enabled == 1
		items = append(items, acc)
	}
	return items
}

func (a *App) GetGroupRuns(groupID int, limit int) []IdolRun {
	runs := []IdolRun{}
	if a.db == nil {
		return runs
	}
	if limit <= 0 {
		limit = 20
	}
	rows, err := a.db.Query(`
		SELECT id, group_id, status,
		       COALESCE(total_accounts,0), COALESCE(checked_accounts,0),
		       COALESCE(new_posts_found,0), COALESCE(new_posts_downloaded,0),
		       COALESCE(error,''), COALESCE(started_at,''), COALESCE(finished_at,'')
		FROM idol_group_runs
		WHERE group_id = ?
		ORDER BY id DESC LIMIT ?`, groupID, limit)
	if err != nil {
		return runs
	}
	defer rows.Close()
	for rows.Next() {
		var r IdolRun
		rows.Scan(&r.ID, &r.GroupID, &r.Status, &r.TotalAccounts,
			&r.CheckedAccounts, &r.NewPostsFound, &r.NewPostsDownloaded,
			&r.Error, &r.StartedAt, &r.FinishedAt)
		runs = append(runs, r)
	}
	return runs
}

// ══════════════════════════════════════════════════════════
// GROUP DOWNLOAD WORKER
// ══════════════════════════════════════════════════════════

func (a *App) StartGroupDownload(groupID int, platforms []string) map[string]interface{} {
	res := map[string]interface{}{"ok": false, "msg": ""}

	a.groupWorkerMu.Lock()
	defer a.groupWorkerMu.Unlock()

	if a.groupWorkerCmd != nil && a.groupWorkerCmd.Process != nil {
		res["msg"] = "Worker sudah jalan"
		return res
	}

	if len(platforms) == 0 {
		res["msg"] = "Pilih minimal 1 platform"
		return res
	}

	exePath, _ := os.Executable()
	exeDir := filepath.Dir(exePath)
	cfg := loadPathsConfig(exeDir)

	pythonDir := filepath.Dir(cfg.PythonDownload)
	scriptPath := filepath.Join(pythonDir, "download_worker.py")

	if _, err := os.Stat(scriptPath); err != nil {
		res["msg"] = "download_worker.py tidak ditemukan di: " + scriptPath
		return res
	}

	cfgMap := map[string]interface{}{
		"group_id":  groupID,
		"platforms": platforms,
		"delay":     1.0,
	}
	cfgJSON, _ := json.Marshal(cfgMap)

	cmd := exec.Command("python", scriptPath, "group", string(cfgJSON))
	cmd.Dir = pythonDir

	stdout, err := cmd.StdoutPipe()
	if err != nil {
		res["msg"] = "Pipe error: " + err.Error()
		return res
	}
	cmd.Stderr = cmd.Stdout

	if err := cmd.Start(); err != nil {
		res["msg"] = "Start error: " + err.Error()
		return res
	}

	a.groupWorkerCmd = cmd
	a.groupWorkerGroupID = groupID

	LogDebug(fmt.Sprintf("👥 Group worker started: group=%d platforms=%v PID=%d",
		groupID, platforms, cmd.Process.Pid))

	go func() {
		scanner := bufio.NewScanner(stdout)
		scanner.Buffer(make([]byte, 64*1024), 1024*1024)
		for scanner.Scan() {
			line := scanner.Text()
			LogDebug("[GRP] " + line)
			runtime.EventsEmit(a.ctx, "groupDownloadLog", line)
		}
		cmd.Wait()
		a.groupWorkerMu.Lock()
		a.groupWorkerCmd = nil
		a.groupWorkerGroupID = 0
		a.groupWorkerMu.Unlock()
		runtime.EventsEmit(a.ctx, "groupDownloadDone", groupID)
		LogDebug("👥 Group worker stopped")
	}()

	res["ok"] = true
	res["msg"] = "Worker started (PID " + fmt.Sprintf("%d", cmd.Process.Pid) + ")"
	return res
}

func (a *App) StopGroupDownload() map[string]interface{} {
	res := map[string]interface{}{"ok": false, "msg": ""}

	a.groupWorkerMu.Lock()
	cmd := a.groupWorkerCmd
	a.groupWorkerMu.Unlock()

	if cmd == nil || cmd.Process == nil {
		res["msg"] = "Worker tidak jalan"
		return res
	}

	pid := cmd.Process.Pid
	LogDebug(fmt.Sprintf("🛑 Stopping group worker (PID %d)", pid))

	exec.Command("taskkill", "/F", "/T", "/PID", fmt.Sprintf("%d", pid)).Run()

	for i := 0; i < 30; i++ {
		time.Sleep(100 * time.Millisecond)
		a.groupWorkerMu.Lock()
		running := a.groupWorkerCmd != nil
		a.groupWorkerMu.Unlock()
		if !running {
			break
		}
	}

	a.groupWorkerMu.Lock()
	a.groupWorkerCmd = nil
	a.groupWorkerGroupID = 0
	a.groupWorkerMu.Unlock()

	runtime.EventsEmit(a.ctx, "groupDownloadDone", 0)

	res["ok"] = true
	res["msg"] = "Worker stopped"
	return res
}

func (a *App) GetGroupDownloadStatus() map[string]interface{} {
	a.groupWorkerMu.Lock()
	defer a.groupWorkerMu.Unlock()

	running := a.groupWorkerCmd != nil && a.groupWorkerCmd.Process != nil
	pid := 0
	if running {
		pid = a.groupWorkerCmd.Process.Pid
	}
	return map[string]interface{}{
		"running":  running,
		"pid":      pid,
		"group_id": a.groupWorkerGroupID,
	}
}

// ══════════════════════════════════════════════════════════
// MANUAL DOWNLOAD WORKER
// ══════════════════════════════════════════════════════════

func (a *App) StartManualDownload(cfg ManualDownloadConfig) map[string]interface{} {
	res := map[string]interface{}{"ok": false, "msg": ""}

	a.manualDlMu.Lock()
	defer a.manualDlMu.Unlock()

	if a.manualDlCmd != nil && a.manualDlCmd.Process != nil {
		res["msg"] = "Worker sudah jalan"
		return res
	}

	if len(cfg.Usernames) == 0 {
		res["msg"] = "Minimal 1 username"
		return res
	}

	platform := strings.ToLower(cfg.Platform)
	validPlatforms := map[string]bool{
		"instagram": true,
		"tiktok":    true,
		"facebook":  true,
		"twitter":   true,
	}
	if !validPlatforms[platform] {
		res["msg"] = "Platform tidak valid: " + platform
		return res
	}

	if cfg.Quality == "" {
		cfg.Quality = "hd"
	}
	if cfg.Delay <= 0 {
		cfg.Delay = 2.0
	}
	if cfg.MaxWorkers <= 0 {
		cfg.MaxWorkers = 1
	}

	cfgMap := map[string]interface{}{
		"platform":    platform,
		"usernames":   cfg.Usernames,
		"quality":     cfg.Quality,
		"delay":       cfg.Delay,
		"use_archive": cfg.UseArchive,
		"max_workers": cfg.MaxWorkers,
	}
	cfgJSON, _ := json.Marshal(cfgMap)

	exePath, _ := os.Executable()
	exeDir := filepath.Dir(exePath)
	pathsCfg := loadPathsConfig(exeDir)

	pythonDir := filepath.Dir(pathsCfg.PythonDownload)
	scriptPath := filepath.Join(pythonDir, "download_worker.py")

	if _, err := os.Stat(scriptPath); err != nil {
		res["msg"] = "download_worker.py tidak ditemukan di: " + scriptPath
		return res
	}

	cmd := exec.Command("python", scriptPath, "manual", string(cfgJSON))
	cmd.Dir = pythonDir

	stdout, err := cmd.StdoutPipe()
	if err != nil {
		res["msg"] = "Pipe error: " + err.Error()
		return res
	}
	cmd.Stderr = cmd.Stdout

	if err := cmd.Start(); err != nil {
		res["msg"] = "Start error: " + err.Error()
		return res
	}

	a.manualDlCmd = cmd
	LogDebug(fmt.Sprintf("📥 Manual download worker started: platform=%s users=%d PID=%d",
		platform, len(cfg.Usernames), cmd.Process.Pid))

	go func() {
		scanner := bufio.NewScanner(stdout)
		scanner.Buffer(make([]byte, 64*1024), 1024*1024)
		for scanner.Scan() {
			line := scanner.Text()
			LogDebug("[DL] " + line)
			runtime.EventsEmit(a.ctx, "manualDownloadLog", line)
		}
		cmd.Wait()
		a.manualDlMu.Lock()
		a.manualDlCmd = nil
		a.manualDlMu.Unlock()
		runtime.EventsEmit(a.ctx, "manualDownloadDone", true)
		LogDebug("📥 Manual download worker stopped")
	}()

	res["ok"] = true
	res["msg"] = "Worker started (PID " + fmt.Sprintf("%d", cmd.Process.Pid) + ")"
	return res
}

func (a *App) StopManualDownload() map[string]interface{} {
	res := map[string]interface{}{"ok": false, "msg": ""}

	a.manualDlMu.Lock()
	cmd := a.manualDlCmd
	a.manualDlMu.Unlock()

	if cmd == nil || cmd.Process == nil {
		res["msg"] = "Worker tidak jalan"
		return res
	}

	pid := cmd.Process.Pid
	LogDebug(fmt.Sprintf("🛑 Stopping manual download worker (PID %d)", pid))

	exec.Command("taskkill", "/F", "/T", "/PID", fmt.Sprintf("%d", pid)).Run()

	for i := 0; i < 30; i++ {
		time.Sleep(100 * time.Millisecond)
		a.manualDlMu.Lock()
		running := a.manualDlCmd != nil
		a.manualDlMu.Unlock()
		if !running {
			break
		}
	}

	a.manualDlMu.Lock()
	a.manualDlCmd = nil
	a.manualDlMu.Unlock()

	runtime.EventsEmit(a.ctx, "manualDownloadDone", false)

	res["ok"] = true
	res["msg"] = "Worker stopped"
	return res
}

func (a *App) GetManualDownloadStatus() map[string]interface{} {
	a.manualDlMu.Lock()
	defer a.manualDlMu.Unlock()

	running := a.manualDlCmd != nil && a.manualDlCmd.Process != nil
	pid := 0
	if running {
		pid = a.manualDlCmd.Process.Pid
	}
	return map[string]interface{}{"running": running, "pid": pid}
}

// ══════════════════════════════════════════════════════════
// TRANSLATION
// ══════════════════════════════════════════════════════════

const (
	TranslateRateLimitMs = 200
	TranslateMaxRetries  = 2
	TranslateCacheFile   = "translation_cache.json"
)

func (a *App) TranslateText(text, targetLang string) string {
	if text == "" {
		return ""
	}

	cacheKey := targetLang + ":" + text
	a.translateCacheMu.RLock()
	if cached, ok := a.translateCache[cacheKey]; ok {
		a.translateCacheMu.RUnlock()
		return cached
	}
	a.translateCacheMu.RUnlock()

	a.translateMu.Lock()
	if elapsed := time.Since(a.lastTranslateTime); elapsed < TranslateRateLimitMs*time.Millisecond {
		time.Sleep(TranslateRateLimitMs*time.Millisecond - elapsed)
	}
	a.lastTranslateTime = time.Now()
	a.translateMu.Unlock()

	var translated string
	for retry := 0; retry <= TranslateMaxRetries; retry++ {
		translated = a.googleTranslateFree(text, targetLang)
		if translated != "" && translated != text {
			break
		}
		if retry < TranslateMaxRetries {
			time.Sleep(500 * time.Millisecond)
		}
	}

	a.translateCacheMu.Lock()
	a.translateCache[cacheKey] = translated
	a.translateCacheMu.Unlock()
	return translated
}

func (a *App) TranslateBatch(texts []string, targetLang string) map[string]string {
	results := make(map[string]string)
	for _, text := range texts {
		if text != "" {
			results[text] = a.TranslateText(text, targetLang)
		}
	}
	return results
}

func (a *App) googleTranslateFree(text, targetLang string) string {
	params := url.Values{}
	params.Add("client", "gtx")
	params.Add("sl", "auto")
	params.Add("tl", targetLang)
	params.Add("dt", "t")
	params.Add("q", text)

	client := &http.Client{Timeout: 10 * time.Second}
	resp, err := client.Get("https://translate.googleapis.com/translate_a/single?" + params.Encode())
	if err != nil {
		return text
	}
	defer resp.Body.Close()
	if resp.StatusCode != 200 {
		return text
	}

	body, _ := io.ReadAll(resp.Body)
	var result []interface{}
	if json.Unmarshal(body, &result) != nil {
		return text
	}

	if len(result) > 0 {
		if outerArr, ok := result[0].([]interface{}); ok {
			var parts []string
			for _, part := range outerArr {
				if partArr, ok := part.([]interface{}); ok && len(partArr) > 0 {
					if s, ok := partArr[0].(string); ok {
						parts = append(parts, s)
					}
				}
			}
			if len(parts) > 0 {
				return strings.Join(parts, "")
			}
		}
	}
	return text
}

func (a *App) loadTranslationCache() {
	exePath, _ := os.Executable()
	a.cacheFilePath = filepath.Join(filepath.Dir(exePath), TranslateCacheFile)

	data, err := os.ReadFile(a.cacheFilePath)
	if err != nil {
		return
	}
	a.translateCacheMu.Lock()
	defer a.translateCacheMu.Unlock()
	if json.Unmarshal(data, &a.translateCache) != nil {
		a.translateCache = make(map[string]string)
	}
	fmt.Printf("Loaded %d cached translations\n", len(a.translateCache))
}

func (a *App) saveTranslationCache() {
	if a.cacheFilePath == "" {
		return
	}
	a.translateCacheMu.RLock()
	data, _ := json.Marshal(a.translateCache)
	a.translateCacheMu.RUnlock()

	if os.WriteFile(a.cacheFilePath, data, 0644) == nil {
		fmt.Printf("Saved %d cached translations\n", len(a.translateCache))
	}
}

func (a *App) ClearTranslationCache() {
	a.translateCacheMu.Lock()
	a.translateCache = make(map[string]string)
	a.translateCacheMu.Unlock()
	if a.cacheFilePath != "" {
		os.Remove(a.cacheFilePath)
	}
}

func (a *App) GetTranslationCacheStats() map[string]interface{} {
	a.translateCacheMu.RLock()
	count := len(a.translateCache)
	a.translateCacheMu.RUnlock()
	return map[string]interface{}{"count": count, "cacheFile": a.cacheFilePath}
}

// ══════════════════════════════════════════════════════════
// REINDEX — FULL
// ══════════════════════════════════════════════════════════

var videoExts = map[string]bool{
	".mp4": true, ".avi": true, ".mov": true, ".wmv": true,
	".flv": true, ".mkv": true, ".webm": true, ".m4v": true,
}
var imageExts = map[string]bool{
	".jpg": true, ".jpeg": true, ".png": true, ".gif": true,
	".bmp": true, ".webp": true,
}

func getMediaType(filename string) string {
	ext := strings.ToLower(filepath.Ext(filename))
	if videoExts[ext] {
		return "video"
	}
	if imageExts[ext] {
		return "photo"
	}
	return "unknown"
}

func extractHashtags(caption string) []string {
	re := regexp.MustCompile(`#([\p{L}\p{N}_]+)`)
	matches := re.FindAllStringSubmatch(caption, -1)
	tags := make([]string, 0, len(matches))
	for _, m := range matches {
		if len(m) > 1 {
			tags = append(tags, m[1])
		}
	}
	return tags
}

func (a *App) resolveAllPaths(exeDir string) map[string][]string {
	LogDebug("")
	LogDebug("═══════════════════════════════════════════")
	LogDebug("  RESOLVE PATHS")
	LogDebug("═══════════════════════════════════════════")
	LogDebug("exeDir: " + exeDir)

	cfg := loadPathsConfig(exeDir)

	pythonDownload := resolvePath(cfg.PythonDownload)
	if cfg.PythonDownload != "" {
		if pythonDownload == "" {
			LogDebug("❌ python_download TIDAK ADA: " + cfg.PythonDownload)
		} else {
			LogDebug("✅ python_download OK: " + pythonDownload)
		}
	}

	if pythonDownload == "" {
		candidates := []string{
			`C:\Users\User\karil\IG_GUI_v2\Download`,
			filepath.Join(exeDir, "..", "..", "IG_GUI_v2", "Download"),
			filepath.Join(exeDir, "..", "..", "..", "IG_GUI_v2", "Download"),
			filepath.Join(exeDir, "..", "..", "..", "..", "IG_GUI_v2", "Download"),
		}
		LogDebug("🔍 Auto-detect Python download...")
		for _, c := range candidates {
			LogDebug("   Cek: " + c)
			if _, err := os.Stat(c); err == nil {
				pythonDownload = c
				LogDebug("   ✅ FOUND: " + c)
				break
			}
		}
	}

	var igPyPath, ttPyPath string
	if pythonDownload != "" {
		igPyPath = filepath.Join(pythonDownload, "instagram")
		ttPyPath = filepath.Join(pythonDownload, "tiktok")

		if _, err := os.Stat(igPyPath); err != nil {
			LogDebug("❌ Folder TIDAK ADA: " + igPyPath)
			igPyPath = ""
		} else {
			LogDebug("✅ IG python: " + igPyPath)
		}

		if _, err := os.Stat(ttPyPath); err != nil {
			LogDebug("❌ Folder TIDAK ADA: " + ttPyPath)
			ttPyPath = ""
		} else {
			LogDebug("✅ TikTok python: " + ttPyPath)
		}
	}

	oldTwitter := resolvePath(cfg.OldTwitter)
	if oldTwitter == "" {
		oldTwitter = findFolder(
			filepath.Join(exeDir, "..", "..", "twitter", "twitter_downloads"),
			filepath.Join(exeDir, "..", "..", "..", "twitter", "twitter_downloads"),
		)
	}
	oldInstagram := resolvePath(cfg.OldInstagram)
	if oldInstagram == "" {
		oldInstagram = findFolder(
			filepath.Join(exeDir, "..", "..", "instagram", "Download"),
			filepath.Join(exeDir, "..", "..", "..", "instagram", "Download"),
		)
	}
	oldTikTok := resolvePath(cfg.OldTikTok)
	if oldTikTok == "" {
		oldTikTok = findFolder(
			filepath.Join(exeDir, "..", "..", "tiktok", "tiktok_downloads"),
			filepath.Join(exeDir, "..", "..", "..", "tiktok", "tiktok_downloads"),
		)
	}

	// ✅ Facebook path resolution
	facebookPath := resolvePath(cfg.Facebook)
	if facebookPath == "" {
		facebookPath = findFolder(
			filepath.Join(exeDir, "..", "..", "facebook", "facebook_downloads"),
			filepath.Join(exeDir, "..", "..", "..", "facebook", "facebook_downloads"),
			filepath.Join(pythonDownload, "facebook"),
			filepath.Join(exeDir, "..", "..", "facebook"),
		)
	}

	LogDebug("")
	LogDebug("📂 Final paths:")
	if oldTwitter != "" {
		LogDebug("   🐦 Twitter:        " + oldTwitter)
	}
	if oldInstagram != "" {
		LogDebug("   📷 IG (old):       " + oldInstagram)
	}
	if oldTikTok != "" {
		LogDebug("   🎵 TikTok (old):   " + oldTikTok)
	}
	if igPyPath != "" {
		LogDebug("   📷 IG (python):    " + igPyPath)
	}
	if ttPyPath != "" {
		LogDebug("   🎵 TikTok (python):" + ttPyPath)
	}
	if facebookPath != "" {
		LogDebug("   📘 Facebook:       " + facebookPath)
	} else {
		LogDebug("   📘 Facebook:       (not configured)")
	}

	return map[string][]string{
		"twitter":      {oldTwitter},
		"instagram":    {oldInstagram},
		"tiktok":       {oldTikTok},
		"py_instagram": {igPyPath},
		"py_tiktok":    {ttPyPath},
		"facebook":     {facebookPath}, // ✅ NEW
	}
}

func (a *App) ReindexDatabase() ReindexResult {
	a.reindexMu.Lock()
	defer a.reindexMu.Unlock()

	result := ReindexResult{}
	startTime := time.Now()

	exePath, _ := os.Executable()
	exeDir := filepath.Dir(exePath)

	LogClear()
	LogDebug("")
	LogDebug("═══════════════════════════════════════════")
	LogDebug("  RE-INDEX START")
	LogDebug("  " + time.Now().Format("2006-01-02 15:04:05"))
	LogDebug("═══════════════════════════════════════════")
	LogDebug("exePath: " + exePath)

	paths := a.resolveAllPaths(exeDir)

	dbFile := filepath.Join(exeDir, "media_library.db")
	for _, p := range []string{
		filepath.Join(exeDir, "media_library.db"),
		filepath.Join(exeDir, "..", "media_library.db"),
		filepath.Join(exeDir, "..", "..", "media_library.db"),
	} {
		if _, err := os.Stat(filepath.Dir(p)); err == nil {
			dbFile = p
			break
		}
	}
	LogDebug("💾 DB: " + dbFile)

	if a.db != nil {
		a.db.Close()
		a.db = nil
	}

	db, err := sql.Open("sqlite", dbFile)
	if err != nil {
		result.Message = fmt.Sprintf("Failed to open DB: %v", err)
		LogDebug("❌ " + result.Message)
		return result
	}

	for _, p := range []string{
		"PRAGMA synchronous = OFF",
		"PRAGMA journal_mode = MEMORY",
		"PRAGMA temp_store = MEMORY",
		"PRAGMA cache_size = -64000",
		"PRAGMA mmap_size = 268435456",
	} {
		db.Exec(p)
	}

	// ✅ SCHEMA UPDATE: full_path UNIQUE (senior best practice)
	mediaSchema := `
		DROP TABLE IF EXISTS media_fts;
		DROP TABLE IF EXISTS media_tags;
		DROP TABLE IF EXISTS tags;
		DROP TABLE IF EXISTS media;
		CREATE TABLE media (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			platform TEXT NOT NULL, account TEXT NOT NULL, type TEXT NOT NULL,
			filename TEXT, folder TEXT, year TEXT, timestamp TEXT,
			caption TEXT, likes INTEGER DEFAULT 0, url TEXT,
			full_path TEXT UNIQUE NOT NULL,
			thumbnail TEXT
		);
		CREATE TABLE tags (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL);
		CREATE TABLE media_tags (media_id INTEGER, tag_id INTEGER, PRIMARY KEY (media_id, tag_id));
		CREATE INDEX idx_media_platform ON media(platform);
		CREATE INDEX idx_media_account ON media(account);
		CREATE INDEX idx_media_type ON media(type);
		CREATE INDEX idx_media_year ON media(year);
		CREATE INDEX idx_media_timestamp ON media(timestamp DESC);
		CREATE INDEX idx_tags_name ON tags(name);
	`
	if _, err := db.Exec(mediaSchema); err != nil {
		result.Message = fmt.Sprintf("Schema error: %v", err)
		LogDebug("❌ " + result.Message)
		db.Close()
		return result
	}

	// Preserve youtube_queue + idol tables
	db.Exec(`CREATE TABLE IF NOT EXISTS youtube_queue (
		id INTEGER PRIMARY KEY AUTOINCREMENT, video_path TEXT UNIQUE NOT NULL,
		thumbnail_path TEXT, platform TEXT, account TEXT, title TEXT,
		description TEXT, tags TEXT, privacy TEXT DEFAULT 'public',
		made_for_kids INTEGER DEFAULT 0, playlist TEXT,
		status TEXT DEFAULT 'pending', youtube_url TEXT, error TEXT,
		attempts INTEGER DEFAULT 0, created_at TEXT, started_at TEXT, finished_at TEXT
	)`)
	db.Exec(`CREATE INDEX IF NOT EXISTS idx_youtube_status ON youtube_queue(status)`)
	db.Exec(`CREATE INDEX IF NOT EXISTS idx_youtube_created ON youtube_queue(created_at DESC)`)

	db.Exec(`CREATE TABLE IF NOT EXISTS idol_groups (
		id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, parent_id INTEGER,
		icon TEXT DEFAULT '👤', color TEXT DEFAULT '#4a9eff',
		sort_order INTEGER DEFAULT 0, created_at TEXT
	)`)
	db.Exec(`CREATE TABLE IF NOT EXISTS idol_accounts (
		id INTEGER PRIMARY KEY AUTOINCREMENT, group_id INTEGER NOT NULL,
		platform TEXT NOT NULL, username TEXT NOT NULL, enabled INTEGER DEFAULT 1,
		last_check_at TEXT, last_download_at TEXT, created_at TEXT,
		UNIQUE(group_id, platform, username)
	)`)
	db.Exec(`CREATE TABLE IF NOT EXISTS idol_group_runs (
		id INTEGER PRIMARY KEY AUTOINCREMENT, group_id INTEGER NOT NULL,
		status TEXT DEFAULT 'running', total_accounts INTEGER DEFAULT 0,
		checked_accounts INTEGER DEFAULT 0, new_posts_found INTEGER DEFAULT 0,
		new_posts_downloaded INTEGER DEFAULT 0, error TEXT,
		started_at TEXT, finished_at TEXT
	)`)
	db.Exec(`CREATE INDEX IF NOT EXISTS idx_idol_groups_parent ON idol_groups(parent_id)`)
	db.Exec(`CREATE INDEX IF NOT EXISTS idx_idol_accounts_group ON idol_accounts(group_id)`)
	db.Exec(`CREATE INDEX IF NOT EXISTS idx_idol_runs_group ON idol_group_runs(group_id)`)
	db.Exec(`CREATE TABLE IF NOT EXISTS app_settings (
		key TEXT PRIMARY KEY,
		value TEXT,
		updated_at TEXT
	)`)
	runtime.EventsEmit(a.ctx, "indexProgress", IndexProgress{Phase: "counting"})

	twCount := a.countTwitter(paths["twitter"])
	igOldCount := a.countInstagram(paths["instagram"])
	igPyCount := a.countInstagram(paths["py_instagram"])
	ttOldCount := a.countTikTokOld(paths["tiktok"])
	ttPyCount := a.countTikTokNew(paths["py_tiktok"])
	fbCount := a.countFacebook(paths["facebook"]) // ✅ NEW
	total := twCount + igOldCount + igPyCount + ttOldCount + ttPyCount + fbCount

	LogDebug("")
	LogDebug("📊 Counting:")
	LogDebug(fmt.Sprintf("   Twitter:         %d", twCount))
	LogDebug(fmt.Sprintf("   IG (old):        %d", igOldCount))
	LogDebug(fmt.Sprintf("   IG (python):     %d", igPyCount))
	LogDebug(fmt.Sprintf("   TikTok (old):    %d", ttOldCount))
	LogDebug(fmt.Sprintf("   TikTok (python): %d", ttPyCount))
	LogDebug(fmt.Sprintf("   Facebook:        %d", fbCount)) // ✅ NEW
	LogDebug(fmt.Sprintf("   TOTAL:           %d", total))

	if total == 0 {
		result.Message = "No media files found"
		LogDebug("❌ No files found!")
		db.Close()
		return result
	}

	processed, lastEmit := 0, time.Now()
	progressCb := func(phase string, current int) {
		processed++
		now := time.Now()
		if processed%100 != 0 && now.Sub(lastEmit) < 500*time.Millisecond {
			return
		}
		lastEmit = now
		elapsed := time.Since(startTime).Seconds()
		percent := float64(processed) / float64(total) * 100
		ips := float64(processed) / elapsed
		est := float64(total) / ips
		rem := est - elapsed
		if rem < 0 {
			rem = 0
		}
		runtime.EventsEmit(a.ctx, "indexProgress", IndexProgress{
			Phase: phase, Current: processed, Total: total,
			Percent: percent, Elapsed: elapsed, Estimated: est,
			Remaining: rem, ItemsPerSec: ips,
		})
	}

	tx, err := db.Begin()
	if err != nil {
		result.Message = fmt.Sprintf("Tx error: %v", err)
		LogDebug("❌ " + result.Message)
		db.Close()
		return result
	}

	stmts, _ := prepareStmts(tx)

	tw := a.loadTwitter(stmts, paths["twitter"], progressCb)
	igOld := a.loadInstagram(stmts, paths["instagram"], progressCb)
	igPy := a.loadInstagram(stmts, paths["py_instagram"], progressCb)
	ttOld := a.loadTikTokOld(stmts, paths["tiktok"], progressCb)
	ttPy := a.loadTikTokNew(stmts, paths["py_tiktok"], progressCb)
	fb := a.loadFacebook(stmts, paths["facebook"], progressCb) // ✅ NEW

	tx.Commit()

	for _, s := range []*sql.Stmt{stmts.Media, stmts.Tag, stmts.GetTag, stmts.MediaTag} {
		if s != nil {
			s.Close()
		}
	}
	db.Close()
	a.connectDB()

	loaded := tw + igOld + igPy + ttOld + ttPy + fb // ✅ NEW
	result.Success = true
	result.Total = loaded
	result.Message = fmt.Sprintf(
		"Indexed %d media (Twitter:%d, IG:%d, IG-Py:%d, TikTok:%d, TikTok-Py:%d, Facebook:%d) in %.2fs",
		loaded, tw, igOld, igPy, ttOld, ttPy, fb, time.Since(startTime).Seconds())

	LogDebug("")
	LogDebug("✅ Selesai: " + result.Message)
	LogDebug("═══════════════════════════════════════════")

	return result
}

// ══════════════════════════════════════════════════════════
// REINDEX — INCREMENTAL (Quick Scan) — FIXED: Transaction wrap
// ══════════════════════════════════════════════════════════

func (a *App) ReindexIncremental() ReindexResult {
	a.reindexMu.Lock()
	defer a.reindexMu.Unlock()

	result := ReindexResult{}
	startTime := time.Now()

	exePath, _ := os.Executable()
	exeDir := filepath.Dir(exePath)

	LogDebug("")
	LogDebug("═══════════════════════════════════════")
	LogDebug("  INCREMENTAL RE-INDEX START")
	LogDebug("═══════════════════════════════════════")

	paths := a.resolveAllPaths(exeDir)

	if a.db == nil {
		result.Message = "DB not connected"
		return result
	}

	// ⚡ FIX: Bungkus semua dalam 1 transaction
	tx, err := a.db.Begin()
	if err != nil {
		result.Message = "Tx begin error: " + err.Error()
		return result
	}
	committed := false
	defer func() {
		if !committed {
			tx.Rollback()
		}
	}()

	stmtMedia, _ := tx.Prepare(`INSERT INTO media (platform,account,type,filename,folder,year,
		timestamp,caption,likes,url,full_path,thumbnail) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
		ON CONFLICT(full_path) DO UPDATE SET
			caption = CASE WHEN excluded.caption != '' THEN excluded.caption ELSE media.caption END,
			thumbnail = CASE WHEN excluded.thumbnail != '' THEN excluded.thumbnail ELSE media.thumbnail END,
			timestamp = CASE WHEN excluded.timestamp != '' THEN excluded.timestamp ELSE media.timestamp END,
			year = CASE WHEN excluded.year != '' AND excluded.year != 'Unknown' THEN excluded.year ELSE media.year END
		RETURNING id`)
	stmtTag, _ := tx.Prepare("INSERT OR IGNORE INTO tags (name) VALUES (?)")
	stmtGetTag, _ := tx.Prepare("SELECT id FROM tags WHERE name = ?")
	stmtMediaTag, _ := tx.Prepare("INSERT OR IGNORE INTO media_tags (media_id, tag_id) VALUES (?,?)")

	defer stmtMedia.Close()
	defer stmtTag.Close()
	defer stmtGetTag.Close()
	defer stmtMediaTag.Close()

	inserted := 0

	insertOrUpdate := func(platform, account, mtype, filename, folder, year,
		timestamp, caption string, likes int, url, fullPath, thumb string, tags []string) {

		var id int64
		err := stmtMedia.QueryRow(platform, account, mtype, filename, folder, year,
			timestamp, caption, likes, url, fullPath, thumb).Scan(&id)
		if err != nil {
			return
		}
		inserted++

		for _, tag := range tags {
			if tag == "" {
				continue
			}
			stmtTag.Exec(tag)
			var tagID int64
			stmtGetTag.QueryRow(tag).Scan(&tagID)
			stmtMediaTag.Exec(id, tagID)
		}
	}

	// ─── INSTAGRAM ───
	igPaths := paths["py_instagram"]
	if len(igPaths) > 0 && igPaths[0] != "" {
		entries, _ := os.ReadDir(igPaths[0])
		for _, entry := range entries {
			if !entry.IsDir() {
				continue
			}
			userFolder := filepath.Join(igPaths[0], entry.Name())
			username := entry.Name()
			dataFile := filepath.Join(userFolder, username+"_data.json")

			postMeta := map[string]IGPostMeta{}
			if data, err := os.ReadFile(dataFile); err == nil {
				var ig InstagramData
				if json.Unmarshal(data, &ig) == nil {
					for _, p := range ig.Posts {
						key := strings.ReplaceAll(p.DateUTC, " ", "_")
						key = strings.ReplaceAll(key, ":", "-") + "_UTC"
						thumb := ""
						if p.Thumbnail != "" {
							if _, err := os.Stat(p.Thumbnail); err == nil {
								thumb = p.Thumbnail
							}
						}
						if thumb == "" && p.Shortcode != "" {
							alt := filepath.Join(userFolder, "thumbnails", p.Shortcode+"_thumb.jpg")
							if _, err := os.Stat(alt); err == nil {
								thumb = alt
							}
						}
						postMeta[key] = IGPostMeta{p.Caption, p.Hashtags, p.Likes, p.URL, thumb}
					}
				}
			}

			tsRe := regexp.MustCompile(`^(\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}_UTC)`)

			for _, sub := range []string{"photo", "reel"} {
				dir := filepath.Join(userFolder, sub)
				filepath.Walk(dir, func(path string, info os.FileInfo, err error) error {
					if err != nil || info.IsDir() {
						return nil
					}
					ext := strings.ToLower(filepath.Ext(path))
					isPhoto := ext == ".jpg" || ext == ".jpeg" || ext == ".png" || ext == ".webp"
					isVideo := ext == ".mp4" || ext == ".mov" || ext == ".webm"
					if !isPhoto && !isVideo {
						return nil
					}
					relPath, _ := filepath.Rel(userFolder, path)
					year := "Unknown"
					parts := strings.Split(relPath, string(filepath.Separator))
					if len(parts) >= 2 {
						year = parts[1]
					}
					tsKey := ""
					if m := tsRe.FindStringSubmatch(strings.TrimSuffix(info.Name(), ext)); len(m) > 1 {
						tsKey = m[1]
					}
					caption, tags, likes, url, thumb := "", []string{}, 0, "", ""
					if meta, ok := postMeta[tsKey]; ok {
						caption, tags, likes, url = meta.Caption, meta.Hashtags, meta.Likes, meta.URL
						if meta.Thumbnail != "" {
							if _, err := os.Stat(meta.Thumbnail); err == nil {
								thumb = meta.Thumbnail
							}
						}
					}
					mtype := "photo"
					if isVideo {
						mtype = "video"
					}
					insertOrUpdate("Instagram", username, mtype, info.Name(),
						strings.ReplaceAll(relPath, "\\", "/"), year, tsKey, caption,
						likes, url, path, thumb, tags)
					return nil
				})
			}
		}
	}

	// ─── TIKTOK ───
	ttPaths := paths["py_tiktok"]
	if len(ttPaths) > 0 && ttPaths[0] != "" {
		entries, _ := os.ReadDir(ttPaths[0])
		for _, entry := range entries {
			if !entry.IsDir() {
				continue
			}
			userFolder := filepath.Join(ttPaths[0], entry.Name())
			filepath.Walk(userFolder, func(path string, info os.FileInfo, err error) error {
				if err != nil || info.IsDir() {
					return nil
				}
				ext := strings.ToLower(filepath.Ext(path))
				if !videoExts[ext] {
					return nil
				}
				filename := info.Name()
				relPath, _ := filepath.Rel(userFolder, path)
				caption, timestamp, year := "", "", "Unknown"
				var tags []string
				jsonFile := strings.TrimSuffix(path, ext) + ".info.json"
				if data, err := os.ReadFile(jsonFile); err == nil {
					var infoData map[string]interface{}
					if json.Unmarshal(data, &infoData) == nil {
						if v, ok := infoData["description"].(string); ok {
							caption = v
						}
						if v, ok := infoData["upload_date"].(string); ok && len(v) >= 8 {
							year = v[:4]
							timestamp = fmt.Sprintf("%s-%s-%s", v[:4], v[4:6], v[6:8])
						}
						if v, ok := infoData["timestamp"].(float64); ok {
							t := time.Unix(int64(v), 0)
							timestamp = t.Format("2006-01-02 15:04:05")
							year = t.Format("2006")
						}
						if arr, ok := infoData["tags"].([]interface{}); ok {
							for _, tag := range arr {
								if s, ok := tag.(string); ok {
									tags = append(tags, s)
								}
							}
						}
					}
				}
				base := strings.TrimSuffix(path, ext)
				thumbPath := ""
				for _, tc := range []string{base + ".jpg", base + ".webp", base + ".png", base + "_thumb.jpg"} {
					if _, err := os.Stat(tc); err == nil {
						thumbPath = tc
						break
					}
				}
				insertOrUpdate("TikTok", entry.Name(), "video", filename,
					relPath, year, timestamp, caption, 0, "", path, thumbPath, tags)
				return nil
			})
		}
	}

	// ─── FACEBOOK ───
	fbPaths := paths["facebook"]
	if len(fbPaths) > 0 && fbPaths[0] != "" {
		a.scanFacebookFolder(fbPaths[0], insertOrUpdate)
	}

	// ⚡ Commit di akhir
	if err := tx.Commit(); err != nil {
		result.Message = "Commit error: " + err.Error()
		return result
	}
	committed = true

	elapsed := time.Since(startTime).Seconds()
	result.Success = true
	result.Total = inserted
	result.Message = fmt.Sprintf("%d media diproses dalam %.2fs", inserted, elapsed)

	LogDebug("✅ " + result.Message)
	return result
}

// ══════════════════════════════════════════════════════════
// REINDEX — SINGLE ACCOUNT
// ══════════════════════════════════════════════════════════

func (a *App) ReindexAccount(platform, username string) ReindexResult {
	result := ReindexResult{}
	startTime := time.Now()

	if a.db == nil {
		result.Message = "DB not connected"
		return result
	}

	exePath, _ := os.Executable()
	exeDir := filepath.Dir(exePath)
	paths := a.resolveAllPaths(exeDir)

	var userFolder string
	if platform == "Instagram" && len(paths["py_instagram"]) > 0 {
		userFolder = filepath.Join(paths["py_instagram"][0], username)
	} else if platform == "TikTok" && len(paths["py_tiktok"]) > 0 {
		userFolder = filepath.Join(paths["py_tiktok"][0], username)
	} else if platform == "Facebook" && len(paths["facebook"]) > 0 {
		userFolder = filepath.Join(paths["facebook"][0], username)
	}

	if userFolder == "" {
		result.Message = "Folder tidak ditemukan untuk " + platform + "/" + username
		return result
	}
	if _, err := os.Stat(userFolder); err != nil {
		result.Message = "Folder tidak ada: " + userFolder
		return result
	}

	mediaIDs := []int{}
	rows, err := a.db.Query("SELECT id FROM media WHERE platform = ? AND account = ?",
		platform, username)
	if err == nil {
		for rows.Next() {
			var id int
			rows.Scan(&id)
			mediaIDs = append(mediaIDs, id)
		}
		rows.Close()
	}
	for _, id := range mediaIDs {
		a.db.Exec("DELETE FROM media_tags WHERE media_id = ?", id)
	}
	a.db.Exec("DELETE FROM media WHERE platform = ? AND account = ?",
		platform, username)

	stmtMedia, _ := a.db.Prepare(`INSERT INTO media (platform,account,type,filename,folder,year,
		timestamp,caption,likes,url,full_path,thumbnail) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)`)
	stmtTag, _ := a.db.Prepare("INSERT OR IGNORE INTO tags (name) VALUES (?)")
	stmtGetTag, _ := a.db.Prepare("SELECT id FROM tags WHERE name = ?")
	stmtMediaTag, _ := a.db.Prepare("INSERT OR IGNORE INTO media_tags (media_id, tag_id) VALUES (?,?)")

	defer stmtMedia.Close()
	defer stmtTag.Close()
	defer stmtGetTag.Close()
	defer stmtMediaTag.Close()

	inserted := 0

	if platform == "Instagram" {
		dataFile := filepath.Join(userFolder, username+"_data.json")
		postMeta := map[string]IGPostMeta{}
		if data, err := os.ReadFile(dataFile); err == nil {
			var ig InstagramData
			if json.Unmarshal(data, &ig) == nil {
				for _, p := range ig.Posts {
					key := strings.ReplaceAll(p.DateUTC, " ", "_")
					key = strings.ReplaceAll(key, ":", "-") + "_UTC"
					thumb := ""
					if p.Thumbnail != "" {
						if _, err := os.Stat(p.Thumbnail); err == nil {
							thumb = p.Thumbnail
						}
					}
					if thumb == "" && p.Shortcode != "" {
						alt := filepath.Join(userFolder, "thumbnails", p.Shortcode+"_thumb.jpg")
						if _, err := os.Stat(alt); err == nil {
							thumb = alt
						}
					}
					postMeta[key] = IGPostMeta{p.Caption, p.Hashtags, p.Likes, p.URL, thumb}
				}
			}
		}
		tsRe := regexp.MustCompile(`^(\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}_UTC)`)
		for _, sub := range []string{"photo", "reel"} {
			dir := filepath.Join(userFolder, sub)
			filepath.Walk(dir, func(path string, info os.FileInfo, err error) error {
				if err != nil || info.IsDir() {
					return nil
				}
				ext := strings.ToLower(filepath.Ext(path))
				isPhoto := ext == ".jpg" || ext == ".jpeg" || ext == ".png" || ext == ".webp"
				isVideo := ext == ".mp4" || ext == ".mov" || ext == ".webm"
				if !isPhoto && !isVideo {
					return nil
				}
				relPath, _ := filepath.Rel(userFolder, path)
				year := "Unknown"
				parts := strings.Split(relPath, string(filepath.Separator))
				if len(parts) >= 2 {
					year = parts[1]
				}
				tsKey := ""
				if m := tsRe.FindStringSubmatch(strings.TrimSuffix(info.Name(), ext)); len(m) > 1 {
					tsKey = m[1]
				}
				caption, tags, likes, url, thumb := "", []string{}, 0, "", ""
				if meta, ok := postMeta[tsKey]; ok {
					caption, tags, likes, url = meta.Caption, meta.Hashtags, meta.Likes, meta.URL
					thumb = meta.Thumbnail
				}
				mtype := "photo"
				if isVideo {
					mtype = "video"
				}
				res, err := stmtMedia.Exec("Instagram", username, mtype, info.Name(),
					strings.ReplaceAll(relPath, "\\", "/"), year, tsKey, caption,
					likes, url, path, thumb)
				if err == nil {
					mediaID, _ := res.LastInsertId()
					for _, tag := range tags {
						if tag == "" {
							continue
						}
						stmtTag.Exec(tag)
						var tagID int64
						stmtGetTag.QueryRow(tag).Scan(&tagID)
						stmtMediaTag.Exec(mediaID, tagID)
					}
					inserted++
				}
				return nil
			})
		}
	} else if platform == "TikTok" {
		filepath.Walk(userFolder, func(path string, info os.FileInfo, err error) error {
			if err != nil || info.IsDir() {
				return nil
			}
			ext := strings.ToLower(filepath.Ext(path))
			if !videoExts[ext] {
				return nil
			}
			filename := info.Name()
			relPath, _ := filepath.Rel(userFolder, path)
			caption, timestamp, year := "", "", "Unknown"
			var tags []string
			jsonFile := strings.TrimSuffix(path, ext) + ".info.json"
			if data, err := os.ReadFile(jsonFile); err == nil {
				var infoData map[string]interface{}
				if json.Unmarshal(data, &infoData) == nil {
					if v, ok := infoData["description"].(string); ok {
						caption = v
					}
					if v, ok := infoData["upload_date"].(string); ok && len(v) >= 8 {
						year = v[:4]
						timestamp = fmt.Sprintf("%s-%s-%s", v[:4], v[4:6], v[6:8])
					}
					if arr, ok := infoData["tags"].([]interface{}); ok {
						for _, tag := range arr {
							if s, ok := tag.(string); ok {
								tags = append(tags, s)
							}
						}
					}
				}
			}
			base := strings.TrimSuffix(path, ext)
			thumbPath := ""
			for _, tc := range []string{base + ".jpg", base + ".webp", base + ".png", base + "_thumb.jpg"} {
				if _, err := os.Stat(tc); err == nil {
					thumbPath = tc
					break
				}
			}
			res, err := stmtMedia.Exec("TikTok", username, "video", filename,
				relPath, year, timestamp, caption, 0, "", path, thumbPath)
			if err == nil {
				mediaID, _ := res.LastInsertId()
				for _, tag := range tags {
					if tag == "" {
						continue
					}
					stmtTag.Exec(tag)
					var tagID int64
					stmtGetTag.QueryRow(tag).Scan(&tagID)
					stmtMediaTag.Exec(mediaID, tagID)
				}
				inserted++
			}
			return nil
		})
	} else if platform == "Facebook" {
		// ✅ NEW: Facebook single account reindex
		filepath.Walk(userFolder, func(path string, info os.FileInfo, err error) error {
			if err != nil || info.IsDir() {
				return nil
			}
			ext := strings.ToLower(filepath.Ext(path))
			if !videoExts[ext] {
				return nil
			}
			filename := info.Name()
			relPath, _ := filepath.Rel(userFolder, path)

			caption, timestamp, year := "", "", "Unknown"
			var tags []string

			jsonFile := strings.TrimSuffix(path, ext) + ".info.json"
			if data, err := os.ReadFile(jsonFile); err == nil {
				var infoData map[string]interface{}
				if json.Unmarshal(data, &infoData) == nil {
					if v, ok := infoData["description"].(string); ok {
						caption = v
					} else if v, ok := infoData["title"].(string); ok {
						caption = v
					}
					if v, ok := infoData["upload_date"].(string); ok && len(v) >= 8 {
						year = v[:4]
						timestamp = fmt.Sprintf("%s-%s-%s", v[:4], v[4:6], v[6:8])
					}
					if v, ok := infoData["timestamp"].(float64); ok {
						tm := time.Unix(int64(v), 0)
						timestamp = tm.Format("2006-01-02 15:04:05")
						year = tm.Format("2006")
					}
					if arr, ok := infoData["tags"].([]interface{}); ok {
						for _, tag := range arr {
							if s, ok := tag.(string); ok {
								tags = append(tags, s)
							}
						}
					}
				}
			}

			base := strings.TrimSuffix(path, ext)
			thumbPath := ""
			for _, tc := range []string{base + ".jpg", base + ".webp", base + ".png", base + "_thumb.jpg"} {
				if _, err := os.Stat(tc); err == nil {
					thumbPath = tc
					break
				}
			}

			res, err := stmtMedia.Exec("Facebook", username, "video", filename,
				relPath, year, timestamp, caption, 0, "", path, thumbPath)
			if err == nil {
				mediaID, _ := res.LastInsertId()
				for _, tag := range tags {
					if tag == "" {
						continue
					}
					stmtTag.Exec(tag)
					var tagID int64
					stmtGetTag.QueryRow(tag).Scan(&tagID)
					stmtMediaTag.Exec(mediaID, tagID)
				}
				inserted++
			}
			return nil
		})
	}

	elapsed := time.Since(startTime).Seconds()
	result.Success = true
	result.Total = inserted
	result.Message = fmt.Sprintf("%s/%s: %d media dalam %.2fs",
		platform, username, inserted, elapsed)

	LogDebug("✅ " + result.Message)
	return result
}

// ══════════════════════════════════════════════════════════
// PRUNE MISSING FILES
// ══════════════════════════════════════════════════════════

func (a *App) PruneMissingFiles() map[string]interface{} {
	res := map[string]interface{}{"ok": false, "removed": 0, "checked": 0}

	if a.db == nil {
		res["msg"] = "DB not connected"
		return res
	}

	startTime := time.Now()
	LogDebug("🧹 Prune missing files...")

	type rec struct {
		id   int
		path string
	}
	var all []rec
	rows, _ := a.db.Query("SELECT id, full_path FROM media")
	if rows == nil {
		res["msg"] = "Query failed"
		return res
	}
	for rows.Next() {
		var r rec
		rows.Scan(&r.id, &r.path)
		all = append(all, r)
	}
	rows.Close()

	res["checked"] = len(all)

	removed := 0
	for _, r := range all {
		if r.path == "" {
			continue
		}
		if _, err := os.Stat(r.path); os.IsNotExist(err) {
			a.db.Exec("DELETE FROM media_tags WHERE media_id = ?", r.id)
			a.db.Exec("DELETE FROM media WHERE id = ?", r.id)
			removed++
		}
	}

	elapsed := time.Since(startTime).Seconds()
	res["ok"] = true
	res["removed"] = removed
	res["elapsed"] = elapsed
	res["msg"] = fmt.Sprintf("%d entry dihapus dari %d total", removed, len(all))

	LogDebug(fmt.Sprintf("✅ Prune: %s (%.2fs)", res["msg"], elapsed))
	return res
}

// ══════════════════════════════════════════════════════════
// LOADER HELPERS
// ══════════════════════════════════════════════════════════

func insertMediaWithTags(stmts *PreparedStmts, platform, account, mtype, filename,
	folder, year, timestamp, caption string, likes int, url, fullPath, thumbnail string,
	tags []string) bool {

	res, err := stmts.Media.Exec(platform, account, mtype, filename, folder,
		year, timestamp, caption, likes, url, fullPath, thumbnail)
	if err != nil {
		return false
	}
	mediaID, _ := res.LastInsertId()
	for _, tag := range tags {
		if tag == "" {
			continue
		}
		stmts.Tag.Exec(tag)
		var tagID int64
		stmts.GetTag.QueryRow(tag).Scan(&tagID)
		stmts.MediaTag.Exec(mediaID, tagID)
	}
	return true
}

func prepareStmts(tx *sql.Tx) (*PreparedStmts, error) {
	m, _ := tx.Prepare(`INSERT INTO media (platform,account,type,filename,folder,year,
		timestamp,caption,likes,url,full_path,thumbnail) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)`)
	t, _ := tx.Prepare("INSERT OR IGNORE INTO tags (name) VALUES (?)")
	gt, _ := tx.Prepare("SELECT id FROM tags WHERE name = ?")
	mt, _ := tx.Prepare("INSERT OR IGNORE INTO media_tags (media_id, tag_id) VALUES (?,?)")
	return &PreparedStmts{m, t, gt, mt}, nil
}

// ══════════════════════════════════════════════════════════
// LOADERS
// ══════════════════════════════════════════════════════════

func (a *App) loadTwitter(stmts *PreparedStmts, paths []string, cb func(string, int)) int {
	count := 0
	for _, downloadsPath := range paths {
		if downloadsPath == "" {
			continue
		}
		entries, _ := os.ReadDir(downloadsPath)
		for _, entry := range entries {
			if !entry.IsDir() {
				continue
			}
			accountFolder := filepath.Join(downloadsPath, entry.Name())
			data, err := os.ReadFile(filepath.Join(accountFolder, "progress_v2.json"))
			if err != nil {
				continue
			}

			var td TwitterMediaData
			if json.Unmarshal(data, &td) != nil {
				continue
			}

			thumbFolder := filepath.Join(accountFolder, "thumbnails")
			for _, m := range td.MediaData {
				mtype := getMediaType(m.Filename)
				if mtype == "unknown" {
					mtype = m.Type
					if mtype == "" {
						mtype = "photo"
					}
				}
				fullPath := filepath.Join(accountFolder, m.Folder)

				thumb := ""
				if mtype == "video" {
					tn := strings.TrimSuffix(m.Filename, filepath.Ext(m.Filename)) + "_thumb.jpg"
					tf := filepath.Join(thumbFolder, tn)
					if _, err := os.Stat(tf); err == nil {
						thumb = tf
					}
				}

				if insertMediaWithTags(stmts, "Twitter", entry.Name(), mtype, m.Filename,
					m.Folder, fmt.Sprintf("%d", m.Year), m.Timestamp, m.Caption,
					0, "", fullPath, thumb, extractHashtags(m.Caption)) {
					count++
				}
				cb("Twitter", count)
			}
		}
	}
	return count
}

func (a *App) loadInstagram(stmts *PreparedStmts, paths []string, cb func(string, int)) int {
	count := 0
	for _, downloadsPath := range paths {
		if downloadsPath == "" {
			continue
		}
		entries, _ := os.ReadDir(downloadsPath)
		for _, entry := range entries {
			if !entry.IsDir() {
				continue
			}
			userFolder := filepath.Join(downloadsPath, entry.Name())
			dataFile := filepath.Join(userFolder, entry.Name()+"_data.json")

			postMetadata := make(map[string]IGPostMeta)

			if data, err := os.ReadFile(dataFile); err == nil {
				var ig InstagramData
				if json.Unmarshal(data, &ig) == nil {
					for _, p := range ig.Posts {
						key := strings.ReplaceAll(p.DateUTC, " ", "_")
						key = strings.ReplaceAll(key, ":", "-") + "_UTC"

						thumb := ""
						if p.Thumbnail != "" {
							if _, err := os.Stat(p.Thumbnail); err == nil {
								thumb = p.Thumbnail
							}
						}
						if thumb == "" && p.Shortcode != "" {
							alt := filepath.Join(userFolder, "thumbnails", p.Shortcode+"_thumb.jpg")
							if _, err := os.Stat(alt); err == nil {
								thumb = alt
							}
						}

						postMetadata[key] = IGPostMeta{
							Caption:   p.Caption,
							Hashtags:  p.Hashtags,
							Likes:     p.Likes,
							URL:       p.URL,
							Thumbnail: thumb,
						}
					}
				}
			}

			tsRe := regexp.MustCompile(`^(\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}_UTC)`)

			photoDir := filepath.Join(userFolder, "photo")
			filepath.Walk(photoDir, func(path string, info os.FileInfo, err error) error {
				if err != nil || info.IsDir() {
					return nil
				}
				ext := strings.ToLower(filepath.Ext(path))
				if ext != ".jpg" && ext != ".jpeg" && ext != ".png" && ext != ".webp" {
					return nil
				}
				a.processIGMedia(stmts, userFolder, entry.Name(), path, info,
					"photo", ext, tsRe, postMetadata, &count, cb)
				return nil
			})

			reelDir := filepath.Join(userFolder, "reel")
			thumbFolder := filepath.Join(userFolder, "thumbnails")
			filepath.Walk(reelDir, func(path string, info os.FileInfo, err error) error {
				if err != nil || info.IsDir() {
					return nil
				}
				ext := strings.ToLower(filepath.Ext(path))
				if ext != ".mp4" && ext != ".mov" && ext != ".webm" {
					return nil
				}
				a.processIGMediaWithThumb(stmts, userFolder, entry.Name(), path, info,
					ext, tsRe, postMetadata, thumbFolder, &count, cb)
				return nil
			})
		}
	}
	return count
}

func (a *App) processIGMedia(stmts *PreparedStmts, userFolder, account, path string,
	info os.FileInfo, mtype, ext string, tsRe *regexp.Regexp,
	postMeta map[string]IGPostMeta, count *int, cb func(string, int)) {

	filename := info.Name()
	relPath, _ := filepath.Rel(userFolder, path)
	year := "Unknown"
	parts := strings.Split(relPath, string(filepath.Separator))
	if len(parts) >= 2 {
		year = parts[1]
	}
	tsKey := ""
	if m := tsRe.FindStringSubmatch(strings.TrimSuffix(filename, ext)); len(m) > 1 {
		tsKey = m[1]
	}

	caption, tags, likes, url, thumb := "", []string{}, 0, "", ""
	if meta, ok := postMeta[tsKey]; ok {
		caption, tags, likes, url = meta.Caption, meta.Hashtags, meta.Likes, meta.URL
		if meta.Thumbnail != "" {
			if _, err := os.Stat(meta.Thumbnail); err == nil {
				thumb = meta.Thumbnail
			}
		}
	}

	if thumb == "" {
		tn := strings.TrimSuffix(filename, ext) + "_thumb.jpg"
		tf := filepath.Join(userFolder, "thumbnails", tn)
		if _, err := os.Stat(tf); err == nil {
			thumb = tf
		}
	}

	if insertMediaWithTags(stmts, "Instagram", account, mtype, filename,
		strings.ReplaceAll(relPath, "\\", "/"), year, tsKey, caption,
		likes, url, path, thumb, tags) {
		*count++
	}
	cb("Instagram", *count)
}

func (a *App) processIGMediaWithThumb(stmts *PreparedStmts, userFolder, account, path string,
	info os.FileInfo, ext string, tsRe *regexp.Regexp,
	postMeta map[string]IGPostMeta, thumbFolder string, count *int, cb func(string, int)) {

	filename := info.Name()
	relPath, _ := filepath.Rel(userFolder, path)
	year := "Unknown"
	parts := strings.Split(relPath, string(filepath.Separator))
	if len(parts) >= 2 {
		year = parts[1]
	}
	tsKey := ""
	if m := tsRe.FindStringSubmatch(strings.TrimSuffix(filename, ext)); len(m) > 1 {
		tsKey = m[1]
	}

	caption, tags, likes, url, thumb := "", []string{}, 0, "", ""
	if meta, ok := postMeta[tsKey]; ok {
		caption, tags, likes, url = meta.Caption, meta.Hashtags, meta.Likes, meta.URL
		if meta.Thumbnail != "" {
			if _, err := os.Stat(meta.Thumbnail); err == nil {
				thumb = meta.Thumbnail
			}
		}
	}

	if thumb == "" {
		tn := strings.TrimSuffix(filename, ext) + "_thumb.jpg"
		tf := filepath.Join(thumbFolder, tn)
		if _, err := os.Stat(tf); err == nil {
			thumb = tf
		}
	}

	if insertMediaWithTags(stmts, "Instagram", account, "video", filename,
		strings.ReplaceAll(relPath, "\\", "/"), year, tsKey, caption,
		likes, url, path, thumb, tags) {
		*count++
	}
	cb("Instagram", *count)
}

func (a *App) loadTikTokOld(stmts *PreparedStmts, paths []string, cb func(string, int)) int {
	count := 0
	for _, downloadsPath := range paths {
		if downloadsPath == "" {
			continue
		}
		entries, _ := os.ReadDir(downloadsPath)
		for _, entry := range entries {
			if !entry.IsDir() {
				continue
			}
			userFolder := filepath.Join(downloadsPath, entry.Name())
			data, err := os.ReadFile(filepath.Join(userFolder, "videos", "metadata.json"))
			if err != nil {
				continue
			}
			var videos []TikTokVideo
			if json.Unmarshal(data, &videos) != nil {
				continue
			}
			videosDir := filepath.Join(userFolder, "videos")
			for _, v := range videos {
				mtype := getMediaType(v.Filename)
				if mtype == "unknown" {
					mtype = "video"
				}
				year := "Unknown"
				if len(v.CreateTime) >= 4 {
					year = v.CreateTime[:4]
				}
				fullPath := filepath.Join(videosDir, v.Folder)
				thumb := ""
				if v.Thumbnail != "" {
					tf := filepath.Join(videosDir, v.Thumbnail)
					if _, err := os.Stat(tf); err == nil {
						thumb = tf
					}
				}
				if thumb == "" {
					tf2 := filepath.Join(videosDir, year, "thumbnail",
						strings.SplitN(v.Filename, "_", 2)[0]+".jpg")
					if _, err := os.Stat(tf2); err == nil {
						thumb = tf2
					}
				}
				if insertMediaWithTags(stmts, "TikTok", entry.Name(), mtype, v.Filename,
					v.Folder, year, v.CreateTime, v.Caption, 0, "", fullPath, thumb, v.Tags) {
					count++
				}
				cb("TikTok", count)
			}
		}
	}
	return count
}

func (a *App) loadTikTokNew(stmts *PreparedStmts, paths []string, cb func(string, int)) int {
	count := 0
	for _, downloadsPath := range paths {
		if downloadsPath == "" {
			continue
		}
		entries, _ := os.ReadDir(downloadsPath)
		for _, entry := range entries {
			if !entry.IsDir() {
				continue
			}
			userFolder := filepath.Join(downloadsPath, entry.Name())
			filepath.Walk(userFolder, func(path string, info os.FileInfo, err error) error {
				if err != nil || info.IsDir() {
					return nil
				}
				ext := strings.ToLower(filepath.Ext(path))
				if !videoExts[ext] {
					return nil
				}

				filename := info.Name()
				relPath, _ := filepath.Rel(userFolder, path)
				caption, timestamp, year := "", "", "Unknown"
				var tags []string

				jsonFile := strings.TrimSuffix(path, ext) + ".info.json"
				if data, err := os.ReadFile(jsonFile); err == nil {
					var infoData map[string]interface{}
					if json.Unmarshal(data, &infoData) == nil {
						if v, ok := infoData["description"].(string); ok {
							caption = v
						}
						if v, ok := infoData["upload_date"].(string); ok && len(v) >= 8 {
							year = v[:4]
							timestamp = fmt.Sprintf("%s-%s-%s", v[:4], v[4:6], v[6:8])
						}
						if v, ok := infoData["timestamp"].(float64); ok {
							t := time.Unix(int64(v), 0)
							timestamp = t.Format("2006-01-02 15:04:05")
							year = t.Format("2006")
						}
						if arr, ok := infoData["tags"].([]interface{}); ok {
							for _, tag := range arr {
								if s, ok := tag.(string); ok {
									tags = append(tags, s)
								}
							}
						}
					}
				}
				if len(tags) == 0 && caption != "" {
					tags = extractHashtags(caption)
				}

				base := strings.TrimSuffix(path, ext)
				thumbPath := ""
				for _, tc := range []string{base + ".jpg", base + ".webp", base + ".png", base + "_thumb.jpg"} {
					if _, err := os.Stat(tc); err == nil {
						thumbPath = tc
						break
					}
				}

				if insertMediaWithTags(stmts, "TikTok", entry.Name(), "video", filename,
					relPath, year, timestamp, caption, 0, "", path, thumbPath, tags) {
					count++
				}
				cb("TikTok", count)
				return nil
			})
		}
	}
	return count
}

// ══════════════════════════════════════════════════════════
// FACEBOOK LOADER ✅ NEW
// ══════════════════════════════════════════════════════════

// loadFacebook — Full reindex version (bulk insert, transaction-safe)
func (a *App) loadFacebook(stmts *PreparedStmts, paths []string, cb func(string, int)) int {
	count := 0
	for _, downloadsPath := range paths {
		if downloadsPath == "" {
			continue
		}
		entries, _ := os.ReadDir(downloadsPath)
		for _, entry := range entries {
			if !entry.IsDir() {
				continue
			}
			pageFolder := filepath.Join(downloadsPath, entry.Name())
			a.walkFacebookPage(pageFolder, entry.Name(), func(meta fbMeta) {
				if insertMediaWithTags(stmts, "Facebook", meta.account, "video", meta.filename,
					meta.folder, meta.year, meta.timestamp, meta.caption, 0, "", meta.fullPath,
					meta.thumbPath, meta.tags) {
					count++
				}
				cb("Facebook", count)
			})
		}
	}
	return count
}

// scanFacebookFolder — Untuk incremental reindex (pakai callback upsert)
func (a *App) scanFacebookFolder(basePath string, insertOrUpdate func(
	platform, account, mtype, filename, folder, year,
	timestamp, caption string, likes int, url, fullPath, thumb string, tags []string)) {

	entries, err := os.ReadDir(basePath)
	if err != nil {
		return
	}
	for _, entry := range entries {
		if !entry.IsDir() {
			continue
		}
		pageFolder := filepath.Join(basePath, entry.Name())
		a.walkFacebookPage(pageFolder, entry.Name(), func(meta fbMeta) {
			insertOrUpdate("Facebook", meta.account, "video", meta.filename,
				meta.folder, meta.year, meta.timestamp, meta.caption, 0, "",
				meta.fullPath, meta.thumbPath, meta.tags)
		})
	}
}

// fbMeta — internal struct untuk hasil parse Facebook
type fbMeta struct {
	account   string
	filename  string
	folder    string
	year      string
	timestamp string
	caption   string
	fullPath  string
	thumbPath string
	tags      []string
}

// walkFacebookPage — Walk satu folder Page, extract metadata, panggil callback
func (a *App) walkFacebookPage(pageFolder, accountName string, callback func(fbMeta)) {
	filepath.Walk(pageFolder, func(path string, info os.FileInfo, err error) error {
		if err != nil || info.IsDir() {
			return nil
		}

		ext := strings.ToLower(filepath.Ext(path))
		if !videoExts[ext] {
			return nil
		}

		filename := info.Name()
		// relPath, _ := filepath.Rel(pageFolder, path)

		caption := ""
		timestamp := ""
		year := "Unknown"
		var tags []string

		// Cari metadata JSON (yt-dlp style: .info.json)
		jsonCandidates := []string{
			strings.TrimSuffix(path, ext) + ".info.json",
			strings.TrimSuffix(path, ext) + ".json",
			path + ".info.json",
		}

		for _, jsonFile := range jsonCandidates {
			data, err := os.ReadFile(jsonFile)
			if err != nil {
				continue
			}
			var meta map[string]interface{}
			if json.Unmarshal(data, &meta) != nil {
				continue
			}

			// Description / title
			if v, ok := meta["description"].(string); ok && v != "" {
				caption = v
			} else if v, ok := meta["title"].(string); ok && v != "" {
				caption = v
			} else if v, ok := meta["fulltitle"].(string); ok && v != "" {
				caption = v
			}

			// Upload date
			if v, ok := meta["upload_date"].(string); ok && len(v) >= 8 {
				year = v[:4]
				timestamp = fmt.Sprintf("%s-%s-%s", v[:4], v[4:6], v[6:8])
			}

			// Timestamp unix (lebih akurat)
			if v, ok := meta["timestamp"].(float64); ok {
				tm := time.Unix(int64(v), 0)
				timestamp = tm.Format("2006-01-02 15:04:05")
				year = tm.Format("2006")
			}

			// Tags
			if arr, ok := meta["tags"].([]interface{}); ok {
				for _, tag := range arr {
					if s, ok := tag.(string); ok && s != "" {
						tags = append(tags, s)
					}
				}
			}

			// Hashtags dari caption sebagai fallback
			if len(tags) == 0 && caption != "" {
				tags = extractHashtags(caption)
			}

			// Kalau ada thumbnail path di metadata
			if v, ok := meta["thumbnail"].(string); ok && v != "" {
				if _, err := os.Stat(v); err == nil {
					// thumbnail path valid
				}
			}

			break // sudah ketemu, tidak perlu lanjut ke candidate berikutnya
		}

		// Cari thumbnail lokal
		base := strings.TrimSuffix(path, ext)
		thumbPath := ""
		for _, tc := range []string{
			base + ".jpg",
			base + ".jpeg",
			base + ".webp",
			base + ".png",
			base + "_thumb.jpg",
			base + ".thumbnail",
		} {
			if _, err := os.Stat(tc); err == nil {
				thumbPath = tc
				break
			}
		}

		// Kalau tidak ada caption, pakai nama file sebagai fallback
		if caption == "" {
			caption = strings.TrimSuffix(filename, ext)
		}

		callback(fbMeta{
			account:   accountName,
			filename:  filename,
			folder:    filepath.Base(pageFolder),
			year:      year,
			timestamp: timestamp,
			caption:   caption,
			fullPath:  path,
			thumbPath: thumbPath,
			tags:      tags,
		})

		return nil
	})
}

// ══════════════════════════════════════════════════════════
// COUNTERS
// ══════════════════════════════════════════════════════════

func (a *App) countTwitter(paths []string) int {
	count := 0
	for _, p := range paths {
		if p == "" {
			continue
		}
		entries, _ := os.ReadDir(p)
		for _, e := range entries {
			if !e.IsDir() {
				continue
			}
			data, err := os.ReadFile(filepath.Join(p, e.Name(), "progress_v2.json"))
			if err != nil {
				continue
			}
			var td TwitterMediaData
			if json.Unmarshal(data, &td) == nil {
				count += len(td.MediaData)
			}
		}
	}
	return count
}

func (a *App) countInstagram(paths []string) int {
	count := 0
	for _, p := range paths {
		if p == "" {
			continue
		}
		entries, _ := os.ReadDir(p)
		for _, e := range entries {
			if !e.IsDir() {
				continue
			}
			uf := filepath.Join(p, e.Name())
			filepath.Walk(filepath.Join(uf, "photo"), countFiles(&count, imageExts))
			filepath.Walk(filepath.Join(uf, "reel"), countFiles(&count, videoExts))
		}
	}
	return count
}

func (a *App) countTikTokOld(paths []string) int {
	count := 0
	for _, p := range paths {
		if p == "" {
			continue
		}
		entries, _ := os.ReadDir(p)
		for _, e := range entries {
			if !e.IsDir() {
				continue
			}
			data, err := os.ReadFile(filepath.Join(p, e.Name(), "videos", "metadata.json"))
			if err != nil {
				continue
			}
			var videos []TikTokVideo
			if json.Unmarshal(data, &videos) == nil {
				count += len(videos)
			}
		}
	}
	return count
}

func (a *App) countTikTokNew(paths []string) int {
	count := 0
	for _, p := range paths {
		if p == "" {
			continue
		}
		entries, _ := os.ReadDir(p)
		for _, e := range entries {
			if !e.IsDir() {
				continue
			}
			filepath.Walk(filepath.Join(p, e.Name()), countFiles(&count, videoExts))
		}
	}
	return count
}

// countFacebook ✅ NEW
func (a *App) countFacebook(paths []string) int {
	count := 0
	for _, p := range paths {
		if p == "" {
			continue
		}
		entries, _ := os.ReadDir(p)
		for _, e := range entries {
			if !e.IsDir() {
				continue
			}
			filepath.Walk(filepath.Join(p, e.Name()), countFiles(&count, videoExts))
		}
	}
	return count
}

func countFiles(count *int, exts map[string]bool) filepath.WalkFunc {
	return func(path string, info os.FileInfo, err error) error {
		if err != nil || info.IsDir() {
			return nil
		}
		if exts[strings.ToLower(filepath.Ext(path))] {
			*count++
		}
		return nil
	}
}
