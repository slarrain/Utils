#!/bin/bash
# Workspace setup: launches and positions all apps across 4 monitors
#
# Monitor layout:
#                 HDMI-0 (1920x1080 @ 1392,0) - UPPER
# DP-0.8 (2560x1440 @ 0,1080) | DP-4.8 (2560x1440 @ 2560,1080) | DVI-D-0 (1080x1920 @ 5120,846)
#          LEFT                |          CENTER (primary)         |        RIGHT (portrait)

set -euo pipefail

# Redirect stderr for launched apps to /dev/null to reduce noise
exec 2>/dev/null

# --- Dependency check ---
for cmd in wmctrl xdotool; do
    if ! command -v "$cmd" &>/dev/null; then
        echo "ERROR: $cmd is not installed. Run: sudo apt install wmctrl xdotool" >&1
        exit 1
    fi
done

# --- Helper functions ---

# Get list of window IDs matching a WM_CLASS substring (case-insensitive)
get_window_ids() {
    local class="$1"
    wmctrl -l -x 2>/dev/null | awk -v c="$class" 'tolower($3) ~ tolower(c) {print $1}'
}

# Wait for a window matching WM_CLASS substring via wmctrl polling
wait_for_window() {
    local pattern="$1"
    local timeout="${2:-30}"
    local deadline=$((SECONDS + timeout))

    while [[ $SECONDS -lt $deadline ]]; do
        local wid
        wid=$(get_window_ids "$pattern" | head -1)
        if [[ -n "$wid" ]]; then
            echo "$wid"
            return 0
        fi
        sleep 0.5
    done

    echo "WARN: Timed out waiting for window matching '$pattern'" >&1
    return 1
}

# Wait for a NEW window matching class that wasn't in the known set
wait_for_new_window() {
    local pattern="$1"
    local known="$2"
    local timeout="${3:-30}"
    local deadline=$((SECONDS + timeout))

    while [[ $SECONDS -lt $deadline ]]; do
        local current_ids
        current_ids=$(get_window_ids "$pattern")
        for id in $current_ids; do
            if [[ ! "$known" =~ $id ]]; then
                echo "$id"
                return 0
            fi
        done
        sleep 0.5
    done

    echo "WARN: Timed out waiting for new '$pattern' window" >&1
    return 1
}

# Position a window using xdotool with minimize/activate trick
# This approach works reliably for all window types (CSD and SSD)
# Usage: place_window <hex_window_id> <x> <y> <w> <h>
place_window() {
    local wid="$1" x="$2" y="$3" w="$4" h="$5"
    local xid
    xid=$(printf "%d" "$wid")
    wmctrl -i -r "$wid" -b remove,maximized_vert,maximized_horz 2>/dev/null
    sleep 0.1
    xdotool windowminimize "$xid" 2>/dev/null; sleep 0.2
    xdotool windowactivate "$xid" 2>/dev/null; sleep 0.2
    xdotool windowsize "$xid" "$w" "$h" 2>/dev/null; sleep 0.2
    xdotool windowmove "$xid" "$x" "$y" 2>/dev/null
}

# Position a CSD window, compensating for invisible shadow borders
# so the visible area fills exactly the target rectangle
# Usage: place_window_csd <hex_window_id> <x> <y> <w> <h>
place_window_csd() {
    local wid="$1" x="$2" y="$3" w="$4" h="$5"
    local xid
    xid=$(printf "%d" "$wid")
    local extents
    extents=$(xprop -id "$wid" _GTK_FRAME_EXTENTS 2>/dev/null | grep -oP '= \K.*')
    local left right top bottom
    IFS=', ' read -r left right top bottom <<< "$extents"
    left=${left:-0}; right=${right:-0}; top=${top:-0}; bottom=${bottom:-0}

    wmctrl -i -r "$wid" -b remove,maximized_vert,maximized_horz 2>/dev/null
    sleep 0.1
    xdotool windowminimize "$xid" 2>/dev/null; sleep 0.2
    xdotool windowactivate "$xid" 2>/dev/null; sleep 0.2
    xdotool windowsize "$xid" $((w + left + right)) $((h + top + bottom)) 2>/dev/null; sleep 0.2
    xdotool windowmove "$xid" $((x - left)) $((y - top)) 2>/dev/null
}

# Maximize a window on a specific screen
maximize_window() {
    local wid="$1" x="$2" y="$3"
    local xid
    xid=$(printf "%d" "$wid")
    wmctrl -i -r "$wid" -b remove,maximized_vert,maximized_horz 2>/dev/null
    sleep 0.1
    xdotool windowmove "$xid" "$x" "$y" 2>/dev/null; sleep 0.2
    wmctrl -i -r "$wid" -b add,maximized_vert,maximized_horz 2>/dev/null
}

# --- Snapshot Chrome windows before launches ---
chrome_ids_before_right=$(get_window_ids "google-chrome")

# --- Launch apps ---

# LEFT screen: Evolution + Firefox
flatpak run org.gnome.Evolution &
firefox \
    "http://192.168.1.200:8888/" \
    "https://console.cloud.google.com/billing/019BEF-B7278C-58A38B/reports?project=gen-lang-client-0865353638" \
    "https://github.com/slarrain/titularia" \
    "https://supabase.com/dashboard/project/zypldbjwbkccwfqlatgl" \
    "https://www.poderalia.cl/" \
    "https://mail.google.com/mail/u/0/" &

# CENTER screen: Kitty with 4 tabs
kitty --class kitty-center --session ~/.config/kitty/sessions/center.conf &

# RIGHT screen: Chrome (Grafana clientes) + ZapZap
google-chrome --new-window \
  "http://192.168.1.200:3010/d/bf0xx4tnpz9j4b/clientes?kiosk=&from=now%2Fd&to=now%2Fd&timezone=browser&refresh=15m" \
  "http://192.168.1.200:3010/d/aeu44bmnzka9sf/poderrores?from=now%2Fd&to=now%2Fd&timezone=browser" \
  "http://192.168.1.200:3010/d/cfetf9a9mheyoc/twenty-crm-sales-pipeline?from=2026-03-01&to=now&timezone=browser" \
  "http://192.168.1.200:3010/d/af0z1amax3abkf/bigpicture?from=now-6M&to=now&timezone=browser" &
flatpak run com.rtosta.zapzap &

# Wait for Chrome clientes window to register before launching more
sleep 3

# UPPER screen: Kitty (spod) + Telegram + Chrome (Grafana podsimple) + Kitty (th)
kitty --class kitty-spod --session ~/.config/kitty/sessions/upper-left.conf &
flatpak run org.telegram.desktop &
google-chrome --app="http://192.168.1.200:3010/d/eeu14w7d7cuf4d/podsimple" &
kitty --class kitty-th --session ~/.config/kitty/sessions/upper-right-bottom.conf &

# --- Position windows in parallel ---
pids=()

# LEFT: Evolution (left half, CSD shadow compensation)
(
    wid=$(wait_for_window "org.gnome.Evolution" 30) && place_window_csd "$wid" 0 1080 1280 1440
) &
pids+=($!)

# LEFT: Firefox (right half, CSD shadow compensation)
(
    wid=$(wait_for_window "firefox_firefox" 30) && place_window_csd "$wid" 1280 1080 1280 1440
) &
pids+=($!)

# CENTER: Kitty (maximized)
(
    wid=$(wait_for_window "kitty-center" 30) && maximize_window "$wid" 2560 1080
) &
pids+=($!)

# RIGHT: Chrome Grafana clientes (top half, CSD shadow compensation)
(
    wid=$(wait_for_new_window "google-chrome" "$chrome_ids_before_right" 30) && place_window_csd "$wid" 5120 846 1080 960
) &
pids+=($!)

# RIGHT: ZapZap (bottom half)
(
    wid=$(wait_for_window "zapzap" 30) && place_window "$wid" 5120 1806 1080 960
) &
pids+=($!)

# UPPER: Kitty spod (left 72%, adjusted for Chrome min width 544)
(
    wid=$(wait_for_window "kitty-spod" 30) && place_window "$wid" 1392 0 1376 1080
) &
pids+=($!)

# UPPER: Telegram (top-right)
(
    wid=$(wait_for_window "TelegramDesktop" 30) && place_window "$wid" 2768 0 544 560
) &
pids+=($!)

# UPPER: Chrome Grafana podsimple (mid-right, app mode)
(
    wid=$(wait_for_window "podsimple" 30) && place_window "$wid" 2768 560 544 284
) &
pids+=($!)

# UPPER: Kitty th (bottom-right)
(
    wid=$(wait_for_window "kitty-th" 30) && place_window "$wid" 2768 844 544 236
) &
pids+=($!)

# Wait only for positioning subshells (not the launched apps)
for pid in "${pids[@]}"; do
    wait "$pid" 2>/dev/null
done

echo "Workspace ready!" >&1
