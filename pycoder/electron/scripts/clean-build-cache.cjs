/**
 * PyCoder Electron 构建缓存清理脚本
 * 用途：在 npm run package / make 之前自动清掉会产生"重复耗时"的目录。
 *   - electron-forge 打包产物（out / out_old / out.make）
 *   - Vite / esbuild / typescript 编译缓存
 *   - packager 临时目录（Windows 用户的 %TEMP% 下 electron-* / electron-forge-*）
 *   - 项目特定的 G:\pycode_pkg_src（之前为绕开 26k node_modules realpath 慢而建的打包源）
 * 安全：仅删除白名单目录；不触碰 node_modules / dist / .git；删除前统计并打印
 *
 * 用法：
 *   node scripts/clean-build-cache.cjs                # 默认：全清
 *   node scripts/clean-build-cache.cjs --keep-pkg-src # 保留 G:\pycode_pkg_src
 *                                                       （prepackage/premake 自动用此模式）
 */

const fs = require('fs');
const path = require('path');
const os = require('os');

const ELECTRON_DIR = path.resolve(__dirname, '..');

/** 相对项目根的目录白名单（必须在 pycoder/electron/ 内） */
const PROJECT_PATHS = [
    'out',                // @electron/packager 输出
    'out_old',            // 历史备份
    'node_modules/.cache', // Vite/eslint/typescript 缓存
    '.vite',              // Vite 缓存（罕见在 root，但稳妥清）
];

/** 系统临时目录通配（packager tmpdir 残留） */
function getSystemTmpPaths() {
    const tmp = os.tmpdir();
    const candidates = [
        path.join(tmp, 'electron-packager'),
        path.join(tmp, 'electron-forge-tmp'),
    ];
    // Windows 上 packager 把 tmpdir 放在用户 Temp 下，名字形如 electron-XXXXXXXX
    try {
        for (const name of fs.readdirSync(tmp)) {
            if (/^electron(-forge)?[-_][a-z0-9]+$/i.test(name)) {
                candidates.push(path.join(tmp, name));
            }
        }
    } catch (_) { /* 读取 tmp 失败时静默跳过 */ }
    return candidates;
}

/** 项目特定的 G 盘打包源（仅当存在时清理，避免误删非本项目数据） */
function getProjectSpecificPaths() {
    const out = [];
    // 之前为绕开 C 盘 packager 慢而建的 G:\pycode_pkg_src
    const gSrc = path.join('G:\\', 'pycode_pkg_src');
    if (fs.existsSync(gSrc) && fs.statSync(gSrc).isDirectory()) {
        out.push(gSrc);
    }
    return out;
}

function dirSizeBytes(dir) {
    let total = 0;
    let count = 0;
    function walk(d) {
        let entries;
        try { entries = fs.readdirSync(d, { withFileTypes: true }); }
        catch (_) { return; }
        for (const e of entries) {
            const p = path.join(d, e.name);
            try {
                if (e.isDirectory()) walk(p);
                else if (e.isFile()) {
                    const s = fs.statSync(p);
                    total += s.size;
                    count += 1;
                }
            } catch (_) { /* 单文件 stat 失败忽略 */ }
        }
    }
    walk(dir);
    return { bytes: total, count };
}

function fmtSize(b) {
    if (b < 1024) return b + ' B';
    if (b < 1024 * 1024) return (b / 1024).toFixed(1) + ' KB';
    if (b < 1024 * 1024 * 1024) return (b / 1024 / 1024).toFixed(1) + ' MB';
    return (b / 1024 / 1024 / 1024).toFixed(2) + ' GB';
}

function safeRemove(target) {
    if (!fs.existsSync(target)) return { ok: true, skipped: true };
    const { bytes, count } = dirSizeBytes(target);
    try {
        fs.rmSync(target, { recursive: true, force: true, maxRetries: 3, retryDelay: 200 });
        return { ok: true, skipped: false, bytes, count };
    } catch (e) {
        return { ok: false, error: e && e.message || String(e), bytes, count };
    }
}

function main() {
    const args = new Set(process.argv.slice(2));
    const keepPkgSrc = args.has('--keep-pkg-src');

    const startedAt = Date.now();
    const targets = [
        ...PROJECT_PATHS.map(p => ({ kind: 'project', path: path.join(ELECTRON_DIR, p) })),
        ...getSystemTmpPaths().map(p => ({ kind: 'tmp', path: p })),
    ];
    if (!keepPkgSrc) {
        targets.push(...getProjectSpecificPaths().map(p => ({ kind: 'project-g', path: p })));
    }

    console.log(`[clean-build-cache] Targets (keep-pkg-src=${keepPkgSrc}):`);
    for (const t of targets) {
        const exists = fs.existsSync(t.path);
        console.log(`  [${t.kind}] ${t.path} ${exists ? '' : '(absent)'}`);
    }
    console.log('');

    let totalBytes = 0;
    let totalFiles = 0;
    let failed = 0;
    for (const t of targets) {
        const r = safeRemove(t.path);
        if (r.skipped) continue;
        if (r.ok) {
            totalBytes += r.bytes;
            totalFiles += r.count;
            console.log(`  removed ${t.path}  (${fmtSize(r.bytes)}, ${r.count} files)`);
        } else {
            failed += 1;
            console.error(`  FAIL    ${t.path}  -> ${r.error}`);
        }
    }

    const elapsed = ((Date.now() - startedAt) / 1000).toFixed(2);
    console.log('');
    console.log(`[clean-build-cache] freed ${fmtSize(totalBytes)} across ${totalFiles} files in ${elapsed}s${failed ? ` (${failed} failed)` : ''}`);
    if (failed > 0) process.exitCode = 1;
}

if (require.main === module) {
    try { main(); }
    catch (e) { console.error('[clean-build-cache] fatal:', e && e.stack || e); process.exit(2); }
}

module.exports = { safeRemove, getSystemTmpPaths, getProjectSpecificPaths };
