using System;
using RecompOne.Runtime.Events;
using RecompOne.Runtime.Hle;
using RecompOne.Runtime.Sdk;

namespace Recompiled;

/// <summary>
/// 16:9 widescreen.
///
/// The field of view is widened at the projection, not at the framebuffer. The game
/// decides what to draw from the coordinates the GTE produces, so squeezing projected X
/// toward the centre by 3/4 means its own object selection, clipping and ordering all
/// work on the wider view and it submits the extra scenery itself. The 4:3 framebuffer
/// is then presented at 16:9, which stretches the squeeze back out.
///
/// The alternative -- widening the framebuffer and letting the game carry on drawing for
/// 4:3 -- was tried at length and does not work. The renderer can be given the room, but
/// the game never sends geometry for it: the margins came up as wedges of flat
/// background in the lower corners, worst near the camera, and suppressing the clear
/// only replaced them with the previous frame's pixels smearing. Nothing downstream can
/// invent geometry the game did not submit.
///
/// The cost is horizontal resolution: 512 pixels now cover a 16:9 screen instead of 4:3,
/// so the picture is a little softer. Everything is drawn, and drawn once.
/// </summary>
public static class Wide
{
    /// <summary>
    /// The gameplay loop's buffer swap, at 0x8002C2AC. Identified positively rather than
    /// by excluding the menus: the menu swap arrives through a path where the saved
    /// return address is not at sp+16, so reading it there yields a junk value.
    ///
    /// In-engine cutscenes run through this same loop and widen with gameplay. FMV needs
    /// no special case -- it presents through the 24-bit path.
    /// </summary>
    const uint GameplaySwap = 0x8002C2AC;

    public static bool Enabled { get; private set; }

    static float _aspect;
    static int _num = 3, _den = 4;

    public static void Install()
    {
        // Before the widescreen bail-out, so the same measurement can be taken in 4:3.
        // SPIDEY_WIDE_DEBUG=1 paints the background fill magenta, which is the only way
        // to tell ground the frame never covered from geometry that was drawn and is
        // simply dark. The switch was documented but nothing set the flag.
        RecompOne.Runtime.Diagnostics.DrawEnvWarn.TintBackground =
            Environment.GetEnvironmentVariable("SPIDEY_WIDE_DEBUG") == "1";

        if (Environment.GetEnvironmentVariable("SPIDEY_WIDE") != "1") return;
        Enabled = true;

        var a = Environment.GetEnvironmentVariable("SPIDEY_WIDE_ASPECT");
        _aspect = float.TryParse(a, out float f) && f > 1.3f && f < 3f ? f : 16f / 9f;

        // 4:3 of field of view has to fit into the same framebuffer as the target
        // aspect, so the squeeze is the ratio between them.
        _num = 1000;
        _den = (int)MathF.Round(1000f * _aspect / GpuHle.BaseAspect);

        RecompOne.Runtime.Hardware.GteScreen.Tracking = true;
        _legacy = Environment.GetEnvironmentVariable("SPIDEY_WIDE_LEGACY") == "1";
        if (_legacy) Console.WriteLine("[wide] legacy HUD rules: shape and position only");

        Event.AddListener<VSyncEvent>(_ => Follow());
        Event.AddListener<RenderPrimEvent>(Screen);
        Console.WriteLine($"[wide] aspect {_aspect:F3}, fov x{_num}/{_den}, gameplay only");
    }

    /// <summary>
    /// Widen for gameplay, and hand back the console's own 4:3 everywhere else, which
    /// the window then pillarboxes.
    /// </summary>
    static void Follow()
    {
        bool wide = LibGpu.LastDispGrandparent == GameplaySwap;

        GpuHle.FovNum = wide ? _num : 1;
        GpuHle.FovDen = wide ? _den : 1;
        RollElements();

        // The recorded projection output belongs to one frame; see GteScreen.
        RecompOne.Runtime.Hardware.GteScreen.Roll();

        if (RecompOne.Runtime.Diagnostics.DrawEnvWarn.TintBackground && ++_frames % 600 == 0)
            Console.WriteLine($"[wide] world primitives rescued from the HUD rules so far: {_rescued}");

        // No margin: the framebuffer keeps the size the game expects, and only the
        // aspect it is presented at changes. That is what keeps the edges free of the
        // uncleared, never-drawn strip the margin approach left behind.
        float want = wide ? _aspect : GpuHle.BaseAspect;
        if (GpuHle.SourceAspect != want) GpuHle.SourceAspect = want;
    }

    /// <summary>
    /// Squeeze the HUD to match, so the stretch at presentation leaves it the shape the
    /// game drew and sitting where the 4:3 layout intends -- against the edges, which on
    /// a wider screen means further out.
    ///
    /// The HUD does not come through the GTE, so it is not squeezed with the world and
    /// would otherwise be stretched by a third. Scaling every vertex about the centre of
    /// the drawing area is a single uniform transform, so elements built from several
    /// quads stay joined -- which is where a per-element shift kept tearing the health
    /// bar apart -- and anything the game centred stays centred.
    /// </summary>
    static void Screen(RenderPrimEvent e)
    {
        if (!Enabled || GpuHle.FovNum == GpuHle.FovDen) return;

        // World geometry, and nothing else, arrives by way of the GTE. Everything below
        // this line is guesswork from shape and screen position, and guesswork is what
        // dragged the building sign's letters into the corner on top of the health bar:
        // they are axis-aligned quads in the corner the HUD occupies, which is precisely
        // what the HUD test looks for. Asking where the vertices came from settles it
        // without a heuristic.
        // SPIDEY_WIDE_LEGACY=1 puts the shape-only rules back, so the two can be run
        // against the same recording from one build and compared.
        if (!_legacy && FromGte(e))
        {
            // How much damage the shape test was doing on its own: world geometry that
            // the HUD rules would have claimed and moved.
            if (Rescued(e)) _rescued++;
            return;
        }

        int lo = e.X[0], hi = e.X[0], top = e.Y[0], bot = e.Y[0];
        for (int i = 1; i < e.Count; i++)
        {
            if (e.X[i] < lo) lo = e.X[i];
            if (e.X[i] > hi) hi = e.X[i];
            if (e.Y[i] < top) top = e.Y[i];
            if (e.Y[i] > bot) bot = e.Y[i];
        }

        // Everything below works in buffer-relative coordinates. The game double
        // buffers, so alternate frames draw at y offset 0 and 256; storing boxes with
        // the offset baked in meant a box recorded on one frame could never contain
        // anything on the next, and the needle was never matched to its ring.
        int rlo = lo - e.DrawLeft, rhi = hi - e.DrawLeft;
        int rtop = top - e.DrawTop, rbot = bot - e.DrawTop;

        int w = e.DrawRight - e.DrawLeft + 1, h = e.DrawBottom - e.DrawTop + 1;
        bool panel = IsScreenAligned(e) && InHudCorner(rlo, rhi, rtop, rbot, w, h);
        int host = panel ? -1 : CarryHost(rlo, rhi, rtop, rbot);
        if (!panel && host < 0) return;

        // One anchor per element, taken from the element's own box, so every quad of it
        // moves identically. Deciding per primitive is what tore the health bar apart:
        // it spans a boundary, so its quads disagreed about which way to go.
        // A carried detail takes the anchor of the element it belongs to. Working it out
        // independently is how the compass needle kept ending up beside its ring instead
        // of inside it -- the two have to move as one thing.
        int anchor = host >= 0 ? AnchorOf(e, host)
                   : (rlo + rhi) / 2 <= w / 2 ? -1 : 1;

        Squeeze(e, anchor);

        // Only element-sized boxes may carry details. The screen-aligned test also picks
        // up full-width and half-width quads from the world, and a half-screen box would
        // adopt anything small that strayed into it.
        if (panel) Remember(rlo, rhi, rtop, rbot, true);
    }

    /// <summary>
    /// Did every vertex of this primitive come out of the GTE this frame?
    ///
    /// Vertices are compared with the draw origin removed, because the GTE records what
    /// it produced and the GPU adds the drawing offset afterwards. Requiring *every*
    /// vertex to match is what makes a false positive negligible: a HUD vertex landing on
    /// a projected one by chance is common enough, all four doing so is not.
    /// </summary>
    static long _rescued, _frames;
    static bool _legacy;

    /// <summary>Would the shape-and-corner rules have claimed this world primitive?</summary>
    static bool Rescued(RenderPrimEvent e)
    {
        int lo = e.X[0], hi = e.X[0], top = e.Y[0], bot = e.Y[0];
        for (int i = 1; i < e.Count; i++)
        {
            if (e.X[i] < lo) lo = e.X[i];
            if (e.X[i] > hi) hi = e.X[i];
            if (e.Y[i] < top) top = e.Y[i];
            if (e.Y[i] > bot) bot = e.Y[i];
        }
        int w = e.DrawRight - e.DrawLeft + 1, h = e.DrawBottom - e.DrawTop + 1;
        int rlo = lo - e.DrawLeft, rhi = hi - e.DrawLeft;
        int rtop = top - e.DrawTop, rbot = bot - e.DrawTop;
        if (IsScreenAligned(e) && InHudCorner(rlo, rhi, rtop, rbot, w, h)) return true;
        return CarryHost(rlo, rhi, rtop, rbot) >= 0;
    }

    static bool FromGte(RenderPrimEvent e)
    {
        for (int i = 0; i < e.Count; i++)
            if (!RecompOne.Runtime.Hardware.GteScreen.Has(e.X[i] - e.DrawLeft, e.Y[i] - e.DrawTop))
                return false;
        return true;
    }

    // Boxes of the HUD elements squeezed so far this frame, so that parts of an element
    // which are not themselves screen-aligned can be squeezed with it.
    // Two generations: boxes are collected during a frame and consulted from the frame
    // before. Within one frame the order is against us -- the compass ring is submitted
    // after its needle, so a needle looking for its ring would never find one. The HUD
    // does not move between frames, so last frame's boxes place it perfectly well.
    const int Elements = 16;
    static readonly int[] _cx0 = new int[Elements], _cx1 = new int[Elements];
    static readonly int[] _cy0 = new int[Elements], _cy1 = new int[Elements];
    static readonly int[] _px0 = new int[Elements], _px1 = new int[Elements];
    static readonly int[] _py0 = new int[Elements], _py1 = new int[Elements];
    static readonly bool[] _ccarry = new bool[Elements], _pcarry = new bool[Elements];
    static int _cur, _prev;

    /// <summary>Widest a primitive can be and still be taken for part of a HUD element.</summary>
    const int MaxDetail = 40;

    /// <summary>
    /// Scale a primitive about an anchor. Squeezing by the same fraction as the world
    /// means presentation stretches it back to the shape the game drew; which anchor is
    /// used decides where it ends up.
    ///
    /// Anchoring to an edge is what pushes the HUD out. Scaling about the frame centre
    /// keeps an element's *fraction* of the frame, which on a wider frame drags it
    /// inward -- the health bar sat at 21.3% of width where 4:3 has it at 11.7%.
    /// Scaling about the near edge instead preserves its distance from that edge, so it
    /// stays where the 4:3 layout puts it and the edge moves out from under it.
    /// </summary>
    static void Squeeze(RenderPrimEvent e, int anchor)
    {
        int n = GpuHle.FovNum, d = GpuHle.FovDen;
        int origin = anchor < 0 ? e.DrawLeft
                   : anchor > 0 ? e.DrawRight
                   : (e.DrawLeft + e.DrawRight) / 2;

        for (int i = 0; i < e.Count; i++)
            e.X[i] = origin + (int)((long)(e.X[i] - origin) * n / d);
    }


    /// <summary>
    /// Is this part of the HUD?
    ///
    /// Shape is the signal: a HUD panel projects to an exact axis-aligned rectangle and
    /// geometry through the GTE effectively never does. Raw texturing was tried as a
    /// cleaner-sounding alternative and is simply wrong for this game -- the HUD is not
    /// drawn raw, so nothing was squeezed and presentation stretched the whole HUD by a
    /// third, which is the oval spider icon and the elongated health bar.
    ///
    /// The needle is the exception that still needs the box test: it rotates, and shares
    /// nothing with the ring except sitting inside it.
    /// </summary>
    /// <summary>
    /// Is this a detail belonging to a HUD element already being squeezed?
    ///
    /// The compass needle rotates, so it never forms an axis-aligned rectangle and is
    /// missed by the shape test -- it stayed at full width beside a squeezed ring. It is
    /// small and sits wholly inside the ring, which is enough to place it, and requiring
    /// containment on both axes is what keeps the world out: a character is built from
    /// small triangles, and matching on width alone dragged them off their model.
    /// </summary>
    /// <summary>
    /// Is this a HUD panel? Shape alone is not enough: the ground is drawn as wide
    /// horizontal strips that project to axis-aligned rectangles just as a HUD panel
    /// does, and squeezing those distorted the floor near the right edge. Requiring an
    /// element-sized rectangle inside the corner the HUD occupies separates the two
    /// cleanly, without depending on draw order or on a flag the world also sets.
    ///
    /// Only the top-left corner -- health and web cartridges -- is moved.
    ///
    /// The compass in the bottom right is deliberately left alone. Its needle rotates,
    /// so it never forms an axis-aligned rectangle and cannot be recognised the same
    /// way; anchoring the ring without it split the compass in two, with the needle
    /// stranded against the ring's edge. Leaving the whole compass where the game puts
    /// it keeps it a single coherent piece, which is worth more than having it against
    /// the frame edge.
    /// </summary>
    static bool InHudCorner(int lo, int hi, int top, int bot, int w, int h)
    {
        if (hi - lo > w / 4 || bot - top > h / 3) return false;

        // Has to hug the corner, not merely fall inside it. The building sign sits high
        // in the frame and its letters are axis-aligned quads like a HUD panel, so a
        // corner region wide enough to hold the whole health display also caught them
        // and pulled letters out of the word.
        return lo <= w / 5 && hi <= w * 2 / 5 && bot <= h * 2 / 5;
    }

    /// <summary>The anchor of a remembered element, so a detail can inherit it.</summary>
    static int AnchorOf(RenderPrimEvent e, int i)
    {
        int w = e.DrawRight - e.DrawLeft + 1;
        return (_px0[i] + _px1[i]) / 2 <= w / 2 ? -1 : 1;
    }

    /// <summary>Which remembered element this detail belongs to, or -1.</summary>
    static int CarryHost(int lo, int hi, int top, int bot)
    {
        if (hi - lo > MaxDetail || bot - top > MaxDetail) return -1;
        // The detail's centre inside the element, with a little slack. The needle pokes
        // past the ring it sits in, so demanding full containment left it behind while
        // the ring moved to the edge without it.
        const int Slack = 12;
        int cx = (lo + hi) / 2, cy = (top + bot) / 2;
        for (int i = 0; i < _prev; i++)
            if (_pcarry[i] &&
                cx >= _px0[i] - Slack && cx <= _px1[i] + Slack &&
                cy >= _py0[i] - Slack && cy <= _py1[i] + Slack) return i;
        return -1;
    }


    static void Remember(int lo, int hi, int top, int bot, bool carry)
    {
        if (_cur >= Elements) return;
        _cx0[_cur] = lo; _cx1[_cur] = hi;
        _cy0[_cur] = top; _cy1[_cur] = bot;
        _ccarry[_cur] = carry;
        _cur++;
    }

    /// <summary>End of frame: this frame's boxes become the ones the next frame reads.</summary>
    static void RollElements()
    {
        System.Array.Copy(_cx0, _px0, _cur); System.Array.Copy(_cx1, _px1, _cur);
        System.Array.Copy(_cy0, _py0, _cur); System.Array.Copy(_cy1, _py1, _cur);
        System.Array.Copy(_ccarry, _pcarry, _cur);
        _prev = _cur;
        _cur = 0;
    }

    /// <summary>
    /// A quad or sprite forming an exact axis-aligned rectangle. The HUD is textured
    /// quads rather than sprites, so vertex count alone does not separate it from the
    /// world; geometry arriving through the GTE effectively never lands on exactly two
    /// distinct X values and two distinct Y values.
    /// </summary>
    static bool IsScreenAligned(RenderPrimEvent e)
    {
        if (e.Count == 2) return true;
        if (e.Count != 4) return false;

        int xs = 1, ys = 1, ox = e.X[0], oy = e.Y[0];
        for (int i = 1; i < 4; i++)
        {
            if (e.X[i] != e.X[0] && e.X[i] != ox) { if (xs == 2) return false; ox = e.X[i]; xs = 2; }
            if (e.Y[i] != e.Y[0] && e.Y[i] != oy) { if (ys == 2) return false; oy = e.Y[i]; ys = 2; }
        }
        return xs == 2 && ys == 2;
    }
}
