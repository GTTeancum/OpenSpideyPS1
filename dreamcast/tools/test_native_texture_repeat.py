"""Native repeat-page regression tests; no Blender or external assets required."""
import struct
import unittest

import pack_sm2_costume_to_dc as pack


def library(records):
    data = bytearray(struct.pack("<HHIII", 4, 2, 16, 0, 0))
    data.extend(struct.pack("<II", 0xFFFFFFFF, len(records)))
    data.extend(struct.pack(f"<{len(records)}I", *range(100, 100 + len(records))))
    # Palette declarations are deliberately nonzero to catch accidental changes.
    data.extend(struct.pack("<II", 1, 123) + bytes(range(32)))
    data.extend(struct.pack("<II", 1, 456) + bytes(range(256)) * 2)
    data.extend(struct.pack("<I", len(records)))
    table = len(data)
    data.extend(bytes(len(records) * 4))
    for ordinal, (index, width, height, bits) in enumerate(records):
        struct.pack_into("<I", data, table + ordinal * 4, len(data))
        data.extend(struct.pack("<IIIIHH", 0, 16 if bits == 4 else 256,
                                123 if bits == 4 else 456, index, width, height))
        row = ((width + 3) & ~3) // 2 if bits == 4 else (width + 1) & ~1
        pixels = bytearray((row * height + 3) & ~3)
        for y in range(height):
            for x in range(width):
                value = (x + 3*y) % (1 << bits)
                offset = y * row + x * bits // 8
                if bits == 4:
                    pixels[offset] |= value << (4 * (x & 1))
                else:
                    pixels[offset] = value
        data.extend(pixels)
    return bytes(data)


def actor(faces):
    # One mesh, no vertices needed: this audit consumes only native face packets.
    data = bytearray(struct.pack("<HHIIII", 4, 2, 0, 0, 1, 20))
    header = bytearray(28)
    struct.pack_into("<H", header, 6, len(faces))
    data.extend(header)
    for index, uv in faces:
        packet = bytearray(32)
        struct.pack_into("<HH", packet, 0, 0x10 if len(uv) == 3 else 0, 32)
        struct.pack_into("<I", packet, 16, index)
        for i, pair in enumerate(uv):
            struct.pack_into("<BB", packet, 20 + i*2, *pair)
        data.extend(packet)
    struct.pack_into("<I", data, 4, len(data))
    data.extend(struct.pack("<7I", 0xFFFFFFFF, 1234, 0, 0, 0, 0, 0))
    return bytes(data)


def texels(data):
    layout = pack.container_layout(data)
    result = {}
    expected_pointer = layout["texturePointerTable"] + 4 * layout["textureCount"]
    for ordinal in range(layout["textureCount"]):
        pointer = pack.u32(data, layout["texturePointerTable"] + ordinal * 4)
        assert pointer == expected_pointer, "records must be contiguous, in ordinal order"
        _, palette, _, index, width, height = struct.unpack_from("<IIIIHH", data, pointer)
        bits = 4 if palette == 16 else 8
        row = ((width + 3) & ~3) // 2 if bits == 4 else (width + 1) & ~1
        pixels = []
        for y in range(height):
            line = []
            for x in range(width):
                value = data[pointer + 20 + y * row + x * bits // 8]
                line.append((value >> (4 * (x & 1))) & 15 if bits == 4 else value)
            pixels.append(line)
        result[index] = pixels
        expected_pointer = pointer + 20 + ((row * height + 3) & ~3)
    assert expected_pointer == len(data)
    return result


class NativeRepeatTests(unittest.TestCase):
    def test_periodic_pixels_and_unchanged_palettes(self):
        for bits in (4, 8):
            with self.subTest(bits=bits):
                source = library([(0, 3, 3, bits)])
                mesh = actor([(0, [(0, 0), (7, 1), (1, 5)])])
                expanded, report = pack.preserve_native_texture_repeat(mesh, source)
                start = pack.container_layout(source)["texturePointerTable"]
                self.assertEqual(source[:start], expanded[:start])
                original, output = texels(source)[0], texels(expanded)[0]
                self.assertEqual((len(output[0]), len(output)), (8, 8))
                for y, row in enumerate(output):
                    for x, value in enumerate(row):
                        self.assertEqual(value, original[y % 3][x % 3])
                self.assertEqual(report["facesAudited"], 1)
                second, _ = pack.preserve_native_texture_repeat(mesh, expanded)
                self.assertEqual(second, expanded)

    def test_indices_not_record_order_and_quad_last_corner(self):
        source = library([(1, 4, 4, 8), (0, 4, 4, 4)])
        mesh = actor([(0, [(0, 0), (1, 0), (1, 1), (4, 7)])])
        output, report = pack.preserve_native_texture_repeat(mesh, source)
        pages = texels(output)
        self.assertEqual((len(pages[0][0]), len(pages[0])), (8, 8))
        self.assertEqual(pages[1], texels(source)[1])
        self.assertEqual(report["expandedPages"][0]["index"], 0)

    def test_no_repeat_is_byte_exact(self):
        source = library([(0, 4, 4, 4)])
        output, report = pack.preserve_native_texture_repeat(
            actor([(0, [(0, 0), (3, 0), (0, 3)])]), source)
        self.assertEqual(source, output)
        self.assertEqual(report["expandedPages"], [])

    def test_boundary_and_full_native_byte_domain(self):
        for maximum, expected in ((63, 64), (64, 128), (255, 256)):
            with self.subTest(maximum=maximum):
                source = library([(0, 64, 4, 4)])
                output, _ = pack.preserve_native_texture_repeat(
                    actor([(0, [(0, 0), (maximum, 0), (0, 3)])]), source)
                self.assertEqual(len(texels(output)[0][0]), expected)

    def test_bad_material_fails(self):
        with self.assertRaisesRegex(ValueError, "exceeds library"):
            pack.preserve_native_texture_repeat(actor([(1, [(0, 0)] * 3)]),
                                                library([(0, 4, 4, 4)]))

    def test_geometry_prefix_untouched_when_embedded(self):
        source = library([(0, 4, 4, 4)])
        mesh = actor([(0, [(0, 0), (7, 0), (0, 3)])])
        output, _ = pack.preserve_native_texture_repeat(mesh, source)
        packed = pack.replace_texture_section(mesh, (100,), output)
        end = pack.container_layout(mesh)["hashCountOffset"]
        self.assertEqual(mesh[:end], packed[:end])

    def test_noncontiguous_records_and_trailing_data_fail(self):
        source = library([(0, 4, 4, 4)])
        mesh = actor([(0, [(0, 0)] * 3)])
        with self.assertRaisesRegex(ValueError, "trailing"):
            pack.preserve_native_texture_repeat(mesh, source + b"TAIL")
        malformed = bytearray(source)
        table = pack.container_layout(source)["texturePointerTable"]
        struct.pack_into("<I", malformed, table, pack.u32(source, table) + 4)
        with self.assertRaisesRegex(ValueError, "noncontiguous"):
            pack.preserve_native_texture_repeat(mesh, malformed)

    def test_independent_audit_detects_changed_pixel(self):
        from audit_sm2_player_port_coverage import verify_repeat_library
        source = library([(0, 4, 4, 4)])
        mesh = actor([(0, [(0, 0), (7, 0), (0, 3)])])
        output, _ = pack.preserve_native_texture_repeat(mesh, source)
        errors = []
        verify_repeat_library(errors, source, output, "synthetic")
        self.assertEqual(errors, [])
        malformed = bytearray(output)
        table = pack.container_layout(output)["texturePointerTable"]
        malformed[pack.u32(output, table) + 20] ^= 1
        verify_repeat_library(errors, source, malformed, "synthetic")
        self.assertTrue(any("pixels differ" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
