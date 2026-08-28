using System;
using System.Text;
using RecompOne.Runtime.Events;
using RecompOne.Runtime.Memory;

namespace Recompiled;

/// <summary>
/// Fills in models that an earlier act would have loaded.
///
/// Resources persist across the acts of a level, so an act's trigger list only asks for
/// what is not already resident. Level 5 is the clear case: act 2 loads the `venom`
/// model and act 3 relies on it still being there, listing only `venom2`. Starting
/// directly in act 3 -- which is the entire point of SPIDEY_LEVEL -- therefore leaves
/// `venom` missing.
///
/// The game does not survive that. Its name lookup (0x800694B8) returns -1, and the
/// caller at 0x8005904C stores that as a *byte*, so -1 becomes 0xFF and it indexes
/// record 255 of a 40-record table. That lands 16 KB past the end, in static data full
/// of 0xFF, and the pointer it reads out is 0xFFFFFFFF. On real hardware the same code
/// would take an address error, so this path is never reached in normal play -- the
/// model is simply always there.
///
/// So rather than let the lookup fail, the closest resident variant is registered under
/// the missing name: `venom2` answers for `venom`, and the other way round. The model is
/// not always the exact one the act would have had, but the actor spawns and the level
/// runs, which is what jumping straight to a level is for.
///
/// DOES NOT WORK, and is off unless SPIDEY_ALIAS=1 asks for it. Copying the record
/// wholesale duplicates pointers the game owns, and two table entries referring to one
/// model corrupts the level far more thoroughly than the missing model did: with this
/// on, the clean 0xFFFFFFFF fault turns into wild addresses, and levels that were fine
/// start failing too. Kept only as a record of a dead end -- the fix belongs on the
/// lookup at 0x800694B8, where a failure can be answered without touching the table.
/// </summary>
public static class ModelAlias
{
    const uint Table = 0x800A0904;   // 40 records of 64 bytes, name at +0 (8 chars + NUL)
    const int Records = 40, Stride = 64, MaxName = 8;

    static bool _on;
    public static int Added { get; private set; }

    public static void Install()
    {
        _on = Environment.GetEnvironmentVariable("SPIDEY_ALIAS") == "1";
        if (_on) Event.AddListener<VSyncEvent>(e => Sweep(e.Memory));
    }

    static string NameAt(IMemory m, int i)
    {
        var sb = new StringBuilder();
        for (uint k = 0; k < MaxName; k++)
        {
            byte b = m.ReadU8(Table + (uint)(i * Stride) + k);
            if (b == 0) break;
            sb.Append((char)b);
        }
        return sb.ToString();
    }

    /// <summary>venom2 -> venom, venom -> venom2. The pairing the game's own data uses.</summary>
    static string Counterpart(string name)
    {
        if (name.Length > 1 && char.IsDigit(name[^1])) return name.TrimEnd('0','1','2','3','4','5','6','7','8','9');
        return name.Length + 1 <= MaxName ? name + "2" : null;
    }

    static void Sweep(IMemory m)
    {
        if (!_on || m == null) return;

        // Free slots are taken from the top. The game fills this table from the bottom
        // as a level's resources load, so an alias placed at the first free slot steals
        // the one the next real model was going to use -- which corrupts the level far
        // worse than the missing model did.
        var names = new string[Records];
        int free = -1;
        for (int i = 0; i < Records; i++) names[i] = NameAt(m, i);
        for (int i = Records - 1; i >= 0; i--)
            if (names[i].Length == 0) { free = i; break; }
        if (free < 0) return;

        for (int i = 0; i < Records; i++)
        {
            if (names[i].Length == 0) continue;
            string want = Counterpart(names[i]);
            if (string.IsNullOrEmpty(want) || want == names[i]) continue;

            bool present = false;
            for (int k = 0; k < Records; k++)
                if (string.Equals(names[k], want, StringComparison.OrdinalIgnoreCase)) { present = true; break; }
            if (present) continue;

            // Copy the whole record so every field the actor reads comes along, then
            // rename it. Only the name is looked up; the rest is the model itself.
            uint src = Table + (uint)(i * Stride), dst = Table + (uint)(free * Stride);
            for (uint k = 0; k < Stride; k += 4) m.WriteU32(dst + k, m.ReadU32(src + k));
            var bytes = Encoding.ASCII.GetBytes(want);
            for (uint k = 0; k < bytes.Length; k++) m.WriteU8(dst + k, bytes[k]);
            m.WriteU8(dst + (uint)bytes.Length, 0);

            Console.WriteLine($"[alias] '{want}' -> the resident '{names[i]}' (slot {free})");
            Added++;
            return;   // one per frame; the next sweep picks up any others
        }
    }
}
