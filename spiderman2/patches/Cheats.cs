using System;
using RecompOne.Runtime.Events;
using RecompOne.Runtime.Memory;

namespace Recompiled;

/// <summary>
/// The game's own cheat flags, set directly instead of typed in.
///
/// Spider-Man 2 keeps a table of ten codes at 0x800B3130 -- pairs of the string the
/// player types and the label shown for it -- and 0x8007A94C walks it comparing what was
/// typed, then hands the matched index to 0x8007A750, which dispatches through the jump
/// table at 0x800A1E58 to a handler. Every handler is a handful of stores, so they were
/// read off completely and are reproduced here: nothing below calls into game code or
/// re-enters the recompiled dispatcher, it writes exactly the words the game's own
/// handlers write.
///
/// | code     | label           | handler    |
/// |----------|-----------------|------------|
/// | DRILHERE | Debug Mode      | 0x8007A788 |
/// | AUNTMAY  | Everything      | 0x8007A7A8 |
/// | VVHISCRS | VV High Scores  | 0x8007A7B8 |
/// | STACEYD  | Big Feet        | 0x8007A864 |
/// | VVISIONS | What If         | 0x8007A884 |
/// | WASHMCHN | Unlock Costumes | 0x8007A8A4 |
/// | DRKROOM  | Unlock Gallery  | 0x8007A8BC |
/// | NONJYMNT | Unlock Levels   | 0x8007A8E8 |
/// | CEREBRA  | Unlock Training | 0x8007A8FC |
/// | ALIEN    | Big Head        | 0x8007A914 |
///
/// This exists to make the port testable, the same way it does in the Spider-Man port:
/// a timed button script cannot play a 3D action level to its end, so reaching a later
/// level legitimately is not something verification can do. With the levels unlocked
/// they can be loaded and checked directly. Off unless SPIDEY_CHEATS asks for it.
///
///     SPIDEY_CHEATS=everything,levels,costumes,gallery,training,debug,bigfeet,bighead,whatif
///     SPIDEY_CHEATS=all
///
/// The flags are re-asserted every frame rather than set once, because this block is the
/// same memory the saved game is built from -- loading a save, or the game clearing it
/// during a transition, would otherwise quietly drop them again.
///
/// VV High Scores is deliberately not offered: its handler copies 352 bytes over the
/// high-score table, which is a destructive write to saved data and nothing here needs
/// it. Its address is recorded above for completeness.
/// </summary>
public static class Cheats
{
    /// <summary>
    /// The unlock block, immediately after the ten-entry code table. Every "unlock"
    /// handler is an offset from here.
    /// </summary>
    const uint Unlocks = 0x800B3180;

    const uint DebugFlag       = 0x800C1FE0;   // DRILHERE, toggled
    const uint BigFeetFlag     = 0x800C1FEC;   // STACEYD,  toggled
    const uint WhatIfFlag      = 0x800C1FB8;   // VVISIONS, xor 1
    const uint BigHeadFlag     = 0x800C1FE4;   // ALIEN,    toggled
    const uint LevelSelectFlag = 0x800C1FD8;   // NONJYMNT, set to 1

    static bool _everything, _levels, _costumes, _gallery, _training,
                _debug, _bigFeet, _bigHead, _whatIf;
    public static bool Any { get; private set; }

    public static void Install()
    {
        var spec = Environment.GetEnvironmentVariable("SPIDEY_CHEATS");
        if (string.IsNullOrWhiteSpace(spec)) return;

        foreach (var raw in spec.Split(',', StringSplitOptions.RemoveEmptyEntries))
        {
            switch (raw.Trim().ToLowerInvariant())
            {
                case "all":         _everything = _levels = _costumes = _gallery =
                                    _training = true; break;
                case "everything":  _everything = true; break;
                case "levels":
                case "levelselect": _levels = true; break;
                case "costumes":    _costumes = true; break;
                case "gallery":     _gallery = true; break;
                case "training":    _training = true; break;
                case "debug":       _debug = true; break;
                case "bigfeet":     _bigFeet = true; break;
                case "bighead":     _bigHead = true; break;
                case "whatif":      _whatIf = true; break;
                default:
                    Console.Error.WriteLine($"[cheats] unknown '{raw.Trim()}'");
                    break;
            }
        }

        Any = _everything || _levels || _costumes || _gallery || _training ||
              _debug || _bigFeet || _bigHead || _whatIf;
        if (!Any) return;

        Event.AddListener<VSyncEvent>(e => Apply(e.Memory));
        Console.WriteLine($"[cheats] {spec}");
    }

    static void Apply(IMemory m)
    {
        if (m == null) return;

        if (_everything)
        {
            // 0x800786E4 verbatim: seven words of unlock bits, the two gallery bytes,
            // three single-byte flags, and the level select alongside them.
            for (uint o = 0x78; o <= 0x90; o += 4) m.WriteU32(Unlocks + o, 0xFFFFFFFFu);
            m.WriteU8(Unlocks + 0xAC, 0xFF);
            m.WriteU8(Unlocks + 0xAD, 0xFF);
            m.WriteU8(Unlocks + 0x6E, 1);
            m.WriteU8(Unlocks + 0x55, 1);
            m.WriteU8(Unlocks + 0x94, 1);
            m.WriteU32(LevelSelectFlag, 1);
        }

        // 0x8007A8A4
        if (_costumes)
        {
            m.WriteU32(Unlocks + 0x78, 0xFFFFFFFFu);
            m.WriteU32(Unlocks + 0x90, 0xFFFFFFFFu);
        }

        // 0x8007A8BC
        if (_gallery)
        {
            m.WriteU32(Unlocks + 0x7C, 0xFFFFFFFFu);
            m.WriteU32(Unlocks + 0x80, 0xFFFFFFFFu);
            m.WriteU32(Unlocks + 0x84, 0xFFFFFFFFu);
            m.WriteU32(Unlocks + 0x88, 0xFFFFFFFFu);
            m.WriteU32(Unlocks + 0x8C, 0xFFFFFFFFu);
            m.WriteU8(Unlocks + 0x55, 1);
        }

        // 0x8007A8FC
        if (_training)
        {
            m.WriteU8(Unlocks + 0xAC, 0xFF);
            m.WriteU8(Unlocks + 0xAD, 0xFF);
        }

        if (_levels)  m.WriteU32(LevelSelectFlag, 1);

        // The four toggles. Their handlers flip a flag, so holding them at 1 every frame
        // is the "on" state rather than the flip.
        if (_debug)   m.WriteU32(DebugFlag, 1);
        if (_bigFeet) m.WriteU32(BigFeetFlag, 1);
        if (_bigHead) m.WriteU32(BigHeadFlag, 1);
        if (_whatIf)  m.WriteU32(WhatIfFlag, 1);
    }
}
