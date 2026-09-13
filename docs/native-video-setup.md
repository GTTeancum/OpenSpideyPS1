# Native Video Setup

Both games replace OPTIONS → Screen Adjust with Video Setup. The implementation
runs each game's original three-row OPTIONS screen, temporarily substituting its
title, row strings and help strings. Native drawing, menu animation, font,
selection highlight, up/down handling, select/cancel sounds and Triangle return
remain in the original game code.

## Bindings and memory

| Binding | SM1 | SM2 |
|---|---|---|
| Native OPTIONS | `8025AA84` | `80243854` |
| Replaced Screen Adjust | `8025D0C4` | `80246118` |
| Native list input | `800174CC` | `80018D70` |
| Input return-address gate | `8025AD18` | `80243AE8` |
| Language pointer table | `80097760` | `800A382C` |

The shared input pre-hook only handles Video Setup while that screen is active
and the caller is its OPTIONS list. It consumes Left/Right and confirm pulses
before the native list sees them. Other lists retain their original behavior.
The screen uses one tracked 864-byte guest allocation for nine 96-byte text slots;
all nine language pointers are restored and that allocation is freed on return.
The permanent English entry/help replacements are shorter than their retail
strings and are written only when the complete original strings match.

`VideoSetupState` owns pending selections. Apply changes the gameplay aspect,
requests an exact window output area, and schedules settings persistence after
the host UI frame. The output panel uses its actual available area when sizing
the window, accounting for chrome and padding. Triangle leaves applied settings
alone and discards subsequent pending selections. Saved windowed sizes are
restored at startup; an explicitly saved fullscreen setting takes precedence.

These controls select windowed output size, not internal GPU rendering scale or
exclusive monitor modes. Menus retain their authored 4:3 layout and gameplay
uses the selected aspect. Internal render scale retains its existing Display
setting and restart requirement.

## Verification

Build/publish each game sequentially, then run:

```powershell
dotnet run --project tools/RecompOne/tests/VideoSetupRegression -c Release
python dreamcast/tools/validate_video_setup_runtime.py --game sm1 --scenario wide
python dreamcast/tools/validate_video_setup_runtime.py --game sm1 --scenario minimum
python dreamcast/tools/validate_video_setup_runtime.py --game sm2 --scenario wide
python dreamcast/tools/validate_video_setup_runtime.py --game sm2 --scenario minimum
```

The native harness temporarily installs isolated settings beside the published
executable, disables memory cards, and restores the prior files afterward. Run
one game at a time. It uses the game's process-local input harness and GPU capture
path, with no OS input or desktop capture. Each scenario records the executable
hash, measured output size, native menu allocation/free counts, saved settings
checks, log and native captures under `proof_render/video-setup-final`.

The wide scenario starts at 640×480, applies 1280×720, reopens the menu, changes
aspect without applying, and verifies that reopening retains 1280×720. The
minimum scenario launches a new process with those saved settings, applies
640×480, and reopens it again. Review the native captures for title, rows, help
and restored OPTIONS layout; automated assertions do not replace visual review.
