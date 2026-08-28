using System;
using RecompOne.Runtime.Events;
using RecompOne.Runtime.Memory;

namespace Recompiled;

/// <summary>
/// The game's own cheat flags, set directly instead of typed in.
///
/// Spider-Man keeps a table of 23 cheat codes at 0x800A55D0 -- pairs of the string the
/// player types and the effect it has -- and 0x8006F540 dispatches an index through a
/// jump table at 0x80095B34 to a handler that flips one flag. The handlers are small
/// enough to read off completely, so nothing here calls into game code or re-enters the
/// recompiled dispatcher: it writes exactly the words the game's own handlers write.
///
/// This exists to make the port testable. Reaching level 6 legitimately means playing
/// five levels of a 3D action game, which a timed button script cannot do; with the
/// level select unlocked, every level can be loaded and checked directly. It is off
/// unless SPIDEY_CHEATS asks for it.
///
///     SPIDEY_CHEATS=everything,levelselect,invuln,webbing,debug
///     SPIDEY_CHEATS=all
///
/// The flags are re-asserted every frame rather than set once. The unlock block is the
/// same memory the memory card save is built from, so loading a save -- or the game
/// clearing it during a transition -- would otherwise quietly drop them again.
/// </summary>
public static class Cheats
{
    // The block 0x8006D180 ("everything") fills in. It is the saved-progress structure:
    // five words of unlock bits, plus two bytes for the gallery viewers.
    const uint Unlocks = 0x800A5688;

    const uint LevelSelectFlag  = 0x800B4F80;   // handler 16, XCLSIOR
    const uint InvulnFlag       = 0x800B4F6C;   // handler 21, RUSTCRST
    const uint WebbingFlag      = 0x800B4F98;   // handler  3, STRUDL
    const uint DebugFlag        = 0x800B4F8C;   // handler  2, LLADNEK
    const uint BigHeadFlag      = 0x800B4FA4;   // handler  4, DULUX
    const uint WhatIfFlag       = 0x800B4F5C;   // handler 20, GBHSRSPM
    const uint CharViewer       = 0x800A570C;   // handler 19, CVIEW EM
    const uint MovieViewer      = 0x800A5710;   // handler 18, WATCH EM
    const uint ComicCollection  = 0x800A5714;   // handler 17, CMC BUFF
    const uint ComicCovers      = 0x800A5718;   // handler 15, ALLSIXCC

    static bool _everything, _levelSelect, _invuln, _webbing, _debug, _bigHead, _viewers;
    public static bool Any { get; private set; }

    public static void Install()
    {
        var spec = Environment.GetEnvironmentVariable("SPIDEY_CHEATS");
        if (string.IsNullOrWhiteSpace(spec)) return;

        foreach (var raw in spec.Split(',', StringSplitOptions.RemoveEmptyEntries))
        {
            switch (raw.Trim().ToLowerInvariant())
            {
                case "all":          _everything = _levelSelect = _invuln = _webbing =
                                     _viewers = true; break;
                case "everything":   _everything = true; break;
                case "levelselect":  _levelSelect = true; break;
                case "invuln":
                case "invulnerable": _invuln = true; break;
                case "webbing":      _webbing = true; break;
                case "debug":        _debug = true; break;
                case "bighead":      _bigHead = true; break;
                case "viewers":      _viewers = true; break;
                default:
                    Console.Error.WriteLine($"[cheats] unknown '{raw.Trim()}'");
                    break;
            }
        }

        Any = _everything || _levelSelect || _invuln || _webbing || _debug || _bigHead || _viewers;
        if (!Any) return;

        Event.AddListener<VSyncEvent>(e => Apply(e.Memory));
        Console.WriteLine($"[cheats] {spec}");
    }

    static void Apply(IMemory m)
    {
        if (m == null) return;

        if (_everything)
        {
            // 0x8006D180 verbatim: five words of unlock bits all set, the two gallery
            // bytes, and the level select alongside them.
            for (uint o = 0x80; o <= 0x90; o += 4) m.WriteU32(Unlocks + o, 0xFFFFFFFFu);
            m.WriteU8(Unlocks + 0x78, 1);
            m.WriteU8(Unlocks + 0x55, 1);
            m.WriteU32(LevelSelectFlag, 1);
        }

        if (_levelSelect) m.WriteU32(LevelSelectFlag, 1);
        if (_invuln)      m.WriteU32(InvulnFlag, 1);
        if (_webbing)     m.WriteU32(WebbingFlag, 1);
        if (_debug)       m.WriteU32(DebugFlag, 1);
        if (_bigHead)     m.WriteU32(BigHeadFlag, 1);

        if (_viewers)
        {
            m.WriteU32(CharViewer, 0xFFFFFFFFu);
            m.WriteU32(MovieViewer, 0xFFFFFFFFu);
            m.WriteU32(ComicCollection, 0xFFFFFFFFu);
            m.WriteU32(ComicCovers, 63);
            m.WriteU32(WhatIfFlag, 1);
        }
    }
}
