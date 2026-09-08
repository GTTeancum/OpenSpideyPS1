"""Regression for SM1 reskins sharing a process with SM2's visible wing donor."""
from pathlib import Path
import unittest
import zipfile
from build_sm2_mod_actor import isolate_cutout, ROOT
from pack_sm2_costume_to_dc import container_layout, HIDDEN_WING_HASH, DC_WING_HASH

class WingCutoutTests(unittest.TestCase):
    def test_only_private_cutout_identity_changes(self):
        with zipfile.ZipFile(ROOT/'spiderman/port/bundled/runtime-assets.zip') as archive:
            before = archive.read('spidey.psx')
        after = isolate_cutout(before)
        old = container_layout(before)
        new = container_layout(after)
        index = old['textureHashes'].index(DC_WING_HASH)
        offset = old['hashCountOffset'] + 4 + index*4
        self.assertEqual(before[:offset], after[:offset])
        self.assertEqual(before[offset+4:], after[offset+4:])
        self.assertEqual(new['textureHashes'][index], HIDDEN_WING_HASH)
        self.assertNotIn(DC_WING_HASH, new['textureHashes'])
        self.assertEqual(old['textureHashes'][:index], new['textureHashes'][:index])
        with zipfile.ZipFile(ROOT/'spiderman2/port/bundled/runtime-assets.zip') as archive:
            self.assertEqual(archive.read('spidey-mod-sm1.psx'), after)

    def test_visible_wing_donor_cannot_be_hidden(self):
        with zipfile.ZipFile(ROOT/'spiderman2/port/bundled/runtime-assets.zip') as archive:
            visible = archive.read('spidey.psx')
        with self.assertRaises(ValueError):
            isolate_cutout(visible)

if __name__ == '__main__':
    unittest.main()
