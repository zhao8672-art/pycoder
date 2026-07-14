const { FusesPlugin } = require('@electron-forge/plugin-fuses');
const { FuseV1Options, FuseVersion } = require('@electron/fuses');

module.exports = {
  packagerConfig: {
    name: 'PyCoder',
    executableName: 'pycoder',
    appBundleId: 'com.pycoder.app',
    asar: true,
    icon: './resources/icon',
    extraResource: ['./resources/tray-icon.png'],
    win32metadata: {
      CompanyName: 'PyCoder',
      FileDescription: 'PyCoder - Python AI Programming IDE',
      OriginalFilename: 'PyCoder.exe',
    },
    ignore: [
      /^\/src/,
      /^\/node_modules\/\.cache/,
      /^\/_archive/,
      /\.ts$/,
      /\.tsx$/,
      /\.map$/,
    ],
  },
  makers: [
    { name: '@electron-forge/maker-squirrel', config: { name: 'PyCoder' } },
    { name: '@electron-forge/maker-zip', platforms: ['darwin', 'linux'] },
    { name: '@electron-forge/maker-dmg', config: {}, platforms: ['darwin'] },
    { name: '@electron-forge/maker-deb', config: {}, platforms: ['linux'] },
    { name: '@electron-forge/maker-rpm', config: {}, platforms: ['linux'] },
  ],
  plugins: [
    { name: '@electron-forge/plugin-auto-unpack-natives', config: {} },
    new FusesPlugin({
      version: FuseVersion.V1,
      [FuseV1Options.RunAsNode]: false,
      [FuseV1Options.EnableEmbeddedAsarIntegrityValidation]: true,
      [FuseV1Options.OnlyLoadAppFromAsar]: true,
    }),
  ],
};
