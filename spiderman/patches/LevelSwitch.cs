using System;
using System.Text;
using System.Text.RegularExpressions;
using RecompOne.Runtime.Context;
using RecompOne.Runtime.Memory;

namespace Recompiled;

/// <summary>
/// Boots straight into a chosen level by selecting its retail level descriptor, then
/// rewriting archive lookups as a fallback for alternate acts that have no descriptor.
///
/// Retail level descriptors carry state beyond the filenames, including which overlay
/// callbacks and HUD elements a level enables.  Selecting l5a1 files while leaving the
/// current descriptor at l1a1_t therefore produces an invalid hybrid level with no Venom
/// chase HUD.  Descriptor-backed levels are selected before the game's table lookup so
/// their complete retail state is retained.
///
///     SPIDEY_LEVEL=l5a3     start in level 5, act 3
///
/// The first level prefix the game asks for is the one that gets redirected -- normally
/// `l1a1`, the level a new game starts on. Once bound, only that prefix is rewritten, so
/// when the level finishes and the game moves on to the next act it loads normally
/// rather than looping on the same assets.
/// </summary>
public static class LevelSwitch
{
    // Scratch for the rewritten name. Above the overlay region, inside the 8 MB the port
    // runs with, and never allocated from -- see OverlayPatches for why that space exists.
    const uint Scratch = 0x802B0000;

    // The current trigger/descriptor name used by func_80018800.  The descriptor table
    // contains 34 retail entries of 20 bytes each; +4 is the trigger-name pointer.
    const uint CurrentLevelName = 0x800A568C;
    const uint LevelDescriptors = 0x800974A4;
    const int LevelDescriptorCount = 34;

    static readonly Regex LevelName = new(@"^(l\d+a\d+[a-z]?)(.*)$", RegexOptions.IgnoreCase);
    static readonly Regex AudioLevelName = new(@"^(l\d+a\d+)", RegexOptions.IgnoreCase);

    static string _target;
    static string _source;
    static bool _descriptorSelected;
    public static int Rewrites { get; private set; }

    public static void Install()
    {
        var want = Environment.GetEnvironmentVariable("SPIDEY_LEVEL");
        if (!string.IsNullOrWhiteSpace(want))
        {
            _target = want.Trim().ToLowerInvariant();
            Console.WriteLine($"[level] starting in '{_target}'");
        }

    }

    /// <summary>
    /// Select the requested retail descriptor before func_80018800 searches for it.
    /// This preserves level-specific flags and callbacks that cannot be reconstructed
    /// by substituting archive filenames alone.
    /// </summary>
    public static void SelectDescriptor(CpuContext c, IMemory m)
    {
        if (_descriptorSelected || _target == null || c.A0 != CurrentLevelName) return;

        string targetName = _target + "_t";
        if (!HasDescriptor(m, targetName)) return;

        string currentName = ReadCString(m, CurrentLevelName, 16);
        if (!Regex.IsMatch(currentName, @"^l\d+a\d+_t$", RegexOptions.IgnoreCase)) return;

        if (!string.Equals(currentName, targetName, StringComparison.OrdinalIgnoreCase))
        {
            WriteCString(m, CurrentLevelName, targetName);
            Console.WriteLine($"[level] descriptor {currentName} -> {targetName}");
        }

        _descriptorSelected = true;
    }

    /// <summary>
    /// Called first thing from the CdWadFind pre-hook. Returns the name the game should
    /// actually look up, having pointed a0 at it when it changed.
    /// </summary>
    public static string Redirect(CpuContext c, IMemory m, string name)
    {
        if (name == null) return name;


        if (_target == null) return name;

        var hit = LevelName.Match(name);
        if (!hit.Success) return name;

        string prefix = hit.Groups[1].Value, rest = hit.Groups[2].Value;

        // Bind to whichever level the game asks for first and redirect only that one.
        _source ??= prefix.ToLowerInvariant();
        if (!string.Equals(prefix, _source, StringComparison.OrdinalIgnoreCase)) return name;

        // Alternate acts such as L1A2A and L3A1A have their own trigger/geometry files
        // but reuse the parent act's VAB/SFX pair.  Asking CD.WAD for L1A2A.VAB runs the
        // retail lookup off the end because that entry does not exist.  Redirect only
        // those audio requests to the numeric parent while keeping every other resource
        // on the exact alternate-act prefix.
        string target = _target;
        if (rest.Equals(".VAB", StringComparison.OrdinalIgnoreCase) ||
            rest.Equals(".SFX", StringComparison.OrdinalIgnoreCase))
        {
            var audio = AudioLevelName.Match(target);
            if (audio.Success) target = audio.Groups[1].Value;
        }

        // Follow the case the game used, in case the archive compare is case sensitive.
        string swapped = char.IsUpper(prefix[0]) ? target.ToUpperInvariant() : target;
        string redirected = swapped + rest;
        return string.Equals(name, redirected, StringComparison.Ordinal)
            ? name
            : Rewrite(c, m, name, redirected);
    }

    static string Rewrite(CpuContext c, IMemory m, string from, string to)
    {
        var bytes = Encoding.ASCII.GetBytes(to);
        for (int i = 0; i < bytes.Length; i++) m.WriteU8(Scratch + (uint)i, bytes[i]);
        m.WriteU8(Scratch + (uint)bytes.Length, 0);
        c.A0 = Scratch;

        Rewrites++;
        Console.WriteLine($"[level] {from} -> {to}");
        return to;
    }

    static bool HasDescriptor(IMemory m, string triggerName)
    {
        for (int i = 0; i < LevelDescriptorCount; i++)
        {
            uint nameAddress = m.ReadU32(LevelDescriptors + (uint)(i * 20 + 4));
            if (nameAddress == 0) continue;
            if (string.Equals(ReadCString(m, nameAddress, 16), triggerName,
                              StringComparison.OrdinalIgnoreCase))
                return true;
        }
        return false;
    }

    static string ReadCString(IMemory m, uint address, int max)
    {
        var text = new StringBuilder();
        for (int i = 0; i < max; i++)
        {
            byte value = m.ReadU8(address + (uint)i);
            if (value == 0) break;
            text.Append((char)value);
        }
        return text.ToString();
    }

    static void WriteCString(IMemory m, uint address, string text)
    {
        byte[] bytes = Encoding.ASCII.GetBytes(text);
        for (int i = 0; i < bytes.Length; i++) m.WriteU8(address + (uint)i, bytes[i]);
        m.WriteU8(address + (uint)bytes.Length, 0);
    }
}
