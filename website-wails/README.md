# Website-Wails: Ultra Media Viewer

## 🚀 Apa ini?

Media viewer dengan UI seperti website, super smooth scrolling, dan dapat di-compile ke single `.exe` tanpa perlu install apapun di PC lain.

## ✨ Keunggulan

| Feature | Benefit |
|---------|---------|
| 🌐 WebView2 | UI persis seperti website |
| 📜 Smooth Scroll | 60fps buttery smooth scrolling |
| 📦 Single EXE | ~10-15MB, tidak perlu install |
| ⚡ Super Fast | Native Go backend |
| 🎨 Modern UI | CSS animations, transitions |

## 📋 Prerequisites

### 1. Install Wails CLI
```powershell
go install github.com/wailsapp/wails/v2/cmd/wails@latest
```

### 2. Install WebView2 Runtime (biasanya sudah ada di Windows 10/11)
Download dari: https://developer.microsoft.com/en-us/microsoft-edge/webview2/

## 🛠️ Development

### Initialize project (pertama kali)
```powershell
cd website-wails
wails init -n ultra-viewer -t vanilla
```

### Run in development mode
```powershell
wails dev
```

### Build EXE
```powershell
wails build
```

Output akan ada di `build/bin/ultra-viewer.exe`

## 📁 Struktur Project

```
website-wails/
├── main.go              # Go backend
├── go.mod               # Go dependencies
├── wails.json          # Wails config
└── frontend/
    └── index.html      # UI (HTML/CSS/JS)
```

## 🔧 Konfigurasi

Edit path database di `main.go`:
```go
dbPaths := []string{
    "media_library.db",
    "../website/media_library.db",
    // tambah path lain
}
```

## 🎯 Fitur

- ✅ Infinite scroll (smooth)
- ✅ Filter by platform, type, account, year
- ✅ Filter by hashtag/tag
- ✅ Search caption & account
- ✅ Click to open media
- ✅ Right-click context menu
- ✅ Lazy image loading
- ✅ Dark theme

## 📊 Perbandingan dengan Tkinter

| Aspect | Tkinter | Wails |
|--------|---------|-------|
| Scroll | Choppy | Super Smooth |
| UI | Native | Web-like |
| Size | ~50MB (PyInstaller) | ~10MB |
| Dev Speed | Fast | Medium |
| Animations | Limited | Full CSS |

## 🔨 Build untuk Distribusi

```powershell
# Build dengan UPX compression
wails build -upx

# Build tanpa console window
wails build -windowsconsole=false

# Build dengan icon custom
wails build -icon icon.ico
```

## 📝 Notes

1. WebView2 runtime biasanya sudah terinstall di Windows 10/11
2. Jika belum ada, Windows akan auto-download saat app pertama kali jalan
3. Untuk Windows 7, perlu install WebView2 runtime manual

## 🐛 Troubleshooting

### "WebView2 not found"
Install dari: https://go.microsoft.com/fwlink/p/?LinkId=2124703

### Database not found
Pastikan `media_library.db` ada di folder yang sama dengan exe atau edit path di `main.go`

### Images not loading
Cek path di database (`full_path`) apakah valid

## 🚀 Quick Start

```powershell
# 1. Clone/copy folder ini
# 2. Install deps
cd website-wails
go mod tidy

# 3. Run development
wails dev

# 4. Build exe
wails build

# 5. Copy exe ke folder dengan media_library.db
```
