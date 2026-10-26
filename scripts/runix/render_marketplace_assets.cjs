const path = require('node:path');
const sharp = require('sharp');

async function render() {
  const directory = path.resolve(__dirname, '../../images/marketplace');
  await sharp(path.join(directory, 'runix-logo.svg'))
    .resize(320, 320)
    .png()
    .toFile(path.join(directory, 'runix-logo-320.png'));
  await sharp(path.join(directory, 'runix-fs-overview.svg'))
    .flatten({ background: '#0a1220' })
    .removeAlpha()
    .png()
    .toFile(path.join(directory, 'runix-fs-overview-780x439.png'));
}

render().catch(error => {
  process.stderr.write(`${error.message}\n`);
  process.exitCode = 1;
});
