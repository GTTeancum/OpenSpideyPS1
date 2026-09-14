## Installation

1. Download OpenSpidey-Character-Tools.zip. Keep this ZIP intact for Blender installation.
2. Obtain the OpenSpideyPS1 repository checkout and NeversoftMultitool. Install a separate Python with Pillow (python -m pip install Pillow).
3. In Blender, open Edit > Preferences > Add-ons and use Install from Disk to select the ZIP. Enable OpenSpidey Character Tools. Tested with Blender 4.5.8 LTS.
4. In the add-on preferences, configure the repository folder, external Python executable, and NeversoftMultitool executable.
5. Open the Spidey sidebar in the 3D Viewport. Import a native v4 character template from your configured game assets, or use File > Import for a native v4 .psx.

## Blender Character Tools 1.0 — Included

- Installable Blender add-on for native character template import and replacement export.
- Template mesh, joint hierarchy, rigid weight groups, and seam ownership import.
- Weight transfer from a posed template to an aligned replacement mesh, with editable weights and pose preview.
- Export that triangulates and segments geometry by native joints, preserves shared boundary attachments, and checks native part budgets and animation tags.
- Diffuse texture atlas export, optional mesh reduction, and native package validation.
- Template catalog, Readme.txt, and detailed artist workflow documentation in blender_spidey/README.md.

## Basic workflow

Import a template; align your replacement character over it; bake one diffuse atlas; transfer template weights; inspect and adjust the weights; then export a native character package. Test the exported assets in a separate game folder using the SPIDEY_ASSET_DIR override. Remove the override to restore the normal character assets.

The target may be a player, NPC, enemy, or boss. Its native hierarchy and animations remain the reference. The exporter uses dominant rigid weights; Blender's blended preview does not exactly reproduce native rendering.

## Requirements and limitations

- Blender 4.5 or newer; tested with 4.5.8 LTS.
- OpenSpideyPS1 repository checkout, external Python with Pillow, and NeversoftMultitool remain required. The ZIP contains the Blender interface, not a standalone conversion backend.
- Native v4 character assets are required for templates; game models are not included. Raw Dreamcast v6 and native v3 assets require conversion first.
- Export supports one opaque diffuse atlas. Other material effects need baking or adaptation.
- Weight transfer still needs artist inspection and an in-game check. Existing holes are not automatically capped.
- Structural roster tests and a bounded Black Cat replacement stress test passed; arbitrary models are not guaranteed to work without adjustment.

Detailed workflow: https://github.com/GTTeancum/OpenSpideyPS1/blob/master/tools/blender_spidey/README.md
