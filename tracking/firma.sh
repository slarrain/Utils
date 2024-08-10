#!/bin/bash
URL=$(python3 /home/santiago/github/Utils/tracking/create_pixel_link.py)
cat /home/santiago/github/Utils/tracking/firma.html | sed "64 s|https://url.santiagolarrain.myds.me/TPbAu|$URL|"

