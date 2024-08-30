#!/bin/bash

# Launch applications
app1="flatpak run org.gnome.Evolution"
app2="firefox --new-window http://192.168.1.200:8888"
app3="flatpak run org.telegram.desktop"
app4="kitty"
app5="flatpak run com.rtosta.zapzap"
app6="firefox --new-window http://192.168.1.200:3010/d/b9040f97-9804-41e9-8573-d614c920fec3/visitas-shlink"
app7="slack"
app8="kitty --title TASKWARRIOR"


# Start the applications in the background
$app2 &
#sleep 2
#wmctrl -r "Firefox" -e 0,5120,2224,2560,1408

$app1 &
$app3 &
$app4 &
$app5 &
$app6 &
$app7 &

# Wait for a short period to ensure the applications launch
sleep 5

# Kitty No task
wmctrl -r "santiago@TheBeast:~" -e 0,1290,1162,1280,1403

## Firefox principal
#wmctrl -r "Heimdall" -e 0,5120,2224,2560,1408

##ZapZap
#wmctrl -r "ZapZap" -e 0,5130,2122,1080,923

## Telegram
#wmctrl -r "Telegram" -e 0,10222,2144,1098,978

## Slack
#wmctrl -r "Slack" -e 0,5130,1162,1080,923

##Firefox dashboards
wmctrl -r "Grafana" -e 0,3066,0,1920,1080

#Evolution
wmctrl -r "Mail" -e 0,-40,2120,1320,1480

## Kitty taskwarrior
$app8 &
sleep 1

wmctrl -r "TASKWARRIOR" -e 0,2620,1244,792,417
