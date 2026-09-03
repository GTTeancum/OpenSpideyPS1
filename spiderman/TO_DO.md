# Spider-Man port — open work

## Abbreviated list

1. Embed a first-run BIN/CUE extractor in each game executable with exact-disc validation, an in-window progress UI, and no dependency on supplemental discs for bundled mod content.

## 1. Embedded first-run disc extraction

- Each game executable must detect a missing loose-file installation on first launch and ask for that game's exact BIN/CUE revision by both disc ID and common title/version name.
- Validate the selected image before extracting every runtime file needed by the game; the extractor must be part of the game executable rather than a separate command-line helper.
- Keep the entire flow inside the game's own window with no command-prompt window, showing elapsed time and a progress bar that advances throughout extraction.
- Ship modded content with the executable, so SM1 never requests a Dreamcast or SM2 disc for Dreamcast conversions or future SM2 suits, and SM2 likewise needs no supplemental source disc for bundled mods.
