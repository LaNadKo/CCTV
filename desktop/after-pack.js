const fs = require("fs");
const path = require("path");

function copyDir(src, dest) {
  fs.rmSync(dest, { recursive: true, force: true });
  fs.mkdirSync(dest, { recursive: true });
  fs.cpSync(src, dest, { recursive: true, force: true });
}

module.exports = async function afterPack(context) {
  const src = path.resolve(__dirname, "..", "frontend", "dist");
  const dest = path.join(context.appOutDir, "resources", "frontend");

  if (!fs.existsSync(path.join(src, "index.html"))) {
    throw new Error(`Frontend bundle not found: ${src}`);
  }

  copyDir(src, dest);
  console.log(`[afterPack] Synced frontend bundle: ${src} -> ${dest}`);
};
