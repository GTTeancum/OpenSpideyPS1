using System;
using System.Collections.Generic;
using System.IO;
using RecompOne.Runtime.Memory;

namespace Recompiled;

/// <summary>
/// Recomp-only storage for SM1's runtime texture records.
///
/// Retail places a 17-entry table immediately before the animation-event table.
/// Dreamcast actors legitimately register more pages than that, so the original
/// layout overwrites animation pointers. Expanded RAM between the loose-WAD arena
/// and the costume-viewer table gives the registry its own 256 KiB region.
/// </summary>
public static class TextureRegistry
{
    static readonly bool TraceEnabled =
        Environment.GetEnvironmentVariable("RECOMP_TRACE_TEXTURE_REGISTRY") == "1";
    static readonly Dictionary<uint, (ushort TPage, ushort Clut, uint Index)> Seen = [];
    public const uint Table = 0x80780000u;
    public const uint End = Costume.ViewerTable;
    public const uint RecordSize = 8u;
    public const uint Capacity = (End - Table) / RecordSize;

    /// <summary>
    /// SM1's model loader only registers a hard-coded list of retail Spider-Man
    /// texture hashes. Recompiled costumes may use arbitrary donor hashes, so the
    /// stable boundary is the model slot: 2 in the shell and 12 in gameplay.
    /// </summary>
    public static bool IsPlayerModelSlot(uint slot) => slot == 2u || slot == 12u;

    public static void ValidateAppend(uint count)
    {
        // The appender always writes a zero terminator after the new record.
        if (count >= Capacity - 1u)
            throw new InvalidOperationException(
                $"expanded texture registry exhausted at {count} records");
    }

    /// <summary>
    /// Remove registry records for a player model that is actually being replaced.
    /// Costume.RunRetailTextureOverlay suppresses duplicate reload requests so cached
    /// texture coordinates cannot be invalidated by pointless free/reallocate cycles.
    /// </summary>
    public static void RemoveModelTextures(
        IMemory memory, uint countAddress, uint modelEntry, uint modelBase)
    {
        uint objectCount = memory.ReadU32(modelBase + 8u);
        if (objectCount > 1024u)
            throw new InvalidDataException($"invalid player object count {objectCount}");
        uint meshCount = memory.ReadU32(modelBase + 12u + objectCount * 36u);
        if (meshCount > 4096u)
            throw new InvalidDataException($"invalid player mesh count {meshCount}");

        // func_80068BB0 stores the absolute end of tagged metadata at +0x0C in
        // the model-cache record. The mesh-name array follows, then the texture
        // count and the hash array that the loader replaces with descriptor pointers.
        uint metadataEnd = memory.ReadU32(modelEntry + 0x0Cu);
        uint textureCountAddress = metadataEnd + meshCount * 4u;
        uint textureCount = memory.ReadU32(textureCountAddress);
        if (textureCount > 4096u)
            throw new InvalidDataException($"invalid player texture count {textureCount}");
        // The first viewer actor can be retail Spider-Man's valid nine-page
        // model; converted actors may have fourteen pages or a larger fixed
        // support window. Remove exactly the descriptors declared by whichever
        // actor is currently cached instead of imposing the replacement's layout.
        var descriptors = new HashSet<uint>();
        for (uint i = 0; i < textureCount; i++)
            descriptors.Add(memory.ReadU32(textureCountAddress + 4u + i * 4u));

        uint count = memory.ReadU32(countAddress);
        uint write = 0;
        for (uint read = 0; read < count; read++)
        {
            uint source = Table + read * RecordSize;
            uint texture = memory.ReadU32(source);
            if (descriptors.Contains(texture)) continue;
            if (write != read)
            {
                uint destination = Table + write * RecordSize;
                memory.WriteU32(destination, texture);
                memory.WriteU16(destination + 4u, memory.ReadU16(source + 4u));
                memory.WriteU16(destination + 6u, memory.ReadU16(source + 6u));
            }
            write++;
        }
        memory.WriteU32(Table + write * RecordSize, 0u);
        memory.WriteU32(countAddress, write);
        if (TraceEnabled && write != count)
            Console.WriteLine(
                $"[texture-registry] removed {count - write} stale player record(s)");
    }

    public static void TraceAppend(uint index, uint key, uint tpage, uint clut)
    {
        if (!TraceEnabled) return;
        ushort page = (ushort)tpage;
        ushort palette = (ushort)clut;
        string duplicate = Seen.TryGetValue(key, out var prior)
            ? $" prior={prior.Index}:{prior.TPage:X3}/{prior.Clut:X4}"
            : "";
        Console.WriteLine(
            $"[texture-registry] index={index} key={key:X8} " +
            $"tpage={page:X3} clut={palette:X4}{duplicate}");
        Seen[key] = (page, palette, index);
    }

    public static void ValidateTextureBlock(uint index)
    {
        if (index >= 192u)
            throw new InvalidOperationException(
                "PS1 texture-block allocator exhausted; refusing its out-of-bounds slot 192");
    }

    public static void ValidateClutSlot(uint index)
    {
        if (index >= 68u)
            throw new InvalidOperationException(
                "PS1 CLUT allocator exhausted; refusing its out-of-bounds slot 68");
    }
}
