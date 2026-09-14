"""Build the installable Blender add-on ZIP without game assets."""
import argparse
from pathlib import Path
import zipfile

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--output', type=Path, required=True)
a = p.parse_args()
a.output.parent.mkdir(parents=True, exist_ok=True)
with zipfile.ZipFile(a.output, 'w', zipfile.ZIP_DEFLATED) as archive:
    for name in ('__init__.py', 'README.md', 'templates.json'):
        archive.write(Path(__file__).parent/name, 'blender_spidey/'+name)
    archive.write(Path(__file__).resolve().parents[2]/'docs/releases/blender-1.0.md', 'Readme.txt')
print(a.output.resolve())
