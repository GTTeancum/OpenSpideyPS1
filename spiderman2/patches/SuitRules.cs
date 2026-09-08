using System.Collections.Generic;

namespace Recompiled;

/// <summary>SM2-owned profile and material allowlists; never supplied by a mod.</summary>
public static class SuitRules
{
    public static readonly string[] Profiles =
    ["spiderman", "spider-phoenix", "prodigy", "dusk", "insulated", "alex-ross-red",
     "alex-ross-white", "venom-earth-x", "negative-zone", "symbiote", "2099",
     "captain-universe", "unlimited", "bagman", "scarlet", "ben-reilly",
     "quick-change", "peter-parker", "battle-damaged"];

    public static readonly string[][] PowerText =
    [
        ["SUPER STRENGTH", "SUPER AGILITY", "STICK TO WALLS", "SPIDER SENSE"],
        ["INVULNERABILITY", "ENHANCED STRENGTH", "ENHANCED WEB SWING"],
        ["DOUBLE JUMP", "ENHANCED STRENGTH", "ENHANCED WEB SWING"],
        ["STEALTH"], ["ENHANCED STRENGTH"], ["DOUBLE JUMP"], ["ENHANCED WEB SWING"],
        ["UNLIMITED WEBBING", "ENHANCED STRENGTH"], ["NONE"], ["UNLIMITED WEBBING"],
        ["ENHANCED STRENGTH"], ["INVULNERABLE", "ENHANCED STRENGTH", "UNLIMITED WEBBING"],
        ["STEALTH MODE"], ["NO SPIDEY BELT"], ["NONE"], ["NONE"],
        ["NO SPIDEY BELT"], ["NO SPIDEY BELT"], ["NONE"]
    ];

    // Exact three power IDs written by retail shell:80249280 (jump table 80250340).
    // ID 1..7 maps to the seven booleans at 800C2210..800C2228 in 80249168.
    public static readonly byte[][] PowerIds =
    [[0,0,0], [4,6,2], [4,5,6], [1,0,0], [4,0,0], [5,0,0], [6,0,0],
     [4,3,0], [0,0,0], [3,0,0], [4,0,0], [4,3,2], [1,0,0], [7,0,0],
     [0,0,0], [0,0,0], [7,0,0], [7,0,0], [0,0,0]];

    public static readonly IReadOnlyDictionary<string, IReadOnlySet<uint>> Models =
        RecompOne.Runtime.Assets.Suits.SuitManifest.PlayerModels;
}
