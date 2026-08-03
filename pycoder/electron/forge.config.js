const module_exports = {
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
    // Fuses（直接写 packagerConfig，等价于 FusesPlugin 但不卡 Finalizing）
    // 关闭 RunAsNode；不启用 EmbeddedAsarIntegrityValidation（开发阶段避免卡顿）
    fuses: {
      runAsNode: false,
      enableEmbeddedAsarIntegrityValidation: false,
      onlyLoadAppFromAsar: true,
    },
    // 重要: 必须保留 dist/renderer/assets/（vite 生成的 JS/CSS bundle）
    // 不要添加 /^\/dist\/renderer\/assets\// 之类的 ignore 规则,
    // 否则浏览器加载 index.html 时所有 bundle 404，React 不挂载 -> 白屏
    ignore: [
      /^\/src/,
      /^\/node_modules\/\.cache/,
      /^\/_archive/,
      /^\/out(_old)?/,
      /\.ts$/,
      /\.tsx$/,
      /\.map$/,
      /\.log$/,
      /^\/__/,
    ],
  },
  makers: [
    { name: '@electron-forge/maker-squirrel', config: { name: 'PyCoder' } },
    { name: '@electron-forge/maker-zip', platforms: ['win32', 'darwin', 'linux'] },
    { name: '@electron-forge/maker-dmg', config: {}, platforms: ['darwin'] },
    { name: '@electron-forge/maker-deb', config: {}, platforms: ['linux'] },
    { name: '@electron-forge/maker-rpm', config: {}, platforms: ['linux'] },
  ],
  plugins: [
    { name: '@electron-forge/plugin-auto-unpack-natives', config: {} },
  ],
};
module.exports = module_exports;
