# Video Compression

## Screencast to WebM (target <10 MB)

Use VP9 CRF (quality-based) mode — not fixed bitrate (ABR). Fixed bitrate at low values causes green artifacts and heavy blocking on screencasts.

```bash
ffmpeg -y \
  -i "input.webm" \
  -vf "scale=1280:-2" \
  -c:v libvpx-vp9 \
  -b:v 0 -crf 40 \
  -pix_fmt yuv420p \
  -deadline good -cpu-used 2 \
  -an \
  "output (compressed).webm"
```

- `scale=1280:-2` — scale width to 1280px, height auto (keeps aspect ratio)
- `-b:v 0 -crf 40` — pure CRF mode; adapts to static content (screencasts compress very well, ~4 MB for 5 min)
- `-pix_fmt yuv420p` — ensures broad playback compatibility
- `-an` — drop audio if there is none (avoids muxing errors)
- `-deadline good -cpu-used 2` — good quality/speed tradeoff

## Why not ABR?

Fixed bitrate (e.g. `-b:v 170k`) at low values + high resolution = green blobs and blocking artifacts. CRF lets the encoder allocate bits where needed, producing clean output at a fraction of the size.
