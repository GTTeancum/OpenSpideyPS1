namespace RecompOne.Runtime.Context;

public sealed class CpuContext
{
    private uint[] _gpr = new uint[32];
    private readonly float[] _gteDepth = new float[32];
    private readonly float[] _gteScreenX = new float[32];
    private readonly float[] _gteScreenY = new float[32];
    private readonly bool[] _gteHasSubpixel = new bool[32];

    uint Get(int index) => _gpr[index];
    void Set(int index, uint value)
    {
        _gpr[index] = value;
        ClearGteTag(index);
    }

    void ClearGteTag(int index)
    {
        _gteDepth[index] = 0f;
        _gteScreenX[index] = _gteScreenY[index] = 0f;
        _gteHasSubpixel[index] = false;
    }

    public uint At { get => Get(1); set => Set(1, value); }
    public uint V0 { get => Get(2); set => Set(2, value); }
    public uint V1 { get => Get(3); set => Set(3, value); }
    public uint A0 { get => Get(4); set => Set(4, value); }
    public uint A1 { get => Get(5); set => Set(5, value); }
    public uint A2 { get => Get(6); set => Set(6, value); }
    public uint A3 { get => Get(7); set => Set(7, value); }
    public uint T0 { get => Get(8); set => Set(8, value); }
    public uint T1 { get => Get(9); set => Set(9, value); }
    public uint T2 { get => Get(10); set => Set(10, value); }
    public uint T3 { get => Get(11); set => Set(11, value); }
    public uint T4 { get => Get(12); set => Set(12, value); }
    public uint T5 { get => Get(13); set => Set(13, value); }
    public uint T6 { get => Get(14); set => Set(14, value); }
    public uint T7 { get => Get(15); set => Set(15, value); }
    public uint S0 { get => Get(16); set => Set(16, value); }
    public uint S1 { get => Get(17); set => Set(17, value); }
    public uint S2 { get => Get(18); set => Set(18, value); }
    public uint S3 { get => Get(19); set => Set(19, value); }
    public uint S4 { get => Get(20); set => Set(20, value); }
    public uint S5 { get => Get(21); set => Set(21, value); }
    public uint S6 { get => Get(22); set => Set(22, value); }
    public uint S7 { get => Get(23); set => Set(23, value); }
    public uint T8 { get => Get(24); set => Set(24, value); }
    public uint T9 { get => Get(25); set => Set(25, value); }
    public uint K0 { get => Get(26); set => Set(26, value); }
    public uint K1 { get => Get(27); set => Set(27, value); }
    public uint GP { get => Get(28); set => Set(28, value); }
    public uint SP { get => Get(29); set => Set(29, value); }
    public uint FP { get => Get(30); set => Set(30, value); }
    public uint RA { get => Get(31); set => Set(31, value); }

    public uint HI;
    public uint LO;
    
    public uint SR; 
    public uint Cause; 
    public uint EPC;
    public uint BadVAddr; 
    public uint PRId; 
    
    public uint this[int index]
    {
        get => index == 0 ? 0u : _gpr[index];
        set { if (index != 0) Set(index, value); }
    }

    public void SetGteRead(int index, uint value,
        Hardware.GteScreen.VertexTag tag)
    {
        if (index == 0) return;
        _gpr[index] = value;
        _gteDepth[index] = tag.Depth;
        _gteScreenX[index] = tag.ScreenX;
        _gteScreenY[index] = tag.ScreenY;
        _gteHasSubpixel[index] = tag.HasSubpixel;
    }

    public void MoveGpr(int destination, int source)
    {
        if (destination == 0) return;
        _gpr[destination] = source == 0 ? 0u : _gpr[source];
        _gteDepth[destination] = source == 0 ? 0f : _gteDepth[source];
        _gteScreenX[destination] = source == 0 ? 0f : _gteScreenX[source];
        _gteScreenY[destination] = source == 0 ? 0f : _gteScreenY[source];
        _gteHasSubpixel[destination] = source != 0 && _gteHasSubpixel[source];
    }

    public void SetDerived(int destination, uint value, int source)
    {
        if (destination == 0) return;
        _gpr[destination] = value;
        _gteDepth[destination] = source == 0 ? 0f : _gteDepth[source];
        _gteScreenX[destination] = _gteScreenY[destination] = 0f;
        _gteHasSubpixel[destination] = false;
    }

    public void SetDerived(int destination, uint value, int sourceA, int sourceB)
    {
        if (destination == 0) return;
        _gpr[destination] = value;
        float a = sourceA == 0 ? 0f : _gteDepth[sourceA];
        float b = sourceB == 0 ? 0f : _gteDepth[sourceB];
        _gteDepth[destination] = a <= 0f ? b : b <= 0f || a == b ? a : 0f;
        _gteScreenX[destination] = _gteScreenY[destination] = 0f;
        _gteHasSubpixel[destination] = false;
    }

    public float GetGteDepth(int index) => index == 0 ? 0f : _gteDepth[index];

    public Hardware.GteScreen.VertexTag GetGteVertexTag(int index) => index == 0
        ? default
        : new(_gteDepth[index], _gteScreenX[index], _gteScreenY[index],
            _gteHasSubpixel[index]);

    public (uint[] gpr, uint hi, uint lo) Snapshot() => ((uint[])_gpr.Clone(), HI, LO);

    public void Restore((uint[] gpr, uint hi, uint lo) s)
    {
        Array.Copy(s.gpr, _gpr, 32);
        Array.Clear(_gteDepth);
        Array.Clear(_gteScreenX);
        Array.Clear(_gteScreenY);
        Array.Clear(_gteHasSubpixel);
        HI = s.hi;
        LO = s.lo;
    }
}
