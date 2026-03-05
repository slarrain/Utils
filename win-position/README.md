# Workspace Setup Automation

A single script that launches and positions the full work environment across 4 monitors in ~6 seconds.

**Trigger:** `Super+Shift+W` keyboard shortcut or run `~/github/Utils/win-position/win-position.sh`

## Monitor Layout

```
                    HDMI-0 (1920x1080 @ 1392,0) - UPPER
DP-0.8 (2560x1440 @ 0,1080)  |  DP-4.8 (2560x1440 @ 2560,1080)  |  DVI-D-0 (1080x1920 @ 5120,846)
         LEFT                 |           CENTER (primary)          |         RIGHT (portrait)
```

## Dependencies

```bash
sudo apt install wmctrl xdotool imagemagick  # imagemagick optional, for screenshots
```

## Files

| File | Purpose |
|------|---------|
| `~/github/Utils/win-position/win-position.sh` | Main launcher script |
| `~/.config/kitty/sessions/center.conf` | Kitty session: 4 tabs (code, venv, claude, crmai) |
| `~/.config/kitty/sessions/upper-left.conf` | Kitty session: SSH to poderalia-gc-01 |
| `~/.config/kitty/sessions/upper-right-bottom.conf` | Kitty session: taskwarrior due today |
| `~/.config/kitty/zsh-venv/.zshrc` | Custom zshrc that sources the real `.zshrc` then activates the Python venv |

## Window Layout

### LEFT Screen (DP-0.8: 2560x1440 @ 0,1080) - 50/50 split

| App | Position | Size | Notes |
|-----|----------|------|-------|
| Evolution (flatpak) | 0, 1080 | 1280x1440 | CSD shadow compensation |
| Firefox (6 tabs) | 1280, 1080 | 1280x1440 | CSD shadow compensation |

**Firefox tabs:**
1. `http://192.168.1.200:8888/` (Heimdall)
2. Google Cloud Billing console
3. GitHub titularia repo
4. Supabase dashboard
5. poderalia.cl
6. Gmail

### CENTER Screen (DP-4.8: 2560x1440 @ 2560,1080) - Fullscreen

| App | Action | Notes |
|-----|--------|-------|
| Kitty (`kitty-center`) | Maximized | 4 tabs: code, venv, claude, crmai |

**Kitty center tabs:**
- **code**: `~/github/titularia/extraccion_texto` - plain zsh
- **venv**: same dir - zsh with Python virtualenv activated (uses `ZDOTDIR` trick)
- **claude**: same dir - launches `claude` CLI (falls back to shell if session conflict)
- **crmai**: `~/github/crmai` - plain zsh

### RIGHT Screen (DVI-D-0: 1080x1920 @ 5120,846) - Top/bottom split

| App | Position | Size | Notes |
|-----|----------|------|-------|
| Chrome (Grafana clientes) | 5120, 846 | 1080x960 | CSD shadow compensation |
| ZapZap (WhatsApp, flatpak) | 5120, 1806 | 1080x960 | `place_window` (no compensation) |

### UPPER Screen (HDMI-0: 1920x1080 @ 1392,0) - 72%/28% split

| App | Position | Size | Notes |
|-----|----------|------|-------|
| Kitty (`kitty-spod`) | 1392, 0 | 1376x1080 | SSH to poderalia-gc-01 |
| Telegram (flatpak) | 2768, 0 | 544x560 | Top-right |
| Chrome (Grafana podsimple) | 2768, 560 | 544x284 | Mid-right, `--app` mode (no URL bar) |
| Kitty (`kitty-th`) | 2768, 844 | 544x236 | Bottom-right, taskwarrior |

## How It Works

### Window Detection

Windows are detected by polling `wmctrl -l -x` for WM_CLASS substrings:

| App | WM_CLASS pattern |
|-----|-----------------|
| Evolution | `org.gnome.Evolution` |
| Firefox (snap) | `firefox_firefox` |
| Kitty instances | `kitty-center`, `kitty-spod`, `kitty-th` (via `--class` flag) |
| Chrome (regular) | `google-chrome` |
| Chrome (app mode) | `podsimple` (URL embedded in class) |
| ZapZap | `zapzap` |
| Telegram | `TelegramDesktop` |

For Chrome, since all regular Chrome windows share the same `WM_CLASS`, the script snapshots existing Chrome window IDs before launching a new one and uses `wait_for_new_window` to find the newly created window by diffing.

Chrome podsimple uses `--app=URL` mode which gets a unique WM_CLASS containing the URL, so it uses `wait_for_window` directly.

### Window Positioning

Two positioning functions handle different window types:

#### `place_window` (standard)
Uses the **minimize/activate trick**: minimize the window, reactivate it, then set size and position with `xdotool`. This breaks any GNOME snapping/tiling behavior and works reliably for both CSD and SSD windows.

```
xdotool windowminimize → windowactivate → windowsize → windowmove
```

#### `place_window_csd` (CSD shadow compensation)
For GTK apps with client-side decorations (Evolution, Firefox, Chrome), invisible shadow borders (`_GTK_FRAME_EXTENTS`) cause visible gaps. This function reads the shadow extents and oversizes the window to compensate:

```
Actual position: (x - shadow_left, y - shadow_top)
Actual size: (w + shadow_left + shadow_right, h + shadow_top + shadow_bottom)
```

Typical `_GTK_FRAME_EXTENTS` values:
- Evolution: `26, 26, 23, 29`
- Firefox: `26, 26, 23, 29`
- Chrome: `22, 22, 19, 25`

#### `maximize_window`
Moves the window to the target screen coordinates, then applies `wmctrl -b add,maximized_vert,maximized_horz`.

### Script Execution Flow

1. Check dependencies (`wmctrl`, `xdotool`)
2. Snapshot existing Chrome window IDs
3. Launch all apps in background (`&`)
4. `sleep 3` to let Chrome register its first window
5. Launch remaining apps
6. Start 9 parallel positioning subshells, each:
   - Polls `wmctrl` every 0.5s until the target window appears (30s timeout)
   - Positions the window using the appropriate function
7. `wait` for only the positioning PIDs (not the app processes)
8. Print "Workspace ready!"

Total runtime: ~6 seconds.

### Virtualenv Activation (ZDOTDIR trick)

The venv tab needs `source .venv/bin/activate` to run **after** `.zshrc` (so oh-my-zsh is loaded and the `(.venv)` prompt prefix persists). This is achieved with:

1. `~/.config/kitty/zsh-venv/.zshrc` contains:
   ```bash
   source ~/.zshrc
   source ~/github/titularia/.venv/bin/activate
   cd ~/github/titularia/extraccion_texto
   ```
2. The kitty session launches: `env ZDOTDIR=~/.config/kitty/zsh-venv zsh -i`
3. zsh reads `.zshrc` from `ZDOTDIR` instead of `$HOME`, which sources the real `.zshrc` first, then activates the venv.

This ensures `(.venv)` appears in the prompt because `activate` modifies `PROMPT` after oh-my-zsh has set it up.

## Keyboard Shortcut

Bound via GNOME custom keybindings:

```bash
gsettings set org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/custom0/ name "Workspace Setup"
gsettings set org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/custom0/ command "/home/santiago/github/Utils/win-position/win-position.sh"
gsettings set org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/custom0/ binding "<Super><Shift>w"
```

## Re-run Behavior

Running the script when apps are already open will launch duplicate instances. Close existing windows first for a clean setup.

## Troubleshooting

### Finding WM_CLASS for a window
```bash
wmctrl -l -x    # lists all windows with WM_CLASS
xprop WM_CLASS  # click on a window to see its class
```

### Checking frame extents (for CSD/SSD debugging)
```bash
xprop -id <window_id> _GTK_FRAME_EXTENTS    # CSD shadows
xprop -id <window_id> _NET_FRAME_EXTENTS    # SSD titlebar
```

### Taking screenshots for debugging
```bash
import -window root /tmp/full.png                          # all monitors
import -window root -crop 2560x1440+0+1080 /tmp/left.png  # specific screen
```

### Key lessons learned
- **`xdotool` > `wmctrl -e`** for positioning — `wmctrl -e` is unreliable with GNOME/Mutter
- **Minimize/activate trick** breaks GNOME snapping and allows precise positioning
- **CSD shadows** (`_GTK_FRAME_EXTENTS`) cause visible gaps; must oversize to compensate
- **SSD windows** (app-mode Chrome, ZapZap) have GNOME-added titlebars; `place_window` handles them fine without compensation
- **Firefox snap** splits tabs into separate windows with `--new-window`; omit the flag to keep all tabs in one window
- **Chrome minimum width** is 544px; the UPPER right column was widened from 461px to accommodate this
- **`wait`** at script end waits for ALL child processes including apps; track positioning PIDs explicitly
- **`env` is not a valid kitty session directive**; use `launch env KEY=VALUE command` instead
