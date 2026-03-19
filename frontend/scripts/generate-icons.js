/**
 * Generate PWA icons from icon.svg.
 * Run: node scripts/generate-icons.js
 * Requires: npm install sharp --save-dev (one-time)
 */
import sharp from "sharp";
import { readFileSync, mkdirSync } from "fs";
import { join, dirname } from "path";
import { fileURLToPath } from "url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = join(__dirname, "..");
const svg = readFileSync(join(root, "public", "icon.svg"));

const sizes = [72, 96, 128, 144, 152, 192, 384, 512];

mkdirSync(join(root, "public", "icons"), { recursive: true });

for (const size of sizes) {
  await sharp(svg)
    .resize(size, size)
    .png()
    .toFile(join(root, "public", "icons", `icon-${size}x${size}.png`));
  console.log(`Generated icon-${size}x${size}.png`);
}

// Apple touch icon
await sharp(svg).resize(180, 180).png().toFile(join(root, "public", "apple-touch-icon.png"));
console.log("Generated apple-touch-icon.png");

// Favicon
await sharp(svg).resize(32, 32).png().toFile(join(root, "public", "favicon.png"));
console.log("Generated favicon.png");

console.log("Done!");
