using System;
using System.Collections.Generic;
using RecompOne.Runtime.Context;
using RecompOne.Runtime.Memory;

namespace Recompiled;

/// <summary>
/// Opt-in diagnostics for the Neversoft segmented-character stitch path.
///
/// Set RECOMP_TRACE_MODEL_STITCHES=1 to verify both stages of the contract:
/// M3dInit_ParsePSX rewrites on-disc type-2 vertices from (0,index,0) to
/// (index*8,0,0), then the renderer resolves that byte offset against the
/// downward-growing transformed-source buffer. Nothing runs in normal builds.
/// </summary>
public static class ModelDiagnostics
{
    static readonly bool TraceEnabled =
        !string.IsNullOrWhiteSpace(Environment.GetEnvironmentVariable("RECOMP_TRACE_MODEL_STITCHES"));
    static readonly bool ValidationEnabled =
        !string.IsNullOrWhiteSpace(Environment.GetEnvironmentVariable("RECOMP_VALIDATE_MODEL_GEOMETRY"));
    static readonly bool LightingEnabled =
        Environment.GetEnvironmentVariable("RECOMP_AUDIT_PLAYER_LIGHTING") == "1";
    static readonly string LayoutFilter =
        Environment.GetEnvironmentVariable("RECOMP_TRACE_MODEL_LAYOUT")?.Trim() ?? "";
    static readonly bool LayoutEnabled = LayoutFilter.Length != 0;
    static readonly bool Enabled = TraceEnabled || ValidationEnabled || LayoutEnabled || LightingEnabled;

    readonly record struct MeshIdentity(uint Slot, string ModelName, int MeshIndex, int MeshCount);

    static uint _parseSlot;
    static uint _sourceBase;
    static uint _lastSourcePointer;
    static int _sequence;
    static int _call;
    static int _activeCall;
    static uint _activeVertexPointer;
    static uint _activeVertexCount;
    static uint _activeOutputPointer;
    static int _activePlayerMesh = -1;
    static MeshIdentity? _activeIdentity;
    static readonly Dictionary<uint, int> _playerVertexPointers = [];
    static readonly Dictionary<uint, MeshIdentity> _meshVertexPointers = [];
    static readonly HashSet<long> _auditedFaceBatches = [];
    static readonly HashSet<uint> _seenMeshes = [];
    static bool _layoutSequenceMatched;
    static int _layoutSequenceTransforms;
    static int _layoutMinX = int.MaxValue, _layoutMaxX = int.MinValue;
    static int _layoutMinY = int.MaxValue, _layoutMaxY = int.MinValue;
    static int _layoutMinZ = int.MaxValue, _layoutMaxZ = int.MinValue;

    public static void ParseEnter(CpuContext c, IMemory m)
    {
        if (!Enabled) return;
        _parseSlot = c.A0;
    }

    public static void ParseExit(CpuContext c, IMemory m)
    {
        if (!Enabled || _parseSlot >= 64) return;

        uint entry = 0x800A0904u + (_parseSlot << 6);
        uint pointerTable = m.ReadU32(entry + 0x10u);
        if (pointerTable < 4) return;
        uint meshCount = m.ReadU32(pointerTable - 4u);
        string modelName = ReadCString(m, entry, 16);
        int sources = 0;
        int references = 0;
        int malformed = 0;
        int maxReference = -1;
        for (uint mesh = 0; mesh < meshCount; mesh++)
        {
            uint model = m.ReadU32(pointerTable + mesh * 4u);
            uint vertexCount = m.ReadU16(model + 2u);
            uint vertices = model + 0x1Cu;
            if (LayoutEnabled || LightingEnabled)
                _meshVertexPointers[vertices] = new MeshIdentity(
                    _parseSlot, modelName, checked((int)mesh), checked((int)meshCount));
            // Spider-Man moves from title slot 2 to level slot 12 in L1A1.
            // Other 18-part actors (notably Black Cat) use different face packet
            // layouts, so including them creates false player-geometry failures.
            if (meshCount == 18)
            {
                if (_parseSlot == 2 || _parseSlot == 12)
                    _playerVertexPointers[vertices] = checked((int)mesh);
                else
                    // The model arena reuses addresses after the title actor is
                    // freed. Do not let a later 18-part NPC inherit that identity.
                    _playerVertexPointers.Remove(vertices);
            }
            // Slot 2 is the active player model in both the title-shell costume
            // preview and normal gameplay.  Other 18-part actors can load later
            // (notably into slot 9); they must not replace the pointer used by
            // the player geometry audit.
            if (_parseSlot == 2 && mesh == 7 && meshCount == 18)
            {
                if (TraceEnabled)
                {
                    string samples = vertexCount > 95
                        ? $" 60={RawPoint(m, vertices, 60)} " +
                          $"93={RawPoint(m, vertices, 93)} " +
                          $"95={RawPoint(m, vertices, 95)}"
                        : "";
                    Console.WriteLine(
                        $"[model-head-loaded] slot={_parseSlot} mesh=7 pointer=0x{model:X8} " +
                        $"vertices={vertexCount} faces={m.ReadU16(model + 6u)}{samples}");
                }
            }
            uint vertex = model + 0x1Cu;
            for (uint index = 0; index < vertexCount; index++, vertex += 8u)
            {
                ushort flags = m.ReadU16(vertex + 6u);
                if ((flags & 1) != 0) sources++;
                if ((flags & 2) == 0) continue;
                references++;
                ushort byteOffset = m.ReadU16(vertex);
                ushort y = m.ReadU16(vertex + 2u);
                if ((byteOffset & 7) != 0 || y != 0) malformed++;
                maxReference = Math.Max(maxReference, byteOffset / 8);
            }
        }

        if (TraceEnabled)
            Console.WriteLine(
                $"[model-stitch] parsed slot={_parseSlot} meshes={meshCount} " +
                $"sources={sources} refs={references} max-ref={maxReference} malformed={malformed}");
        if (LayoutEnabled && ModelMatches(modelName))
            Console.WriteLine(
                $"[model-layout-loaded] slot={_parseSlot} name={modelName} meshes={meshCount} " +
                $"parts={m.ReadU16(entry + 0x34u)} pointer-table=0x{pointerTable:X8}");
    }

    public static void TransformEnter(CpuContext c, IMemory m)
    {
        if (!Enabled || c.A1 == 0) return;

        uint sourcePointer = m.ReadU32(0x800B5940u);
        if (_sourceBase == 0 || sourcePointer > _lastSourcePointer)
        {
            FlushLayoutSequence();
            _sourceBase = sourcePointer;
            _sequence++;
            _call = 0;
            _seenMeshes.Clear();
            Console.WriteLine($"[model-stitch] render-sequence={_sequence} source-base=0x{_sourceBase:X8}");
        }

        _activeCall = _call;
        _activeVertexPointer = c.A0;
        _activeVertexCount = c.A1;
        _activeOutputPointer = m.ReadU32(0x800B58F0u);
        _activePlayerMesh = _playerVertexPointers.TryGetValue(c.A0, out int playerMesh)
            ? playerMesh
            : -1;
        _activeIdentity = _meshVertexPointers.TryGetValue(c.A0, out MeshIdentity identity)
            ? identity
            : null;

        if (_activePlayerMesh == 7 && TraceEnabled)
            DumpHeadTransform(c, m);

        int priorSources = _sourceBase >= sourcePointer
            ? checked((int)((_sourceBase - sourcePointer) / 8u))
            : -1;
        int localSources = 0;
        int references = 0;
        int premature = 0;
        int maxReference = -1;
        uint vertex = c.A0;
        for (uint index = 0; index < c.A1; index++, vertex += 8u)
        {
            ushort flags = m.ReadU16(vertex + 6u);
            if ((flags & 1) != 0) localSources++;
            if ((flags & 2) == 0) continue;
            references++;
            int target = m.ReadU16(vertex) / 8;
            maxReference = Math.Max(maxReference, target);
            if (target >= priorSources + localSources) premature++;
        }

        if (TraceEnabled && (localSources != 0 || references != 0) && _seenMeshes.Add(c.A0))
        {
            Console.WriteLine(
                $"[model-stitch] call={_call} vertices={c.A1} prior={priorSources} " +
                $"sources={localSources} refs={references} max-ref={maxReference} premature={premature} " +
                $"source-ptr=0x{sourcePointer:X8} vertices-ptr=0x{c.A0:X8}");
        }

        if (LayoutEnabled && _activeIdentity is MeshIdentity layout && ModelMatches(layout.ModelName))
            Console.WriteLine(
                $"[model-layout-stitches] sequence={_sequence} mesh={layout.MeshIndex} " +
                $"caller=0x{c.RA:X8} output=0x{_activeOutputPointer:X8} " +
                $"source=0x{sourcePointer:X8} prior={priorSources} sources={localSources} " +
                $"refs={references} max-ref={maxReference} premature={premature}");

        _call++;
        _lastSourcePointer = sourcePointer - checked((uint)localSources * 8u);
    }

    public static void TransformExit(CpuContext c, IMemory m)
    {
        bool tracePlayer = TraceEnabled && _activePlayerMesh >= 0;
        MeshIdentity identity = _activeIdentity.GetValueOrDefault();
        bool traceLayout = LayoutEnabled && _activeIdentity.HasValue && ModelMatches(identity.ModelName);
        if ((!tracePlayer && !traceLayout) || _activeVertexCount == 0) return;

        if (traceLayout && m is PSMemory ps)
        {
            int stitches = 0, nativeMismatch = 0, projectionMismatch = 0, missingProjection = 0;
            float maxDelta = 0;
            for (uint index = 0; index < _activeVertexCount; index++)
            {
                uint input = _activeVertexPointer + index * 8u;
                if ((m.ReadU16(input + 6u) & 2) == 0) continue;
                stitches++;
                // The transform's T3 is outputBase+0x1F38. Parsed stitch X is
                // the byte offset subtracted from this fixed source origin.
                uint source = _activeOutputPointer + 0x1F38u - m.ReadU16(input);
                uint output = _activeOutputPointer + index * 8u;
                uint sourceWord = m.ReadU32(source), outputWord = m.ReadU32(output);
                if (sourceWord != outputWord || m.ReadU32(source + 4u) != m.ReadU32(output + 4u)) nativeMismatch++;
                bool hasSource = ps.TryGetGteVertex(source, sourceWord, out var sourceTag) && sourceTag.HasSubpixel;
                bool hasOutput = ps.TryGetGteVertex(output, outputWord, out var outputTag) && outputTag.HasSubpixel;
                if (!hasSource || !hasOutput) missingProjection++;
                else
                {
                    if (sourceTag != outputTag) projectionMismatch++;
                    maxDelta = Math.Max(maxDelta, Math.Max(Math.Abs(sourceTag.ScreenX - outputTag.ScreenX),
                        Math.Abs(sourceTag.ScreenY - outputTag.ScreenY)));
                }
            }
            if (stitches != 0)
                Console.WriteLine($"[model-shared-vertices] sequence={_sequence} name={identity.ModelName} mesh={identity.MeshIndex} " +
                    $"stitches={stitches} native-mismatch={nativeMismatch} projection-mismatch={projectionMismatch} " +
                    $"missing-projection={missingProjection} max-screen-delta={maxDelta:R}");
        }

        int outliers = 0;
        int rigidMinX = int.MaxValue, rigidMaxX = int.MinValue;
        int rigidMinY = int.MaxValue, rigidMaxY = int.MinValue;
        int stitchMinX = int.MaxValue, stitchMaxX = int.MinValue;
        int stitchMinY = int.MaxValue, stitchMaxY = int.MinValue;
        int minZ = int.MaxValue, maxZ = int.MinValue;
        for (uint index = 0; index < _activeVertexCount; index++)
        {
            uint input = _activeVertexPointer + index * 8u;
            uint output = _activeOutputPointer + index * 8u;
            short x = unchecked((short)m.ReadU16(output));
            short y = unchecked((short)m.ReadU16(output + 2u));
            short z = unchecked((short)m.ReadU16(output + 4u));
            minZ = Math.Min(minZ, z); maxZ = Math.Max(maxZ, z);
            ushort flags = m.ReadU16(input + 6u);
            if ((flags & 2) != 0)
            {
                stitchMinX = Math.Min(stitchMinX, x); stitchMaxX = Math.Max(stitchMaxX, x);
                stitchMinY = Math.Min(stitchMinY, y); stitchMaxY = Math.Max(stitchMaxY, y);
            }
            else
            {
                rigidMinX = Math.Min(rigidMinX, x); rigidMaxX = Math.Max(rigidMaxX, x);
                rigidMinY = Math.Min(rigidMinY, y); rigidMaxY = Math.Max(rigidMaxY, y);
            }
            if (x >= -640 && x <= 960 && y >= -480 && y <= 720) continue;

            ushort stitchOffset = m.ReadU16(input);
            if (tracePlayer)
                Console.WriteLine(
                    $"[model-mesh] sequence={_sequence} mesh={_activePlayerMesh} vertex={index} xy=({x},{y}) " +
                    $"type={(flags & 3)} stitch={(flags & 2) != 0} offset={stitchOffset}");
            outliers++;
        }
        if (tracePlayer && outliers != 0)
            Console.WriteLine(
                $"[model-mesh] sequence={_sequence} mesh={_activePlayerMesh} outliers={outliers}/{_activeVertexCount}");

        int minX = Math.Min(rigidMinX, stitchMinX);
        int maxX = Math.Max(rigidMaxX, stitchMaxX);
        int minY = Math.Min(rigidMinY, stitchMinY);
        int maxY = Math.Max(rigidMaxY, stitchMaxY);
        if (traceLayout)
        {
            _layoutSequenceMatched = true;
            _layoutSequenceTransforms++;
            _layoutMinX = Math.Min(_layoutMinX, minX); _layoutMaxX = Math.Max(_layoutMaxX, maxX);
            _layoutMinY = Math.Min(_layoutMinY, minY); _layoutMaxY = Math.Max(_layoutMaxY, maxY);
            _layoutMinZ = Math.Min(_layoutMinZ, minZ); _layoutMaxZ = Math.Max(_layoutMaxZ, maxZ);
            Console.WriteLine(
                $"[model-layout-transform] sequence={_sequence} slot={identity.Slot} name={identity.ModelName} " +
                $"mesh={identity.MeshIndex}/{identity.MeshCount} vertices={_activeVertexCount} " +
                $"xyz=({minX},{minY},{minZ})..({maxX},{maxY},{maxZ})");
        }
        if (tracePlayer && (_sequence <= 3 || maxX - minX > 320 || maxY - minY > 320))
        {
            Console.WriteLine(
                $"[model-mesh-bounds] sequence={_sequence} mesh={_activePlayerMesh} all=({minX},{minY})..({maxX},{maxY}) " +
                $"rigid=({rigidMinX},{rigidMinY})..({rigidMaxX},{rigidMaxY}) " +
                $"stitch=({stitchMinX},{stitchMinY})..({stitchMaxX},{stitchMaxY})");
            if (_activePlayerMesh == 7 && _activeVertexCount > 95)
                Console.WriteLine(
                    $"[model-head-129-after-transform] sequence={_sequence} " +
                    $"60={ScreenPoint(m, _activeOutputPointer, 60)} " +
                    $"93={ScreenPoint(m, _activeOutputPointer, 93)} " +
                    $"95={ScreenPoint(m, _activeOutputPointer, 95)}");
        }
    }

    public static void DrawFacesEnter(CpuContext c, IMemory m)
    {
        if (LightingEnabled && _activeIdentity is MeshIdentity actor &&
            actor.ModelName.Equals("spidey", StringComparison.OrdinalIgnoreCase))
            AuditLighting(c, m, actor);
        if (!Enabled || _activePlayerMesh < 0 || _activeVertexCount == 0 || c.A2 == 0)
            return;
        long batchKey = ((long)_sequence << 32) | (uint)_activePlayerMesh;
        if (!_auditedFaceBatches.Add(batchKey))
            return;

        if (TraceEnabled)
        {
            short depth4000 = unchecked((short)m.ReadU16(0x1F8002C4u));
            short depth2000 = unchecked((short)m.ReadU16(0x1F8002B4u));
            short depth6000 = unchecked((short)m.ReadU16(0x1F800344u));
            Console.WriteLine(
                $"[model-mesh-depth-bias] sequence={_sequence} mesh={_activePlayerMesh} " +
                $"flag4000={depth4000} flag2000={depth2000} flag6000={depth6000}");
        }

        int invalid = 0;
        int maxSpan = 0;
        int maxFace = -1;
        string maxIndices = "";
        uint face = c.A0;
        for (uint faceIndex = 0; faceIndex < c.A2; faceIndex++)
        {
            ushort flags = m.ReadU16(face);
            ushort length = m.ReadU16(face + 2u);
            if (length < 16 || length > 256)
            {
                Console.WriteLine(
                    $"[model-mesh-faces] sequence={_sequence} mesh={_activePlayerMesh} malformed-length={length} face={faceIndex}");
                break;
            }

            int corners = (flags & 0x20) != 0 ? 4 : 3;
            int minX = int.MaxValue, maxX = int.MinValue;
            int minY = int.MaxValue, maxY = int.MinValue;
            var indices = new int[corners];
            for (int corner = 0; corner < corners; corner++)
            {
                int index = m.ReadU8(face + 4u + (uint)corner);
                indices[corner] = index;
                if (index >= _activeVertexCount)
                {
                    invalid++;
                    continue;
                }
                uint output = _activeOutputPointer + (uint)index * 8u;
                short x = unchecked((short)m.ReadU16(output));
                short y = unchecked((short)m.ReadU16(output + 2u));
                minX = Math.Min(minX, x); maxX = Math.Max(maxX, x);
                minY = Math.Min(minY, y); maxY = Math.Max(maxY, y);
            }
            int span = Math.Max(maxX - minX, maxY - minY);
            if (span > maxSpan)
            {
                maxSpan = span;
                maxFace = (int)faceIndex;
                maxIndices = string.Join(',', indices);
            }
            face += length;
        }

        if (_sequence <= 3 || invalid != 0 || maxSpan > 160)
        {
            Console.WriteLine(
                $"[model-mesh-faces] sequence={_sequence} mesh={_activePlayerMesh} faces={c.A2} invalid={invalid} " +
                $"max-span={maxSpan} face={maxFace} indices={maxIndices}");
            if (_activePlayerMesh == 7 && _activeVertexCount > 95)
                Console.WriteLine(
                    $"[model-head-129-at-draw] sequence={_sequence} " +
                    $"60={ScreenPoint(m, _activeOutputPointer, 60)} " +
                    $"93={ScreenPoint(m, _activeOutputPointer, 93)} " +
                    $"95={ScreenPoint(m, _activeOutputPointer, 95)}");
        }
        if (ValidationEnabled)
        {
            Console.WriteLine(
                $"[model-mesh-audit] sequence={_sequence} mesh={_activePlayerMesh} vertices={_activeVertexCount} " +
                $"faces={c.A2} invalid={invalid} max-span={maxSpan}");
        }
    }

    static void AuditLighting(CpuContext c, IMemory m, MeshIdentity actor)
    {
        // Mirror DrawPrimSet's input color selection before depth cueing. Keep
        // actor identity explicit: model arenas can reuse a previous player's address.
        uint table = m.ReadU32(0x800B5914u);
        uint faceMask = m.ReadU32(0x1F8003F4u);
        uint face = c.A0;
        long sumR = 0, sumG = 0, sumB = 0;
        long shadeR = 0, shadeG = 0, shadeB = 0;
        int shadeSamples = 0, shadeBlack = 0;
        int samples = 0, black = 0, min = 765, max = 0, smooth = 0;
        uint hash = 2166136261u;
        for (uint i = 0; i < c.A2; i++)
        {
            ushort flags = m.ReadU16(face), length = m.ReadU16(face + 2u);
            if (length < 16 || length > 256) break;
            flags = (ushort)((flags & (faceMask >> 16)) | (faceMask & 65535u));
            uint colors = m.ReadU32(face + 8u);
            bool indexed = (flags & 0x0800) != 0;
            int count = indexed ? ((flags & 0x20) != 0 ? 4 : 3) : 1;
            if (indexed) smooth++;
            for (int k = 0; k < count; k++)
            {
                uint rgb = indexed ? m.ReadU32(table + ((colors >> (k * 8)) & 255u) * 4u) : colors;
                int r = (int)(rgb & 255), g = (int)((rgb >> 8) & 255), b = (int)((rgb >> 16) & 255);
                sumR += r; sumG += g; sumB += b; samples++;
                min = Math.Min(min, r + g + b); max = Math.Max(max, r + g + b);
                if (r + g + b == 0) black++;
                hash = unchecked((hash ^ (rgb & 0xffffffu)) * 16777619u);
            }
            // The 0xC mode reads packed vertex lighting from the parallel
            // transformed buffer, not from the face's constant base color.
            if ((flags & 0xC) == 0xC)
            {
                int corners = (flags & 0x20) != 0 ? 4 : 3;
                for (int k = 0; k < corners; k++)
                {
                    uint index = m.ReadU8(face + 4u + (uint)k);
                    if (index >= _activeVertexCount) continue;
                    uint packed = m.ReadU32(_activeOutputPointer + index * 8u + 0x1F44u);
                    int r = (ushort)(packed << 5), g = (ushort)(packed >> 6), b = (ushort)(packed >> 17);
                    shadeR += r; shadeG += g; shadeB += b; shadeSamples++;
                    if (r + g + b == 0) shadeBlack++;
                }
            }
            face += length;
        }
        Console.WriteLine($"[player-lighting] sequence={_sequence} slot={actor.Slot} mesh={actor.MeshIndex} " +
            $"faces={c.A2} smooth={smooth} samples={samples} sums={sumR},{sumG},{sumB} " +
            $"range={min},{max} black={black} hash={hash:X8} table={table:X8} " +
            $"shade-samples={shadeSamples} shade-sums={shadeR},{shadeG},{shadeB} shade-black={shadeBlack} " +
            $"uniform-shade={m.ReadU32(0x1F8003E4u):X8} " +
            $"fog-start={m.ReadU16(0x1F800284u)} fog-shift={m.ReadU16(0x1F800294u)} " +
            $"face-mask={m.ReadU32(0x1F8003F4u):X8}");
    }

    static string ScreenPoint(IMemory m, uint outputBase, uint index)
    {
        uint output = outputBase + index * 8u;
        short x = unchecked((short)m.ReadU16(output));
        short y = unchecked((short)m.ReadU16(output + 2u));
        return $"({x},{y})";
    }

    static bool ModelMatches(string modelName) =>
        modelName.Contains(LayoutFilter, StringComparison.OrdinalIgnoreCase);

    static string ReadCString(IMemory m, uint address, int max)
    {
        var chars = new char[max];
        int length = 0;
        for (; length < max; length++)
        {
            byte value = m.ReadU8(address + (uint)length);
            if (value == 0) break;
            chars[length] = value is >= 32 and <= 126 ? (char)value : '?';
        }
        return new string(chars, 0, length);
    }

    static void FlushLayoutSequence()
    {
        if (!_layoutSequenceMatched) return;
        Console.WriteLine(
            $"[model-layout-sequence] sequence={_sequence} transforms={_layoutSequenceTransforms} " +
            $"xyz=({_layoutMinX},{_layoutMinY},{_layoutMinZ})..({_layoutMaxX},{_layoutMaxY},{_layoutMaxZ})");
        _layoutSequenceMatched = false;
        _layoutSequenceTransforms = 0;
        _layoutMinX = _layoutMinY = _layoutMinZ = int.MaxValue;
        _layoutMaxX = _layoutMaxY = _layoutMaxZ = int.MinValue;
    }

    static string RawPoint(IMemory m, uint inputBase, uint index)
    {
        uint input = inputBase + index * 8u;
        short x = unchecked((short)m.ReadU16(input));
        short y = unchecked((short)m.ReadU16(input + 2u));
        short z = unchecked((short)m.ReadU16(input + 4u));
        ushort flags = m.ReadU16(input + 6u);
        return $"({x},{y},{z};flags={flags})";
    }

    static void DumpHeadTransform(CpuContext c, IMemory m)
    {
        static short Lo(uint value) => unchecked((short)value);
        static short Hi(uint value) => unchecked((short)(value >> 16));

        uint rt01 = RecompOne.Runtime.Gte.ReadControl(0);
        uint rt23 = RecompOne.Runtime.Gte.ReadControl(1);
        uint rt45 = RecompOne.Runtime.Gte.ReadControl(2);
        uint rt67 = RecompOne.Runtime.Gte.ReadControl(3);
        short[] rt =
        [
            Lo(rt01), Hi(rt01), Lo(rt23), Hi(rt23), Lo(rt45),
            Hi(rt45), Lo(rt67), Hi(rt67), Lo(RecompOne.Runtime.Gte.ReadControl(4))
        ];
        int trx = unchecked((int)RecompOne.Runtime.Gte.ReadControl(5));
        int try_ = unchecked((int)RecompOne.Runtime.Gte.ReadControl(6));
        int trz = unchecked((int)RecompOne.Runtime.Gte.ReadControl(7));
        int ofx = unchecked((int)RecompOne.Runtime.Gte.ReadControl(24));
        int ofy = unchecked((int)RecompOne.Runtime.Gte.ReadControl(25));
        int h = unchecked((short)RecompOne.Runtime.Gte.ReadControl(26));

        static long RowLengthSquared(short[] matrix, int row)
        {
            int offset = row * 3;
            long x = matrix[offset], y = matrix[offset + 1], z = matrix[offset + 2];
            return x * x + y * y + z * z;
        }

        static long Dot(short[] matrix, int left, int right)
        {
            int a = left * 3, b = right * 3;
            return (long)matrix[a] * matrix[b] +
                   (long)matrix[a + 1] * matrix[b + 1] +
                   (long)matrix[a + 2] * matrix[b + 2];
        }

        long determinant =
            (long)rt[0] * (rt[4] * rt[8] - rt[5] * rt[7]) -
            (long)rt[1] * (rt[3] * rt[8] - rt[5] * rt[6]) +
            (long)rt[2] * (rt[3] * rt[7] - rt[4] * rt[6]);

        uint precisionMode = m.ReadU32(c.GP + 0x1170u);
        string inputs = _activeVertexCount > 95
            ? $" input60={InputPoint(m, _activeVertexPointer, 60, precisionMode != 0)}" +
              $" input93={InputPoint(m, _activeVertexPointer, 93, precisionMode != 0)}" +
              $" input95={InputPoint(m, _activeVertexPointer, 95, precisionMode != 0)}"
            : "";
        Console.WriteLine(
            $"[model-head-matrix] sequence={_sequence} " +
            $"precision={(precisionMode != 0 ? "near" : "far")} " +
            $"rt=[{rt[0]},{rt[1]},{rt[2]};{rt[3]},{rt[4]},{rt[5]};{rt[6]},{rt[7]},{rt[8]}] " +
            $"tr=({trx},{try_},{trz}) row-len2=({RowLengthSquared(rt, 0)},{RowLengthSquared(rt, 1)},{RowLengthSquared(rt, 2)}) " +
            $"row-dot=({Dot(rt, 0, 1)},{Dot(rt, 0, 2)},{Dot(rt, 1, 2)}) det={determinant} " +
            $"projection=({ofx},{ofy},h={h}){inputs}");
    }

    static string InputPoint(IMemory m, uint inputBase, uint index, bool nearPrecision)
    {
        uint input = inputBase + index * 8u;
        int x = unchecked((short)m.ReadU16(input));
        int y = unchecked((short)m.ReadU16(input + 2u));
        int z = unchecked((short)m.ReadU16(input + 4u));
        if (nearPrecision)
            return $"({x},{y},{z})";

        // func_8007B798 consumes signed 12-bit fixed-point fields.  The original
        // MIPS shifts expose exactly this representation to the GTE.
        x = unchecked((short)((m.ReadU16(input) & 0x0FFFu) << 4));
        y >>= 4;
        z = unchecked((short)((m.ReadU16(input + 4u) & 0x0FFFu) << 4));
        return $"({x},{y},{z})";
    }
}
