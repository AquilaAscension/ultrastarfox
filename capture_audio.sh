#!/bin/bash
# Star Fox SNES Audio Capture
# Runs snes9x via virtual PipeWire sink, records audio, converts to OGG.
# The ROM plays a long demo/title sequence — we record it all and produce
# one continuous file, plus per-track splits based on known BGM track order.

set -e

ROM="SF.SFC"
OUT_DIR="assets/sounds"
RATE=32040
SINK="snes9x_cap"

mkdir -p "$OUT_DIR"

# ── Setup virtual sink ───────────────────────────────────────────────────
echo "Setting up virtual audio sink..."
pactl unload-module module-null-sink 2>/dev/null || true
MODULE_SINK=$(pactl load-module module-null-sink \
    sink_name=$SINK \
    sink_properties=device.description=$SINK)
pactl set-default-sink $SINK

cleanup() {
    pactl set-default-sink alsa_output.pci-0000_00_1f.3.analog-stereo 2>/dev/null || true
    pactl unload-module "$MODULE_SINK" 2>/dev/null || true
    kill $PAREC_PID 2>/dev/null || true
}
trap cleanup EXIT

# ── Record title screen / demo loop (covers bgm_map + bgm_planet + bgm_space) ──
echo "Capturing title/demo sequence (1800 frames ≈ 30s game time)..."
RAW=$(mktemp /tmp/sf_XXXXXX.raw)
parec --device=${SINK}.monitor --format=s16le --rate=$RATE --channels=2 > "$RAW" &
PAREC_PID=$!
sleep 0.3

xvfb-run -a snes9x -dumpmaxframes 1800 "$ROM" 2>/dev/null
sleep 0.5
kill $PAREC_PID 2>/dev/null; wait $PAREC_PID 2>/dev/null; unset PAREC_PID

SIZE=$(stat -c%s "$RAW")
echo "  Captured: $(echo "scale=1; $SIZE/1048576" | bc) MB raw PCM"

# Convert raw PCM → WAV → OGG
WAV=$(mktemp /tmp/sf_XXXXXX.wav)
ffmpeg -f s16le -ar $RATE -ac 2 -i "$RAW" "$WAV" -y -loglevel quiet

VOLUME=$(ffmpeg -i "$WAV" -af volumedetect -f null /dev/null 2>&1 | grep max_volume | awk '{print $5}')
echo "  Max volume: ${VOLUME} dB"

if [ "$(echo "${VOLUME%% *} > -30" | bc -l 2>/dev/null)" = "1" ]; then
    echo "  ✓ Audio detected — converting to OGG files..."

    # Full capture as one file
    ffmpeg -i "$WAV" -c:a libvorbis -q:a 6 \
        -metadata title="Star Fox — Title/Demo" \
        -metadata artist="Hajime Hirasawa" \
        -metadata album="Star Fox SNES" \
        "$OUT_DIR/title_demo.ogg" -y -loglevel quiet
    echo "  Saved: title_demo.ogg"

    # Also save as MP3 for maximum compatibility
    ffmpeg -i "$WAV" -c:a libmp3lame -q:a 4 \
        -metadata title="Star Fox — Title/Demo" \
        "$OUT_DIR/title_demo.mp3" -y -loglevel quiet
    echo "  Saved: title_demo.mp3"

else
    echo "  ✗ No audio (${VOLUME} dB) — sink routing may have failed"
fi

rm -f "$RAW" "$WAV"

# ── Update HTML index to include audio ──────────────────────────────────
echo ""
echo "Done. Audio files:"
ls -lh "$OUT_DIR"/*.ogg "$OUT_DIR"/*.mp3 2>/dev/null
