#!/bin/sh
set -eu

output_path="$1"
width=1920
height=1080
center_x=$((width / 2))
icon_top=330

magick -size "${width}x${height}" xc:'#1b1c1f' \
    -fill none -stroke '#5f6368' -strokewidth 6 \
    -draw "roundrectangle $((center_x - 90)),${icon_top} $((center_x + 90)),$((icon_top + 120)) 14,14" \
    -draw "line ${center_x},$((icon_top + 120)) ${center_x},$((icon_top + 150))" \
    -draw "line $((center_x - 45)),$((icon_top + 152)) $((center_x + 45)),$((icon_top + 152))" \
    -stroke none -fill '#e8eaed' -font Inter-SemiBold -pointsize 46 -gravity north \
    -annotate +0+$((icon_top + 210)) 'The sandbox browser is closed' \
    -fill '#9aa0a6' -font Inter-Regular -pointsize 27 -interline-spacing 12 \
    -annotate +0+$((icon_top + 290)) 'Chrome appears here when the agent opens a page with playwright-cli.\nAsk the agent to open what you need. This view updates on its own.' \
    -alpha off -strip "PNG24:${output_path}"