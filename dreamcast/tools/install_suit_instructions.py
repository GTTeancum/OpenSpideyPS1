"""Copy the shared customization guide into every suit in supplied mod roots."""
import argparse
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('suit_roots', nargs='+', type=Path)
    args = parser.parse_args()
    guide = ROOT / 'mods/suit-instructions.txt'
    count = 0
    for root in args.suit_roots:
        if not root.is_dir():
            raise ValueError(f'Not a suit directory: {root}')
        for manifest in sorted(root.glob('*/suit.json')):
            target = manifest.parent / 'instructions.txt'
            shutil.copy2(guide, target)
            assert target.read_bytes() == guide.read_bytes()
            count += 1
    print(f'Installed and verified instructions in {count} suit folders')


if __name__ == '__main__':
    main()
