// Rasterize Blender's exported polygons without altering any UV coordinates.
const fs = require('node:fs');
const path = require('node:path');
const [mod, sharpModule = 'sharp'] = process.argv.slice(2);
const sharp = require(sharpModule);

async function main() {
  for (const file of fs.readdirSync(path.join(mod, 'textures')).filter(f => f.endsWith('.png')).sort()) {
    const input = path.join(mod, 'textures', file);
    const svg = fs.readFileSync(path.join(mod, 'TEMPLATE', 'UV', file.replace(/\.png$/, '.svg')), 'utf8');
    // Keep the original Blender SVG alongside the sheet. Only stroke appearance
    // differs here: a black halo with a white center stays legible on any fabric.
    const halo = Buffer.from(svg.replaceAll('stroke-width="1"', 'stroke-width="3"'));
    const lines = Buffer.from(svg.replaceAll('stroke="black"', 'stroke="white"'));
    const target = path.join(mod, 'TEMPLATE', file);
    await sharp(input).composite([{input: halo}, {input: lines}]).png().toFile(target);
    const a = await sharp(input).metadata(), b = await sharp(target).metadata();
    if (a.width !== b.width || a.height !== b.height) throw new Error(`Dimensions changed: ${file}`);
    console.log(`Stamped ${file}: ${b.width}x${b.height}`);
  }
}
main().catch(error => { console.error(error); process.exitCode = 1; });
