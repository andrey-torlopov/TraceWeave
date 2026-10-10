# Synthetic E4 media

Every byte was generated locally from solid colours, FFmpeg's procedural test
pattern, a 440 Hz sine wave, or the literal synthetic text in `generate.py`.
No recordings, user documents, external images, downloaded samples or secrets.

Regenerate from the delivery repository with
`python3 tests/fixtures/media/generate.py`. Existing `ffmpeg` and `ffprobe` on
PATH are required; explicit paths use TW_FIXTURE_FFMPEG/TW_FIXTURE_FFPROBE.
The generator performs no network access or tool installation.
The generator checks each media container with ffprobe and writes exact sizes,
SHA-256 and codec/dimension metadata to `manifest.json`. Encodings can differ
between ffmpeg releases; regenerate the manifest together with the fixtures.

`unsupported-prores.mov` is a valid QuickTime container with a ProRes video
stream. The backend must preserve it; the Chromium test requires the native
decoder to report unsupported playback and the application to offer download.
This does not generalise Chromium's codec support to Safari or other browsers.

`preview-limit.png` is a fully formed compressed RGB image: 8000 × 4001 =
32,008,000 pixels, above the 32,000,000 automatic-preview limit. Browser tests
must not decode it automatically. It is not a malformed header-only image.
