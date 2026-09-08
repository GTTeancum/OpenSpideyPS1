using System;
using RecompOne.Runtime;
using RecompOne.Runtime.Context;
using RecompOne.Runtime.Memory;
using RecompOne.Runtime.Hle;

namespace Recompiled;

/// <summary>Keep SM1's object bounds tests consistent with horizontal projection.</summary>
public static class WorldFrustum
{
    static readonly uint[] Saved = new uint[5];
    static bool changed;

    public static void Enter(CpuContext c, IMemory m)
    {
        changed = GpuHle.FovNum != GpuHle.FovDen;
        if (!changed) return;
        Span<short> matrix = stackalloc short[10];
        for (int i=0;i<5;i++)
        {
            uint word=Saved[i]=Gte.ReadControl(16+i);
            matrix[2*i]=(short)word;
            matrix[2*i+1]=(short)(word>>16);
        }
        // The color matrix contains the bottom, left and right inward planes.
        // Their sum is the forward component; their difference is horizontal.
        // Widen only that horizontal component, then normalize so the native
        // sphere-radius and bounding-box tests retain the same units.
        Span<double> left=stackalloc double[3], right=stackalloc double[3];
        double ratio=(double)GpuHle.FovNum/GpuHle.FovDen;
        double ll=0, rr=0;
        for(int i=0;i<3;i++)
        {
            double forward=(matrix[3+i]+matrix[6+i])*0.5;
            double horizontal=(matrix[3+i]-matrix[6+i])*0.5*ratio;
            left[i]=forward+horizontal; right[i]=forward-horizontal;
            ll+=left[i]*left[i]; rr+=right[i]*right[i];
        }
        for(int i=0;i<3;i++)
        {
            matrix[3+i]=(short)Math.Round(left[i]*4096/Math.Sqrt(ll));
            matrix[6+i]=(short)Math.Round(right[i]*4096/Math.Sqrt(rr));
        }
        for(int i=0;i<5;i++)
            Gte.WriteControl(16+i,(ushort)matrix[2*i]|((uint)(ushort)matrix[2*i+1]<<16));
    }

    public static void Exit(CpuContext c, IMemory m)
    {
        if (!changed) return;
        for(int i=0;i<5;i++) Gte.WriteControl(16+i,Saved[i]);
        changed=false;
    }
}
