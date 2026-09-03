using Silk.NET.OpenGL;

namespace RecompOne.Runtime.Hle;
//the idea is to drop gl45 is gl33 is stable enought, in the future maybe add vulkan and dx backend?
public enum GlBackendKind
{
    Auto,
    Gl45,
    Gl33,
#if RECOMPONE_LEGACY_RENDERER
    Gl21,
#endif
}

public static class GpuBackendFactory //fkn hate these factories
{
    public static GlBackendKind Selected { get; private set; }

    public static IGpuBackend Create(GL gl, GlBackendKind requested)
    {
        bool has45 = Supports45(gl);
        bool has33 = ContextAtLeast(gl, 3, 3);

        GlBackendKind kind = requested == GlBackendKind.Auto
            ? (has45 ? GlBackendKind.Gl45 : GlBackendKind.Gl33)
            : requested;

        if (kind == GlBackendKind.Gl45 && !has45)
        {
            Console.WriteLine("[Gpu] gl45 requested but the support by your gpu is below 4.5, falling back to gl33");
            kind = GlBackendKind.Gl33;
        }
        if (kind == GlBackendKind.Gl33 && !has33)
        {
            throw new NotSupportedException(
                "The modern renderer requires OpenGL 3.3 or newer; the legacy renderer is not part of this build.");
        }

#if RECOMPONE_LEGACY_RENDERER
        if (kind == GlBackendKind.Gl21) ClampScaleToLimit(gl);
#endif

        Selected = kind;
        IGlVram vram = kind switch
        {
            GlBackendKind.Gl45 => new Gl45Vram(gl),
            GlBackendKind.Gl33 => new Gl33Vram(gl),
#if RECOMPONE_LEGACY_RENDERER
            GlBackendKind.Gl21 => new Gl21Vram(gl),
#endif
            _ => throw new InvalidOperationException($"Unsupported renderer backend: {kind}"),
        };
        Console.WriteLine($"[Gpu] backend: {kind}");
#if RECOMPONE_LEGACY_RENDERER
        return new GlCore(gl, vram, kind == GlBackendKind.Gl21);
#else
        return new GlCore(gl, vram, legacy: false);
#endif
    }

    static bool ContextAtLeast(GL gl, int wantMajor, int wantMinor)
    {
        try
        {
            int major = gl.GetInteger(GLEnum.MajorVersion);
            int minor = gl.GetInteger(GLEnum.MinorVersion);
            if (major > 0) return major > wantMajor || (major == wantMajor && minor >= wantMinor);
        }
        catch { }

        string version = Str(gl, StringName.Version);
        var parts = version.Split('.', ' ');
        if (parts.Length >= 2 && int.TryParse(parts[0], out int m) && int.TryParse(parts[1], out int n))
            return m > wantMajor || (m == wantMajor && n >= wantMinor);
        return false;
    }

#if RECOMPONE_LEGACY_RENDERER
    // Reference renderer support. This code is absent from normal and shipping builds.
    static void ClampScaleToLimit(GL gl)
    {
        int max;
        try { max = gl.GetInteger(GLEnum.MaxTextureSize); }
        catch { return; }
        if (max <= 0) return;

        while (GlVram.Scale > 1 &&
               (VramShadow.Width * GlVram.Scale > max || VramShadow.Height * GlVram.Scale > max))
        {
            GlVram.Scale /= 2;
            Console.WriteLine($"[Gpu] max texture size support is {max}, dropping the vram scale to {GlVram.Scale}");
        }
    }
#endif

    static bool Supports45(GL gl)
    {
        int major = 0, minor = 0;
        try
        {
            major = gl.GetInteger(GLEnum.MajorVersion);
            minor = gl.GetInteger(GLEnum.MinorVersion);
        }
        catch (Exception e)
        {
            Console.WriteLine($"[Gpu] could not read the context version: {e.Message}");
        }

        string version = Str(gl, StringName.Version);
        string renderer = Str(gl, StringName.Renderer);
        Console.WriteLine($"[Gpu] context: {major}.{minor} ({version}) on {renderer}");

        if (major > 4 || (major == 4 && minor >= 5)) return true;

        bool barrier = HasExtension(gl, "GL_ARB_texture_barrier");
        bool copyImage = HasExtension(gl, "GL_ARB_copy_image");
        if (barrier && copyImage)
        {
            Console.WriteLine("[Gpu] context is below 4.5 but exposes texture barrier and copy image");
            return true;
        }

        Console.WriteLine($"[Gpu] gl45 unavailable (texture barrier: {barrier}, copy image: {copyImage})");
        return false;
    }

    static bool HasExtension(GL gl, string name)
    {
        try
        {
            int count = gl.GetInteger(GLEnum.NumExtensions);
            for (uint i = 0; i < count; i++)
                if (gl.GetStringS(StringName.Extensions, i) == name) return true;
        }
        catch { }
        return false;
    }

    static string Str(GL gl, StringName name)
    {
        try { return gl.GetStringS(name) ?? "?"; }
        catch { return "?"; }
    }

    /// <summary>
    /// Normal builds always choose the best modern backend. A source-only reference
    /// build can deliberately opt into GL 2.1; no user setting exposes this path.
    /// </summary>
    public static GlBackendKind RequestedBackend()
    {
#if RECOMPONE_LEGACY_RENDERER
        if (Environment.GetEnvironmentVariable("RECOMPONE_REFERENCE_RENDERER") == "gl21")
            return GlBackendKind.Gl21;
#endif
        return GlBackendKind.Auto;
    }
}
