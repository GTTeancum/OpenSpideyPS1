using Silk.NET.OpenGL;

namespace RecompOne.Runtime.Hle;

internal static class GlShaders
{
    public const string FullscreenVs = """
        #version 330 core
        layout(location = 0) in vec2 aPos;
        out vec2 vUv;
        void main() {
            vUv = aPos * 0.5 + 0.5;
            gl_Position = vec4(aPos, 0.0, 1.0);
        }
        """;

    public const string PresentFs = """
        #version 330 core
        in vec2 vUv;
        uniform sampler2D uVram;
        uniform vec2 uOrigin;
        uniform vec2 uSize;
        uniform vec2 uTexSize;
        out vec4 oColor;
        void main() {
            vec2 t = (uOrigin + vUv * uSize) / uTexSize;
            oColor = vec4(texture(uVram, t).rgb, 1.0);
        }
        """;

    public const string Present24Fs = """
        #version 330 core
        in vec2 vUv;
        uniform sampler2D uVram;
        uniform vec2 uOrigin;
        uniform vec2 uSize;
        uniform int uScale;
        out vec4 oColor;

        int u5(float f) { return int(floor(f * 31.0 + 0.5)); }
        int texel16(int lin) {
            vec4 p = texelFetch(uVram, ivec2((lin & 1023) * uScale, ((lin >> 10) & 511) * uScale), 0);
            return u5(p.r) | (u5(p.g) << 5) | (u5(p.b) << 10) | (int(ceil(p.a)) << 15);
        }
        int byteAt(int b) {
            int t = texel16(b >> 1);
            return (b & 1) == 0 ? (t & 0xff) : ((t >> 8) & 0xff);
        }
        void main() {
            int px = int(floor(vUv.x * uSize.x));
            int py = int(floor(vUv.y * uSize.y));
            int ty = int(uOrigin.y) + py;
            int base = (ty * 1024 + int(uOrigin.x)) * 2 + px * 3;
            oColor = vec4(float(byteAt(base)) / 255.0, float(byteAt(base + 1)) / 255.0,
                          float(byteAt(base + 2)) / 255.0, 1.0);
        }
        """;

    /// <summary>
    /// Cheap second pass over submitted triangles. Red records visible primitive coverage,
    /// green records visible GTE/world geometry, blue records HUD, and alpha records an
    /// authored transparent texture footprint. Max blending accumulates those facts so
    /// later cut-outs cannot erase earlier visible scene coverage.
    /// </summary>
    public const string CoverageVs = """
        #version 330 core
        layout(location = 0) in vec2 inPos;
        layout(location = 2) in float inClutF;
        layout(location = 3) in float inTexpageF;
        layout(location = 4) in vec2 inUV;
        layout(location = 5) in float inWorld;
        layout(location = 6) in float inHud;
        layout(location = 7) in float inPerspectiveW;
        uniform vec2 uPosBias;
        uniform vec2 uFbInv;
        out vec2 vUV;
        flat out ivec2 clutBase;
        flat out ivec2 pageBase;
        flat out int texMode;
        flat out int vRepClut;
        flat out float vWorld;
        flat out float vHud;
        void main() {
            vec2 p = (inPos + uPosBias) * uFbInv - 1.0;
            float perspectiveW = max(inPerspectiveW, 1.0);
            gl_Position = vec4(p * perspectiveW, 0.0, perspectiveW);
            int inClut = int(inClutF + 0.5);
            int inTexpage = int(inTexpageF + 0.5);
            vUV = inUV;
            vRepClut = (inTexpage >> 12) & 1;
            if ((inTexpage & 0x8000) != 0) texMode = 4;
            else if ((inTexpage & 0x4000) != 0) texMode = 5;
            else if ((inTexpage & 0x2000) != 0) texMode = 6;
            else {
                texMode = (inTexpage >> 7) & 3;
                pageBase = ivec2((inTexpage & 0xf) * 64, ((inTexpage >> 4) & 1) * 256);
                clutBase = ivec2((inClut & 0x3f) * 16, (inClut >> 6) & 0x1ff);
            }
            vWorld = inWorld;
            vHud = inHud;
        }
        """;

    public const string CoverageFs = """
        #version 330 core
        in vec2 vUV;
        flat in ivec2 clutBase;
        flat in ivec2 pageBase;
        flat in int texMode;
        flat in int vRepClut;
        flat in float vWorld;
        flat in float vHud;
        uniform sampler2D uVram;
        uniform sampler2D uExtTex;
        uniform sampler2D uRepTex;
        uniform sampler2D uRepClut;
        uniform vec4 uRepRect;
        uniform float uRepClutCount;
        uniform ivec4 uTexWindow;
        uniform int uScale;
        out vec4 oColor;

        int u5(float f) { return int(floor(f * 31.0 + 0.5)); }
        vec4 fetch(ivec2 c) { return texelFetch(uVram, (c & ivec2(1023, 511)) * uScale, 0); }
        int fetch16(ivec2 c) {
            vec4 p = fetch(c);
            return u5(p.r) | (u5(p.g) << 5) | (u5(p.b) << 10) | (int(ceil(p.a)) << 15);
        }

        void main() {
            bool visible = true;
            if (texMode == 5) {
                visible = texture(uExtTex, vUV).a >= 0.5;
            } else if (texMode != 4) {
                int rawU = dFdx(vUV.x) < 0.0 ? int(ceil(vUV.x - 0.0001)) : int(floor(vUV.x + 0.0001));
                int rawV = dFdy(vUV.y) < 0.0 ? int(ceil(vUV.y - 0.0001)) : int(floor(vUV.y + 0.0001));
                ivec2 uv = (ivec2(rawU, rawV) & uTexWindow.xy) | uTexWindow.zw;
                uv &= ivec2(0xff);
                if (texMode == 6) {
                    vec2 win = vec2(uTexWindow.xy) + 1.0;
                    vec2 fuv = mod(vUV, win) + vec2(uTexWindow.zw);
                    vec2 t = (fuv - uRepRect.xy) / uRepRect.zw;
                    visible = texture(uRepTex, t).a >= 0.5;
                } else {
                    vec4 texel;
                    if (texMode == 0) {
                        int s = fetch16(ivec2(pageBase.x + (uv.x >> 2), pageBase.y + uv.y));
                        int idx = (s >> ((uv.x & 3) << 2)) & 0xf;
                        texel = vRepClut != 0
                            ? texture(uRepClut, vec2((float(idx) + 0.5) / uRepClutCount, 0.5))
                            : fetch(ivec2(clutBase.x + idx, clutBase.y));
                    } else if (texMode == 1) {
                        int s = fetch16(ivec2(pageBase.x + (uv.x >> 1), pageBase.y + uv.y));
                        int idx = (s >> ((uv.x & 1) << 3)) & 0xff;
                        texel = vRepClut != 0
                            ? texture(uRepClut, vec2((float(idx) + 0.5) / uRepClutCount, 0.5))
                            : fetch(ivec2(clutBase.x + idx, clutBase.y));
                    } else {
                        texel = fetch(ivec2(pageBase.x + uv.x, pageBase.y + uv.y));
                    }
                    if (vRepClut != 0 && texMode != 2) {
                        visible = texel.a >= 0.5;
                    } else visible = texel.rgb != vec3(0.0) || texel.a >= 0.5;
                }
            }
            oColor = visible
                ? vec4(1.0, vWorld, vHud, 0.0)
                : vec4(0.0, 0.0, 0.0, 1.0);
        }
        """;

    /// <summary>
    /// Copy the already-rendered color beneath exact GTE geometry into a HUD-free
    /// companion texture. Geometry provides the footprint; sampling the completed
    /// render target preserves the real texture, lighting, and blend result.
    /// </summary>
    public const string WorldCopyFs = """
        #version 330 core
        flat in float vWorld;
        uniform sampler2D uRendered;
        uniform ivec2 uRenderedSize;
        out vec4 oColor;
        void main() {
            if (vWorld < 0.5) discard;
            ivec2 p = clamp(ivec2(gl_FragCoord.xy), ivec2(0), uRenderedSize - 1);
            oColor = texelFetch(uRendered, p, 0);
        }
        """;

    /// <summary>
    /// Resolve only untouched pixels in the horizontal area a wider camera adds.
    /// Submitted pixels are unchanged, enclosed one-pixel cracks borrow an adjacent
    /// world pixel, and an unmodeled side band may continue only the HUD-free world
    /// color present at the original authored-view boundary. This avoids treating
    /// screen-space HUD or an arbitrary nearby scene pixel as missing geometry.
    /// </summary>
    public const string WideCompleteFs = """
        #version 330 core
        in vec2 vUv;
        uniform sampler2D uTex;
        uniform sampler2D uCoverage;
        uniform sampler2D uWorld;
        uniform vec2 uTexSize;
        uniform float uBaseFraction;
        uniform float uDebugCoverage;
        uniform vec3 uClearColor;
        uniform vec3 uDrawClear;
        uniform float uDiagnosticClear;
        out vec4 oColor;

        bool sourceAt(ivec2 p, ivec2 size) {
            if (p.x < 0 || p.y < 0 || p.x >= size.x || p.y >= size.y) return false;
            vec3 coverage = texelFetch(uCoverage, p, 0).rgb;
            // Side completion may borrow only from GTE-proven world geometry. A
            // visible-but-unclassified screen primitive can be a moving HUD part;
            // treating it as scenery produced horizontal health-bar smears at the
            // widened edge during SM2's damage animation.
            return coverage.g > 0.5 && coverage.b < 0.5;
        }

        bool drawnAt(ivec2 p, ivec2 size) {
            if (p.x < 0 || p.y < 0 || p.x >= size.x || p.y >= size.y) return false;
            vec3 color = texelFetch(uTex, p, 0).rgb;
            vec3 axis = uDrawClear - uClearColor;
            float axis2 = dot(axis, axis);
            if (axis2 > 0.01) {
                // Linear presentation sampling creates a fringe between the diagnostic
                // clear and the authored clear. Recognize only that color line, not
                // arbitrary scene colors which happen to share one channel.
                float t = clamp(dot(color - uClearColor, axis) / axis2, 0.0, 1.0);
                vec3 onLine = uClearColor + axis * t;
                if (distance(color, onLine) <= 8.0 / 255.0) return false;
            }
            return any(greaterThan(abs(color - uDrawClear), vec3(0.5 / 255.0)));
        }

        void main() {
            ivec2 size = ivec2(uTexSize);
            ivec2 p = clamp(ivec2(floor(vUv * uTexSize)), ivec2(0), size - 1);
            vec4 base = texelFetch(uTex, p, 0);
            if (uDebugCoverage > 0.5) {
                vec3 coverage = texelFetch(uCoverage, p, 0).rgb;
                oColor = vec4(coverage, 1.0);
                return;
            }
            float side = (1.0 - uBaseFraction) * 0.5;
            bool addedSide = vUv.x < side || vUv.x > 1.0 - side;
            vec4 here = texelFetch(uCoverage, p, 0);
            if (here.r > 0.5 && (drawnAt(p, size) || addedSide)) {
                oColor = base;
                return;
            }
            if (here.a > 0.5) {
                oColor = vec4(uClearColor, 1.0);
                return;
            }

            // Integer projection can leave a one-pixel stair-step crack where two
            // authored surfaces still meet. Repair only pixels enclosed by visible
            // scene coverage on opposite sides; broad clear areas and open sky cannot
            // satisfy this test.
            ivec2 enclosedSource = p;
            bool enclosed = false;
            if (sourceAt(p + ivec2(-1, 0), size) && sourceAt(p + ivec2(1, 0), size)) {
                enclosedSource = p + ivec2(-1, 0);
                enclosed = true;
            } else if (sourceAt(p + ivec2(0, -1), size) && sourceAt(p + ivec2(0, 1), size)) {
                enclosedSource = p + ivec2(0, -1);
                enclosed = true;
            }
            if (!addedSide) {
                oColor = enclosed ? texelFetch(uTex, enclosedSource, 0)
                    : uDiagnosticClear > 0.5 && !drawnAt(p, size)
                        ? vec4(1.0, 0.0, 1.0, 1.0) : base;
                return;
            }

            // The level may simply have no mesh outside its original 4:3 camera.
            // Continue the world pixel at that authored-view boundary, but only when
            // coverage proves it is GTE world geometry. This is constant work and
            // cannot pull animated HUD art into the side band.
            int boundaryX = vUv.x < 0.5
                ? int(floor(side * uTexSize.x))
                : int(ceil((1.0 - side) * uTexSize.x)) - 1;
            ivec2 boundary = ivec2(clamp(boundaryX, 0, size.x - 1), p.y);
            oColor = sourceAt(boundary, size) ? texelFetch(uWorld, boundary, 0)
                : uDiagnosticClear > 0.5 && !drawnAt(p, size)
                    ? vec4(1.0, 0.0, 1.0, 1.0)
                    : vec4(uClearColor, 1.0);
        }
        """;

    /// <summary>
    /// FXAA 3-style edge search. It runs on the host-resolution presentation texture,
    /// after any user post-process, so polygon edges are smoothed without lowering the
    /// internal render resolution or changing texture filtering.
    /// </summary>
    public const string FxaaFs = """
        #version 330 core
        in vec2 vUv;
        uniform sampler2D uTex;
        uniform vec2 uTexSize;
        out vec4 oColor;

        float luma(vec3 c) { return dot(c, vec3(0.299, 0.587, 0.114)); }

        void main() {
            vec2 px = 1.0 / uTexSize;
            vec3 nw = texture(uTex, vUv + vec2(-1.0, -1.0) * px).rgb;
            vec3 ne = texture(uTex, vUv + vec2( 1.0, -1.0) * px).rgb;
            vec3 sw = texture(uTex, vUv + vec2(-1.0,  1.0) * px).rgb;
            vec3 se = texture(uTex, vUv + vec2( 1.0,  1.0) * px).rgb;
            vec4 center = texture(uTex, vUv);

            float lnw = luma(nw), lne = luma(ne), lsw = luma(sw), lse = luma(se);
            float lm = luma(center.rgb);
            float lo = min(lm, min(min(lnw, lne), min(lsw, lse)));
            float hi = max(lm, max(max(lnw, lne), max(lsw, lse)));
            if (hi - lo < max(0.0312, hi * 0.125)) {
                oColor = center;
                return;
            }

            vec2 dir;
            dir.x = -((lnw + lne) - (lsw + lse));
            dir.y =  ((lnw + lsw) - (lne + lse));
            float reduce = max((lnw + lne + lsw + lse) * (0.25 * 0.125), 1.0 / 128.0);
            float invMin = 1.0 / (min(abs(dir.x), abs(dir.y)) + reduce);
            dir = clamp(dir * invMin, vec2(-8.0), vec2(8.0)) * px;

            vec3 a = 0.5 * (
                texture(uTex, vUv + dir * (1.0 / 3.0 - 0.5)).rgb +
                texture(uTex, vUv + dir * (2.0 / 3.0 - 0.5)).rgb);
            vec3 b = a * 0.5 + 0.25 * (
                texture(uTex, vUv + dir * -0.5).rgb +
                texture(uTex, vUv + dir *  0.5).rgb);
            float lb = luma(b);
            oColor = vec4(lb < lo || lb > hi ? a : b, center.a);
        }
        """;

    public const string PrimVs = """
        #version 330 core
        layout(location = 0) in vec2  inPos;
        layout(location = 1) in vec3  inColorF;
        layout(location = 2) in float inClutF;
        layout(location = 3) in float inTexpageF;
        layout(location = 4) in vec2  inUV;
        layout(location = 7) in float inPerspectiveW;

        out vec4 vColor;
        out vec2 vUV;
        out float vAffineW;
        flat out ivec2 clutBase;
        flat out ivec2 pageBase;
        flat out int   texMode;
        flat out int   vRepClut;

        uniform vec2 uVertexOffset;
        uniform vec2 uPosBias;
        uniform vec2 uFbInv;

        void main() {
            vec2 p = (inPos + uVertexOffset + uPosBias) * uFbInv - 1.0;
            float perspectiveW = max(inPerspectiveW, 1.0);
            gl_Position = vec4(p * perspectiveW, 0.0, perspectiveW);

            int inClut = int(inClutF + 0.5);
            int inTexpage = int(inTexpageF + 0.5);

            vColor = (vec4(inColorF, 0.0) / 255.0) * perspectiveW;
            vAffineW = perspectiveW;
            vRepClut = (inTexpage >> 12) & 1;

            if ((inTexpage & 0x8000) != 0) {
                texMode = 4;
            } else if ((inTexpage & 0x4000) != 0) {
                texMode = 5;
                vUV = inUV;
            } else if ((inTexpage & 0x2000) != 0) {
                texMode = 6;
                vUV = inUV;
            } else {
                texMode = (inTexpage >> 7) & 3;
                vUV = inUV;
                pageBase = ivec2((inTexpage & 0xf) * 64, ((inTexpage >> 4) & 1) * 256);
                clutBase = ivec2((inClut & 0x3f) * 16, (inClut >> 6) & 0x1ff);
            }
        }
        """;

    public const string PrimFs = """
        #version 330 core
        in vec4 vColor;
        in vec2 vUV;
        in float vAffineW;
        flat in ivec2 clutBase;
        flat in ivec2 pageBase;
        flat in int   texMode;
        flat in int   vRepClut;

        layout(location = 0, index = 0) out vec4 FragColor;
        layout(location = 0, index = 1) out vec4 BlendColor;

        uniform sampler2D uVram;
        uniform sampler2D uDest;
        uniform sampler2D uExtTex;
        uniform sampler2D uRepTex;
        uniform sampler2D uRepClut;
        uniform vec4  uRepRect;
        uniform float uRepClutCount;
        uniform ivec4 uTexWindow;
        uniform vec4  uBlend;
        uniform vec4  uBlendOpaque = vec4(1.0, 1.0, 1.0, 0.0);
        uniform float uSetMask;
        uniform int   uCheckMask;
        uniform int   uScale;
        uniform vec2  uPosBias;

        int u5(float f) { return int(floor(f * 31.0 + 0.5)); }
        vec4 fetch(ivec2 c) { return texelFetch(uVram, (c & ivec2(1023, 511)) * uScale, 0); }
        int fetch16(ivec2 c) {
            vec4 p = fetch(c);
            return u5(p.r) | (u5(p.g) << 5) | (u5(p.b) << 10) | (int(ceil(p.a)) << 15);
        }
        vec3 fullColor(ivec3 c8) { return vec3(clamp(c8, 0, 255)) / 255.0; }

        void main() {
            vec4 affineColor = vColor / max(vAffineW, 0.000001);
            if (uCheckMask != 0 && texelFetch(uDest, ivec2(gl_FragCoord.xy), 0).a >= 0.5) discard;

            if (texMode == 4) {
                FragColor = vec4(fullColor(ivec3(affineColor.rgb * 255.0 + 0.5)), uSetMask);
                BlendColor = uBlend;
                return;
            }

            if (texMode == 5) {
                vec4 img = texture(uExtTex, vUV);
                if (img.a < 0.5) discard;
                ivec3 e8 = (ivec3(img.rgb * 255.0 + 0.5) * ivec3(affineColor.rgb * 255.0 + 0.5)) >> 7;
                FragColor = vec4(fullColor(e8), uSetMask);
                BlendColor = uBlend;
                return;
            }

            int rawU = dFdx(vUV.x) < 0.0 ? int(ceil(vUV.x - 0.0001)) : int(floor(vUV.x + 0.0001));
            int rawV = dFdy(vUV.y) < 0.0 ? int(ceil(vUV.y - 0.0001)) : int(floor(vUV.y + 0.0001));
            ivec2 uv = (ivec2(rawU, rawV) & uTexWindow.xy) | uTexWindow.zw;
            uv &= ivec2(0xff);

            if (texMode == 6) {
                vec2 win = vec2(uTexWindow.xy) + 1.0;
                vec2 fuv = mod(vUV, win) + vec2(uTexWindow.zw);
                vec2 t = (fuv - uRepRect.xy) / uRepRect.zw;
                vec4 img = texture(uRepTex, t);
                if (img.a < 0.5) discard;
                vec3 straightRgb = img.rgb / max(img.a, 0.000001);
                ivec3 e8 = (ivec3(straightRgb * 255.0 + 0.5) * ivec3(affineColor.rgb * 255.0 + 0.5)) >> 7;
                float stp = img.a < 0.95 ? 1.0 : 0.0;
                // Replacement art is host-GPU data, not PS1 VRAM data. Keep
                // the full 8-bit result instead of applying console-era
                // framebuffer quantization to the upgraded texture.
                FragColor = vec4(vec3(clamp(e8, 0, 255)) / 255.0, max(stp, uSetMask));
                BlendColor = stp > 0.5 ? uBlend : uBlendOpaque;
                return;
            }

            vec4 texel;

            if (texMode == 0) {
                int s = fetch16(ivec2(pageBase.x + (uv.x >> 2), pageBase.y + uv.y));
                int idx = (s >> ((uv.x & 3) << 2)) & 0xf;
                texel = vRepClut != 0
                    ? texture(uRepClut, vec2((float(idx) + 0.5) / uRepClutCount, 0.5))
                    : fetch(ivec2(clutBase.x + idx, clutBase.y));
            } else if (texMode == 1) {
                int s = fetch16(ivec2(pageBase.x + (uv.x >> 1), pageBase.y + uv.y));
                int idx = (s >> ((uv.x & 1) << 3)) & 0xff;
                texel = vRepClut != 0
                    ? texture(uRepClut, vec2((float(idx) + 0.5) / uRepClutCount, 0.5))
                    : fetch(ivec2(clutBase.x + idx, clutBase.y));
            } else {
                texel = fetch(ivec2(pageBase.x + uv.x, pageBase.y + uv.y));
            }

            if (vRepClut != 0 && texMode != 2) {
                if (texel.a < 0.5) discard;
                ivec3 e8 = (ivec3(texel.rgb * 255.0 + 0.5) * ivec3(affineColor.rgb * 255.0 + 0.5)) >> 7;
                float stp = texel.a < 0.95 ? 1.0 : 0.0;
                FragColor = vec4(fullColor(e8), max(stp, uSetMask));
                BlendColor = stp > 0.5 ? uBlend : uBlendOpaque;
                return;
            }

            if (texel.rgb == vec3(0.0) && texel.a < 0.5) discard;
            ivec3 t8 = ivec3(texel.rgb * 31.0 + 0.5) << 3;
            ivec3 c8 = (t8 * ivec3(affineColor.rgb * 255.0 + 0.5)) >> 7;
            FragColor = vec4(fullColor(c8), max(texel.a, uSetMask));
            BlendColor = texel.a >= 0.5 ? uBlend : uBlendOpaque;
        }
        """;
    
    public const string FullscreenVs120 = """
        #version 120
        attribute vec2 aPos;
        varying vec2 vUv;
        void main() {
            vUv = aPos * 0.5 + 0.5;
            gl_Position = vec4(aPos, 0.0, 1.0);
        }
        """;

    public const string PresentFs120 = """
        #version 120
        varying vec2 vUv;
        uniform sampler2D uVram;
        uniform vec2 uOrigin;
        uniform vec2 uSize;
        uniform vec2 uTexSize;
        void main() {
            vec2 t = (uOrigin + vUv * uSize) / uTexSize;
            gl_FragColor = vec4(texture2D(uVram, t).rgb, 1.0);
        }
        """;

    public const string Present24Fs120 = """
        #version 120
        varying vec2 vUv;
        uniform sampler2D uVram;
        uniform vec2 uOrigin;
        uniform vec2 uSize;
        uniform vec2 uVramSize;
        uniform float uScale;

        float u5(float f) { return floor(f * 31.0 + 0.5); }

        float texel16(float lin) {
            float x = mod(lin, 1024.0);
            float y = floor(lin / 1024.0);
            vec2 uv = (vec2(x, y) * uScale + 0.5) / uVramSize;
            vec4 p = texture2D(uVram, uv);
            return u5(p.r) + u5(p.g) * 32.0 + u5(p.b) * 1024.0 + ceil(p.a) * 32768.0;
        }

        float byteAt(float b) {
            float t = texel16(floor(b * 0.5));
            return mod(b, 2.0) < 0.5 ? mod(t, 256.0) : floor(t / 256.0);
        }

        void main() {
            float px = floor(vUv.x * uSize.x);
            float py = floor(vUv.y * uSize.y);
            float ty = uOrigin.y + py;
            float base = (ty * 1024.0 + uOrigin.x) * 2.0 + px * 3.0;
            gl_FragColor = vec4(byteAt(base) / 255.0, byteAt(base + 1.0) / 255.0, byteAt(base + 2.0) / 255.0, 1.0);
        }
        """;

    public const string CoverageVs120 = """
        #version 120
        attribute vec2 inPos;
        attribute float inClutF;
        attribute float inTexpageF;
        attribute vec2 inUV;
        attribute float inWorld;
        attribute float inHud;
        attribute float inPerspectiveW;
        uniform vec2 uPosBias;
        uniform vec2 uFbInv;
        varying vec2 vUV;
        varying vec2 vClutBase;
        varying vec2 vPageBase;
        varying float vTexMode;
        varying float vRepClut;
        varying float vWorld;
        varying float vHud;
        float bitAt(float v, float bit) { return floor(mod(v / bit, 2.0)); }
        void main() {
            vec2 p = (inPos + uPosBias) * uFbInv - 1.0;
            float perspectiveW = max(inPerspectiveW, 1.0);
            gl_Position = vec4(p * perspectiveW, 0.0, perspectiveW);
            float tp = floor(inTexpageF + 0.5);
            float clut = floor(inClutF + 0.5);
            vUV = inUV;
            vRepClut = bitAt(tp, 4096.0);
            vClutBase = vec2(0.0);
            vPageBase = vec2(0.0);
            if (bitAt(tp, 32768.0) > 0.5) vTexMode = 4.0;
            else if (bitAt(tp, 16384.0) > 0.5) vTexMode = 5.0;
            else if (bitAt(tp, 8192.0) > 0.5) vTexMode = 6.0;
            else {
                vTexMode = floor(mod(tp / 128.0, 4.0));
                vPageBase = vec2(mod(tp, 16.0) * 64.0, bitAt(tp, 16.0) * 256.0);
                vClutBase = vec2(mod(clut, 64.0) * 16.0, mod(floor(clut / 64.0), 512.0));
            }
            vWorld = inWorld;
            vHud = inHud;
        }
        """;

    public const string CoverageFs120 = """
        #version 120
        varying vec2 vUV;
        varying vec2 vClutBase;
        varying vec2 vPageBase;
        varying float vTexMode;
        varying float vRepClut;
        varying float vWorld;
        varying float vHud;
        uniform sampler2D uVram;
        uniform sampler2D uExtTex;
        uniform sampler2D uRepTex;
        uniform sampler2D uRepClut;
        uniform vec4 uRepRect;
        uniform float uRepClutCount;
        uniform vec4 uTexWindow;
        uniform float uScale;
        uniform vec2 uVramSize;

        float u5(float f) { return floor(f * 31.0 + 0.5); }
        vec4 fetch(vec2 c) {
            vec2 w = vec2(mod(c.x, 1024.0), mod(c.y, 512.0));
            return texture2D(uVram, (w * uScale + 0.5) / uVramSize);
        }
        float fetch16(vec2 c) {
            vec4 p = fetch(c);
            return u5(p.r) + u5(p.g) * 32.0 + u5(p.b) * 1024.0 + ceil(p.a) * 32768.0;
        }

        void main() {
            bool visible = true;
            if (vTexMode > 4.5 && vTexMode < 5.5) {
                visible = texture2D(uExtTex, vUV).a >= 0.5;
            } else if (vTexMode < 3.5 || vTexMode > 4.5) {
                vec2 win = uTexWindow.xy + 1.0;
                vec2 fuv = vec2(mod(vUV.x, win.x), mod(vUV.y, win.y)) + uTexWindow.zw;
                float rawU = dFdx(vUV.x) < 0.0 ? ceil(vUV.x - 0.0001) : floor(vUV.x + 0.0001);
                float rawV = dFdy(vUV.y) < 0.0 ? ceil(vUV.y - 0.0001) : floor(vUV.y + 0.0001);
                if (vTexMode > 5.5) {
                    vec2 t = (fuv - uRepRect.xy) / uRepRect.zw;
                    visible = texture2D(uRepTex, t).a >= 0.5;
                } else {
                    vec2 uv = vec2(mod(rawU, win.x), mod(rawV, win.y)) + uTexWindow.zw;
                    uv = vec2(mod(uv.x, 256.0), mod(uv.y, 256.0));
                    vec4 texel;
                    if (vTexMode < 0.5) {
                        float s = fetch16(vec2(vPageBase.x + floor(uv.x / 4.0), vPageBase.y + uv.y));
                        float lane = mod(uv.x, 4.0);
                        float div = lane < 0.5 ? 1.0 : (lane < 1.5 ? 16.0 : (lane < 2.5 ? 256.0 : 4096.0));
                        float idx = mod(floor(s / div), 16.0);
                        texel = vRepClut > 0.5
                            ? texture2D(uRepClut, vec2((idx + 0.5) / uRepClutCount, 0.5))
                            : fetch(vec2(vClutBase.x + idx, vClutBase.y));
                    } else if (vTexMode < 1.5) {
                        float s = fetch16(vec2(vPageBase.x + floor(uv.x / 2.0), vPageBase.y + uv.y));
                        float div = mod(uv.x, 2.0) < 0.5 ? 1.0 : 256.0;
                        float idx = mod(floor(s / div), 256.0);
                        texel = vRepClut > 0.5
                            ? texture2D(uRepClut, vec2((idx + 0.5) / uRepClutCount, 0.5))
                            : fetch(vec2(vClutBase.x + idx, vClutBase.y));
                    } else {
                        texel = fetch(vec2(vPageBase.x + uv.x, vPageBase.y + uv.y));
                    }
                    if (vRepClut > 0.5 && vTexMode < 1.5) {
                        visible = texel.a >= 0.5;
                    } else visible = texel.r != 0.0 || texel.g != 0.0 ||
                                           texel.b != 0.0 || texel.a >= 0.5;
                }
            }
            gl_FragColor = visible
                ? vec4(1.0, vWorld, vHud, 0.0)
                : vec4(0.0, 0.0, 0.0, 1.0);
        }
        """;

    public const string WorldCopyFs120 = """
        #version 120
        varying float vWorld;
        uniform sampler2D uRendered;
        uniform vec2 uRenderedSize;
        void main() {
            if (vWorld < 0.5) discard;
            gl_FragColor = texture2D(uRendered, gl_FragCoord.xy / uRenderedSize);
        }
        """;

    public const string WideCompleteFs120 = """
        #version 120
        varying vec2 vUv;
        uniform sampler2D uTex;
        uniform sampler2D uCoverage;
        uniform sampler2D uWorld;
        uniform vec2 uTexSize;
        uniform float uBaseFraction;
        uniform float uDebugCoverage;
        uniform vec3 uClearColor;
        uniform vec3 uDrawClear;
        uniform float uDiagnosticClear;

        vec4 at(sampler2D tex, vec2 p) {
            return texture2D(tex, (p + 0.5) / uTexSize);
        }
        bool sourceAt(vec2 p) {
            if (p.x < 0.0 || p.y < 0.0 || p.x >= uTexSize.x || p.y >= uTexSize.y)
                return false;
            vec3 coverage = at(uCoverage, p).rgb;
            return coverage.g > 0.5 && coverage.b < 0.5;
        }

        bool drawnAt(vec2 p) {
            if (p.x < 0.0 || p.y < 0.0 || p.x >= uTexSize.x || p.y >= uTexSize.y) return false;
            vec3 color = at(uTex, p).rgb;
            vec3 axis = uDrawClear - uClearColor;
            float axis2 = dot(axis, axis);
            if (axis2 > 0.01) {
                float t = clamp(dot(color - uClearColor, axis) / axis2, 0.0, 1.0);
                vec3 onLine = uClearColor + axis * t;
                if (distance(color, onLine) <= 8.0 / 255.0) return false;
            }
            vec3 delta = abs(color - uDrawClear);
            return delta.r > 0.5 / 255.0 || delta.g > 0.5 / 255.0 ||
                   delta.b > 0.5 / 255.0;
        }

        void main() {
            vec2 p = clamp(floor(vUv * uTexSize), vec2(0.0), uTexSize - 1.0);
            vec4 base = at(uTex, p);
            if (uDebugCoverage > 0.5) {
                vec3 coverage = at(uCoverage, p).rgb;
                gl_FragColor = vec4(coverage, 1.0);
                return;
            }
            float side = (1.0 - uBaseFraction) * 0.5;
            bool addedSide = vUv.x < side || vUv.x > 1.0 - side;
            vec4 here = at(uCoverage, p);
            if (here.r > 0.5 && (drawnAt(p) || addedSide)) {
                gl_FragColor = base;
                return;
            }
            if (here.a > 0.5) {
                gl_FragColor = vec4(uClearColor, 1.0);
                return;
            }

            vec2 enclosedSource = p;
            bool enclosed = false;
            if (sourceAt(p + vec2(-1.0, 0.0)) && sourceAt(p + vec2(1.0, 0.0))) {
                enclosedSource = p + vec2(-1.0, 0.0);
                enclosed = true;
            } else if (sourceAt(p + vec2(0.0, -1.0)) && sourceAt(p + vec2(0.0, 1.0))) {
                enclosedSource = p + vec2(0.0, -1.0);
                enclosed = true;
            }
            if (!addedSide) {
                gl_FragColor = enclosed ? at(uTex, enclosedSource)
                    : uDiagnosticClear > 0.5 && !drawnAt(p)
                        ? vec4(1.0, 0.0, 1.0, 1.0) : base;
                return;
            }

            float boundaryX = vUv.x < 0.5
                ? floor(side * uTexSize.x)
                : ceil((1.0 - side) * uTexSize.x) - 1.0;
            vec2 boundary = vec2(clamp(boundaryX, 0.0, uTexSize.x - 1.0), p.y);
            gl_FragColor = sourceAt(boundary) ? at(uWorld, boundary)
                : uDiagnosticClear > 0.5 && !drawnAt(p)
                    ? vec4(1.0, 0.0, 1.0, 1.0)
                    : vec4(uClearColor, 1.0);
        }
        """;

    public const string FxaaFs120 = """
        #version 120
        varying vec2 vUv;
        uniform sampler2D uTex;
        uniform vec2 uTexSize;

        float luma(vec3 c) { return dot(c, vec3(0.299, 0.587, 0.114)); }

        void main() {
            vec2 px = 1.0 / uTexSize;
            vec3 nw = texture2D(uTex, vUv + vec2(-1.0, -1.0) * px).rgb;
            vec3 ne = texture2D(uTex, vUv + vec2( 1.0, -1.0) * px).rgb;
            vec3 sw = texture2D(uTex, vUv + vec2(-1.0,  1.0) * px).rgb;
            vec3 se = texture2D(uTex, vUv + vec2( 1.0,  1.0) * px).rgb;
            vec4 center = texture2D(uTex, vUv);

            float lnw = luma(nw), lne = luma(ne), lsw = luma(sw), lse = luma(se);
            float lm = luma(center.rgb);
            float lo = min(lm, min(min(lnw, lne), min(lsw, lse)));
            float hi = max(lm, max(max(lnw, lne), max(lsw, lse)));
            if (hi - lo < max(0.0312, hi * 0.125)) {
                gl_FragColor = center;
                return;
            }

            vec2 dir;
            dir.x = -((lnw + lne) - (lsw + lse));
            dir.y =  ((lnw + lsw) - (lne + lse));
            float reduce = max((lnw + lne + lsw + lse) * (0.25 * 0.125), 1.0 / 128.0);
            float invMin = 1.0 / (min(abs(dir.x), abs(dir.y)) + reduce);
            dir = clamp(dir * invMin, vec2(-8.0), vec2(8.0)) * px;

            vec3 a = 0.5 * (
                texture2D(uTex, vUv + dir * (1.0 / 3.0 - 0.5)).rgb +
                texture2D(uTex, vUv + dir * (2.0 / 3.0 - 0.5)).rgb);
            vec3 b = a * 0.5 + 0.25 * (
                texture2D(uTex, vUv + dir * -0.5).rgb +
                texture2D(uTex, vUv + dir *  0.5).rgb);
            float lb = luma(b);
            gl_FragColor = vec4(lb < lo || lb > hi ? a : b, center.a);
        }
        """;

    public const string BlitVs120 = """
        #version 120
        attribute vec2 aPos;
        uniform vec4 uDstRect;
        uniform vec4 uSrcRect;
        varying vec2 vSrc;
        void main() {
            vec2 unit = aPos * 0.5 + 0.5;
            vSrc = uSrcRect.xy + unit * uSrcRect.zw;
            vec2 p = uDstRect.xy + unit * uDstRect.zw;
            gl_Position = vec4(p * 2.0 - 1.0, 0.0, 1.0);
        }
        """;

    public const string BlitFs120 = """
        #version 120
        varying vec2 vSrc;
        uniform sampler2D uSrc;
        void main() { gl_FragColor = texture2D(uSrc, vSrc); }
        """;

    public const string PrimVs120 = """
        #version 120
        attribute vec2  inPos;
        attribute vec3  inColorF;
        attribute float inClutF;
        attribute float inTexpageF;
        attribute vec2  inUV;
        attribute float inPerspectiveW;

        varying vec4  vColor;
        varying vec2  vUV;
        varying float vAffineW;
        varying vec2  vClutBase;
        varying vec2  vPageBase;
        varying float vTexMode;
        varying float vRepClut;

        uniform vec2 uVertexOffset;
        uniform vec2 uPosBias;
        uniform vec2 uFbInv;

        float bitAt(float v, float bit) { return floor(mod(v / bit, 2.0)); }

        void main() {
            vec2 p = (inPos + uVertexOffset + uPosBias) * uFbInv - 1.0;
            float perspectiveW = max(inPerspectiveW, 1.0);
            gl_Position = vec4(p * perspectiveW, 0.0, perspectiveW);

            float tp = floor(inTexpageF + 0.5);
            float clut = floor(inClutF + 0.5);

            vColor = vec4(inColorF / 255.0, 0.0) * perspectiveW;
            vAffineW = perspectiveW;
            vRepClut = bitAt(tp, 4096.0);
            vUV = inUV;
            vClutBase = vec2(0.0);
            vPageBase = vec2(0.0);

            if (bitAt(tp, 32768.0) > 0.5) {
                vTexMode = 4.0;
            } else if (bitAt(tp, 16384.0) > 0.5) {
                vTexMode = 5.0;
            } else if (bitAt(tp, 8192.0) > 0.5) {
                vTexMode = 6.0;
            } else {
                vTexMode = floor(mod(tp / 128.0, 4.0));
                vPageBase = vec2(mod(tp, 16.0) * 64.0, bitAt(tp, 16.0) * 256.0);
                vClutBase = vec2(mod(clut, 64.0) * 16.0, mod(floor(clut / 64.0), 512.0));
            }
        }
        """;

    //gl 2.1 has no dual source blending =/ has to do by hand
    public const string PrimFs120 = """
        #version 120
        varying vec4  vColor;
        varying vec2  vUV;
        varying float vAffineW;
        varying vec2  vClutBase;
        varying vec2  vPageBase;
        varying float vTexMode;
        varying float vRepClut;

        uniform sampler2D uVram;
        uniform sampler2D uDest;
        uniform sampler2D uExtTex;
        uniform sampler2D uRepTex;
        uniform sampler2D uRepClut;
        uniform vec4  uRepRect;
        uniform float uRepClutCount;
        uniform vec4  uTexWindow;
        uniform float uSetMask;
        uniform float uCheckMask;
        uniform float uScale;
        uniform vec2  uPosBias;
        uniform vec2  uVramSize;
        uniform vec2  uDestSize;
        uniform float uSemiTrans;
        uniform float uBlendMode;

        float u5(float f) { return floor(f * 31.0 + 0.5); }

        vec4 fetch(vec2 c) {
            vec2 w = vec2(mod(c.x, 1024.0), mod(c.y, 512.0));
            return texture2D(uVram, (w * uScale + 0.5) / uVramSize);
        }

        float fetch16(vec2 c) {
            vec4 p = fetch(c);
            return u5(p.r) + u5(p.g) * 32.0 + u5(p.b) * 1024.0 + ceil(p.a) * 32768.0;
        }

        vec3 fullColor(vec3 c8) { return clamp(c8, 0.0, 255.0) / 255.0; }

        vec3 blendWith(vec3 src, vec3 dst) {
            if (uBlendMode < 0.5) return (dst + src) * 0.5;
            if (uBlendMode < 1.5) return dst + src;
            if (uBlendMode < 2.5) return dst - src;
            return dst + src * 0.25;
        }

        void main() {
            vec4 affineColor = vColor / max(vAffineW, 0.000001);
            vec2 destUv = gl_FragCoord.xy / uDestSize;
            vec4 dstTexel = texture2D(uDest, destUv);
            if (uCheckMask > 0.5 && dstTexel.a >= 0.5) discard;

            vec3 rgb;
            float stp;
            float mask;
            float hostReplacement = 0.0;

            if (vTexMode > 3.5 && vTexMode < 4.5) {
                rgb = affineColor.rgb * 255.0;
                stp = 1.0;
                mask = uSetMask;
            } else if (vTexMode > 4.5 && vTexMode < 5.5) {
                vec4 img = texture2D(uExtTex, vUV);
                if (img.a < 0.5) discard;
                rgb = floor(img.rgb * 255.0 + 0.5) * floor(affineColor.rgb * 255.0 + 0.5) / 128.0;
                stp = 1.0;
                mask = uSetMask;
            } else {
                vec2 win = uTexWindow.xy + 1.0;
                vec2 fuv = vec2(mod(vUV.x, win.x), mod(vUV.y, win.y)) + uTexWindow.zw;

        
                float rawU = dFdx(vUV.x) < 0.0 ? ceil(vUV.x - 0.0001) : floor(vUV.x + 0.0001);
                float rawV = dFdy(vUV.y) < 0.0 ? ceil(vUV.y - 0.0001) : floor(vUV.y + 0.0001);

                if (vTexMode > 5.5) {
                    vec2 t = (fuv - uRepRect.xy) / uRepRect.zw;
                    vec4 img = texture2D(uRepTex, t);
                    if (img.a < 0.5) discard;
                    vec3 straightRgb = img.rgb / max(img.a, 0.000001);
                    rgb = floor(straightRgb * 255.0 + 0.5) * floor(affineColor.rgb * 255.0 + 0.5) / 128.0;
                    stp = img.a < 0.95 ? 1.0 : 0.0;
                    mask = max(stp, uSetMask);
                    hostReplacement = 1.0;
                } else {
                    vec2 uv = vec2(mod(rawU, win.x), mod(rawV, win.y)) + uTexWindow.zw;
                    uv = vec2(mod(uv.x, 256.0), mod(uv.y, 256.0));
                    vec4 texel;

                    if (vTexMode < 0.5) {
                        float s = fetch16(vec2(vPageBase.x + floor(uv.x / 4.0), vPageBase.y + uv.y));
                        float lane = mod(uv.x, 4.0);
                        float div = lane < 0.5 ? 1.0 : (lane < 1.5 ? 16.0 : (lane < 2.5 ? 256.0 : 4096.0));
                        float idx = mod(floor(s / div), 16.0);
                        texel = vRepClut > 0.5
                            ? texture2D(uRepClut, vec2((idx + 0.5) / uRepClutCount, 0.5))
                            : fetch(vec2(vClutBase.x + idx, vClutBase.y));
                    } else if (vTexMode < 1.5) {
                        float s = fetch16(vec2(vPageBase.x + floor(uv.x / 2.0), vPageBase.y + uv.y));
                        float div = mod(uv.x, 2.0) < 0.5 ? 1.0 : 256.0;
                        float idx = mod(floor(s / div), 256.0);
                        texel = vRepClut > 0.5
                            ? texture2D(uRepClut, vec2((idx + 0.5) / uRepClutCount, 0.5))
                            : fetch(vec2(vClutBase.x + idx, vClutBase.y));
                    } else {
                        texel = fetch(vec2(vPageBase.x + uv.x, vPageBase.y + uv.y));
                    }

                    if (vRepClut > 0.5 && vTexMode < 1.5) {
                        if (texel.a < 0.5) discard;
                        rgb = floor(texel.rgb * 255.0 + 0.5) * floor(affineColor.rgb * 255.0 + 0.5) / 128.0;
                        stp = texel.a < 0.95 ? 1.0 : 0.0;
                    } else {
                        if (texel.r == 0.0 && texel.g == 0.0 && texel.b == 0.0 && texel.a < 0.5) discard;
                        vec3 t8 = floor(texel.rgb * 31.0 + 0.5) * 8.0;
                        rgb = t8 * floor(affineColor.rgb * 255.0 + 0.5) / 128.0;
                        stp = texel.a >= 0.5 ? 1.0 : 0.0;
                    }
                    mask = max(stp, uSetMask);
                }
            }

            vec3 outRgb = hostReplacement > 0.5
                ? clamp(rgb, 0.0, 255.0) / 255.0
                : fullColor(floor(rgb));
            if (uSemiTrans * stp > 0.5) outRgb = clamp(blendWith(outRgb, dstTexel.rgb), 0.0, 1.0);

            gl_FragColor = vec4(outRgb, mask);
        }
        """;

    static readonly (uint Index, string Name)[] PrimAttribs =
    [
        (0, "inPos"), (1, "inColorF"), (2, "inClutF"), (3, "inTexpageF"),
        (4, "inUV"), (5, "inWorld"), (6, "inHud"), (7, "inPerspectiveW"),
    ];

    public static uint BuildPrim(GL gl, string vsSrc, string fsSrc, string name)
        => Build(gl, vsSrc, fsSrc, name, PrimAttribs);

    public static uint BuildFullscreen(GL gl, string vsSrc, string fsSrc, string name)
        => Build(gl, vsSrc, fsSrc, name, [(0, "aPos")]);

    public static uint Build(GL gl, string vsSrc, string fsSrc, string name, out string? error)
    {
        error = null;
        uint vs = CompileStage(gl, ShaderType.VertexShader, vsSrc, name, out string? vsLog);
        uint fs = CompileStage(gl, ShaderType.FragmentShader, fsSrc, name, out string? fsLog);
        if (vs == 0 || fs == 0)
        {
            error = vsLog ?? fsLog;
            if (vs != 0) gl.DeleteShader(vs);
            if (fs != 0) gl.DeleteShader(fs);
            return 0;
        }

        uint prog = gl.CreateProgram();
        gl.AttachShader(prog, vs);
        gl.AttachShader(prog, fs);
        gl.LinkProgram(prog);
        gl.GetProgram(prog, ProgramPropertyARB.LinkStatus, out int ok);
        if (ok == 0)
        {
            error = gl.GetProgramInfoLog(prog);
            gl.DeleteProgram(prog);
            prog = 0;
        }
        gl.DeleteShader(vs);
        gl.DeleteShader(fs);
        return prog;
    }

    static uint CompileStage(GL gl, ShaderType type, string src, string name, out string? log)
    {
        log = null;
        uint sh = gl.CreateShader(type);
        gl.ShaderSource(sh, Ascii(src));
        gl.CompileShader(sh);
        gl.GetShader(sh, ShaderParameterName.CompileStatus, out int ok);
        if (ok == 0)
        {
            log = $"{type}: {gl.GetShaderInfoLog(sh)}";
            gl.DeleteShader(sh);
            return 0;
        }
        return sh;
    }

    public static uint Build(GL gl, string vsSrc, string fsSrc, string name, (uint Index, string Name)[]? attribs = null)
    {
        uint vs = CompileStage(gl, ShaderType.VertexShader, vsSrc, name);
        uint fs = CompileStage(gl, ShaderType.FragmentShader, fsSrc, name);
        if (vs == 0 || fs == 0) return 0;

        uint prog = gl.CreateProgram();
        gl.AttachShader(prog, vs);
        gl.AttachShader(prog, fs);
        if (attribs != null)
            foreach (var (index, attrib) in attribs)
                gl.BindAttribLocation(prog, index, attrib);
        gl.LinkProgram(prog);
        gl.GetProgram(prog, ProgramPropertyARB.LinkStatus, out int ok);
        if (ok == 0)
        {
            Console.WriteLine($"[GlBackend] link failed ({name}): {gl.GetProgramInfoLog(prog)}");
            gl.DeleteProgram(prog);
            prog = 0;
        }
        gl.DeleteShader(vs);
        gl.DeleteShader(fs);
        return prog;
    }

    static string Ascii(string s)
    {
        var a = s.ToCharArray();
        for (int i = 0; i < a.Length; i++) if (a[i] > 0x7F) a[i] = ' ';
        return new string(a);
    }

    static uint CompileStage(GL gl, ShaderType type, string src, string name)
    {
        uint sh = gl.CreateShader(type);
        gl.ShaderSource(sh, Ascii(src));
        gl.CompileShader(sh);
        gl.GetShader(sh, ShaderParameterName.CompileStatus, out int ok);
        if (ok == 0)
        {
            Console.WriteLine($"[GlBackend] compile failed ({name} {type}) {gl.GetShaderInfoLog(sh)}");
            gl.DeleteShader(sh);
            return 0;
        }
        return sh;
    }
}
