#!/usr/bin/env node

import { spawn, spawnSync } from "node:child_process";
import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync, cpSync, readdirSync, statSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import readline from "node:readline";
import process from "node:process";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const projectRoot = __dirname;
const isWindows = process.platform === "win32";
const isWsl = os.release().toLowerCase().includes("microsoft");
const packageName = "codex_session_toolkit";
const appName = "codex-session-toolkit";

const actions = [
  { id: "install", label: "安装本地 .venv", description: "创建隔离的本地 Python 环境。", run: runInstallAction },
  { id: "launch", label: "启动 TUI", description: "进入工具箱主菜单。", run: (args) => runLaunchAction([], args) },
  { id: "version", label: "查看版本", description: "输出当前工具版本。", run: (args) => runLaunchAction(["--version"], args) },
  { id: "advanced-help", label: "查看高级帮助", description: "输出稳定自动化 CLI 帮助。", run: (args) => runLaunchAction(["--advanced-help"], args) },
  { id: "release", label: "构建发布目录", description: "按 release 清单生成分发目录和压缩包。", run: runReleaseAction },
  { id: "exit", label: "退出", description: "关闭启动器。", run: null },
];

function usage() {
  console.log("用法: node ./start.mjs [--help] [--list] [--action <id>] [-- <extra args>]");
  console.log("");
  console.log("现有 install / launch / release 脚本的可视化启动器。WSL/Unix 下直接走 Node 内置逻辑，不依赖 shell 脚本换行符。 ");
  console.log("");
  console.log("选项:");
  console.log("  --help           显示这份帮助");
  console.log("  --list           输出可用 action id");
  console.log("  --action <id>    不进入菜单，直接执行一个动作");
  console.log("  --               把剩余参数透传给目标动作");
}

function printAvailableActions() {
  console.log("可用动作:");
  for (const action of actions) {
    if (action.id === "exit") {
      continue;
    }
    console.log(`  ${action.id.padEnd(14, " ")} ${action.label}`);
  }
}

function parseArgs(argv) {
  const parsed = { help: false, list: false, action: "", passthrough: [] };
  for (let index = 0; index < argv.length; index += 1) {
    const current = argv[index];
    if (current === "--") {
      parsed.passthrough = argv.slice(index + 1);
      break;
    }
    if (current === "--help" || current === "-h") {
      parsed.help = true;
      continue;
    }
    if (current === "--list") {
      parsed.list = true;
      continue;
    }
    if (current === "--action") {
      if (index + 1 >= argv.length) {
        throw new Error("--action 需要一个值。");
      }
      parsed.action = argv[index + 1];
      index += 1;
      continue;
    }
    throw new Error(`未知选项: ${current}`);
  }
  return parsed;
}

function parseInstallArgs(args) {
  const parsed = { editable: false, force: false, pythonBin: "", help: false };
  for (let index = 0; index < args.length; index += 1) {
    const current = args[index];
    if (current === "--editable") {
      parsed.editable = true;
      continue;
    }
    if (current === "--force") {
      parsed.force = true;
      continue;
    }
    if (current === "--help" || current === "-h") {
      parsed.help = true;
      continue;
    }
    if (current === "--python") {
      if (index + 1 >= args.length) {
        throw new Error("--python 需要一个值。");
      }
      parsed.pythonBin = args[index + 1];
      index += 1;
      continue;
    }
    throw new Error(`install 不支持参数: ${current}`);
  }
  return parsed;
}

function parseReleaseArgs(args) {
  const parsed = { outputDir: path.join(projectRoot, "dist", "releases"), version: "", pythonBin: "", help: false };
  for (let index = 0; index < args.length; index += 1) {
    const current = args[index];
    if (current === "--help" || current === "-h") {
      parsed.help = true;
      continue;
    }
    if (current === "--output-dir") {
      if (index + 1 >= args.length) {
        throw new Error("--output-dir 需要一个值。");
      }
      parsed.outputDir = path.resolve(projectRoot, args[index + 1]);
      index += 1;
      continue;
    }
    if (current === "--version") {
      if (index + 1 >= args.length) {
        throw new Error("--version 需要一个值。");
      }
      parsed.version = args[index + 1];
      index += 1;
      continue;
    }
    if (current === "--python") {
      if (index + 1 >= args.length) {
        throw new Error("--python 需要一个值。");
      }
      parsed.pythonBin = args[index + 1];
      index += 1;
      continue;
    }
    throw new Error(`release 不支持参数: ${current}`);
  }
  return parsed;
}

function findAction(actionId) {
  return actions.find((action) => action.id === actionId) || null;
}

function renderMenu(selectedIndex) {
  process.stdout.write("\x1b[2J\x1b[H");
  process.stdout.write("Codex Session Toolkit 启动器\n");
  process.stdout.write("============================\n");
  process.stdout.write(`${isWsl ? "环境: WSL\n" : ""}`);
  process.stdout.write(`平台: ${process.platform}\n`);
  process.stdout.write("使用 ↑/↓ 移动，Enter 执行，q 退出。\n\n");
  actions.forEach((action, index) => {
    const prefix = index === selectedIndex ? "> " : "  ";
    process.stdout.write(`${prefix}${action.label}\n`);
    process.stdout.write(`    ${action.description}\n`);
  });
}

function resolvePython(preferred = "", { allowVenv = false } = {}) {
  const candidates = [];
  if (preferred) {
    candidates.push(preferred);
  }
  if (allowVenv) {
    const venvPython = isWindows ? path.join(projectRoot, ".venv", "Scripts", "python.exe") : path.join(projectRoot, ".venv", "bin", "python");
    if (existsSync(venvPython)) {
      candidates.push(venvPython);
    }
  }
  if (process.env.PYTHON_BIN) {
    candidates.push(process.env.PYTHON_BIN);
  }
  candidates.push("python3", "python");

  for (const candidate of candidates) {
    const probe = spawnSync(candidate, ["--version"], { cwd: projectRoot, encoding: "utf8" });
    if (!probe.error && probe.status === 0) {
      return candidate;
    }
  }
  throw new Error("找不到可用的 python3/python 解释器。");
}

function spawnChecked(file, args, options = {}) {
  const result = spawnSync(file, args, {
    cwd: options.cwd || projectRoot,
    stdio: options.capture ? ["ignore", "pipe", "pipe"] : "inherit",
    encoding: "utf8",
    env: options.env || process.env,
  });
  if (result.error) {
    throw result.error;
  }
  if (result.status !== 0) {
    if (options.capture) {
      throw new Error((result.stderr || result.stdout || `${file} 执行失败`).trim());
    }
    throw new Error(`${file} ${args.join(" ")} 执行失败，退出码 ${result.status}`);
  }
  return result;
}

function projectVersion(pythonBin = "") {
  const python = resolvePython(pythonBin);
  const result = spawnChecked(
    python,
    ["-c", 'import sys; sys.path.insert(0, "src"); from codex_session_toolkit import __version__; print(__version__)'],
    { capture: true },
  );
  return result.stdout.trim();
}

function ensureDir(targetDir) {
  mkdirSync(targetDir, { recursive: true });
}

function copyTree(srcPath, destPath) {
  const srcStat = statSync(srcPath);
  if (srcStat.isDirectory()) {
    mkdirSync(destPath, { recursive: true });
    for (const entry of readdirSync(srcPath)) {
      copyTree(path.join(srcPath, entry), path.join(destPath, entry));
    }
    return;
  }
  mkdirSync(path.dirname(destPath), { recursive: true });
  cpSync(srcPath, destPath, { force: true });
}

function removeGeneratedFiles(rootDir) {
  for (const entry of readdirSync(rootDir, { withFileTypes: true })) {
    const targetPath = path.join(rootDir, entry.name);
    if (entry.isDirectory()) {
      if (entry.name === "__pycache__" || entry.name.endsWith(".egg-info")) {
        rmSync(targetPath, { recursive: true, force: true });
        continue;
      }
      removeGeneratedFiles(targetPath);
      continue;
    }
    if (entry.name.endsWith(".pyc") || entry.name.endsWith(".pyo") || entry.name === ".DS_Store") {
      rmSync(targetPath, { force: true });
    }
  }
}

function installUsage() {
  console.log("用法: node ./start.mjs --action install -- [--editable] [--force] [--python <python-bin>]");
  console.log("创建或刷新项目根目录下的隔离 .venv。 ");
}

function releaseUsage() {
  console.log("用法: node ./start.mjs --action release -- [--output-dir <dir>] [--version <version>] [--python <python-bin>]");
  console.log("按 release-manifest.txt 构建目录和 tar.gz/zip。 ");
}

async function runInstallAction(args) {
  const parsed = parseInstallArgs(args);
  if (parsed.help) {
    installUsage();
    return 0;
  }

  const pythonBin = resolvePython(parsed.pythonBin);
  const venvDir = path.join(projectRoot, ".venv");
  const venvPython = isWindows ? path.join(venvDir, "Scripts", "python.exe") : path.join(venvDir, "bin", "python");
  const sitePackagesProbe = 'import sysconfig; print(sysconfig.get_path("purelib"))';

  if (parsed.force && existsSync(venvDir)) {
    rmSync(venvDir, { recursive: true, force: true });
  }

  console.log("=============================================");
  console.log(" Codex Session Toolkit - 安装器 (Node)");
  console.log("=============================================");
  console.log(`Project:   ${projectRoot}`);
  console.log(`Python:    ${pythonBin}`);
  console.log(`Venv:      ${venvDir}`);
  console.log("Isolation: enabled");
  console.log(`Mode:      ${parsed.editable ? "editable" : "standard"}`);

  spawnChecked(pythonBin, ["-m", "venv", venvDir]);
  const sitePackages = spawnChecked(venvPython, ["-c", sitePackagesProbe], { capture: true }).stdout.trim();
  ensureDir(sitePackages);
  const pthFile = path.join(sitePackages, `${packageName}-local.pth`);
  const installedPackageDir = path.join(sitePackages, packageName);
  rmSync(pthFile, { force: true });
  rmSync(installedPackageDir, { recursive: true, force: true });

  if (parsed.editable) {
    writeFileSync(pthFile, `${path.join(projectRoot, "src")}\n`, "utf8");
  } else {
    copyTree(path.join(projectRoot, "src", packageName), installedPackageDir);
  }

  console.log("");
  console.log("安装完成。");
  console.log("现在可用：");
  console.log("  node ./start.mjs --action launch");
  console.log("  node ./start.mjs --action version");
  return 0;
}

function launchEnvironment() {
  const env = { ...process.env };
  const srcDir = path.join(projectRoot, "src");
  env.PYTHONPATH = env.PYTHONPATH ? `${srcDir}${path.delimiter}${env.PYTHONPATH}` : srcDir;
  return env;
}

async function runLaunchAction(fixedArgs, passthroughArgs) {
  const pythonBin = resolvePython("", { allowVenv: true });
  const env = launchEnvironment();
  const args = ["-m", packageName, ...fixedArgs, ...passthroughArgs];

  console.log("=============================================");
  console.log(" Codex Session Toolkit - 启动器 (Node)");
  console.log("=============================================");
  console.log(`Python:    ${pythonBin}`);
  console.log(`Env:       ${pythonBin.includes(`${path.sep}.venv${path.sep}`) ? "local isolated .venv" : "system interpreter"}`);
  console.log(`>> ${pythonBin} ${args.join(" ")}`);

  return await new Promise((resolve, reject) => {
    const child = spawn(pythonBin, args, { cwd: projectRoot, stdio: "inherit", env });
    child.on("error", reject);
    child.on("exit", (code, signal) => {
      if (signal) {
        reject(new Error(`动作被信号 ${signal} 终止`));
        return;
      }
      resolve(code ?? 0);
    });
  });
}

async function runReleaseAction(args) {
  const parsed = parseReleaseArgs(args);
  if (parsed.help) {
    releaseUsage();
    return 0;
  }

  const version = parsed.version || projectVersion(parsed.pythonBin);
  const archiveRoot = `${appName}-${version}`;
  const releaseDir = path.join(parsed.outputDir, archiveRoot);
  const stageDir = path.join(os.tmpdir(), `codex-session-toolkit-release-${Date.now()}`);
  const stageRoot = path.join(stageDir, archiveRoot);
  const manifestFile = path.join(projectRoot, "scripts", "release", "release-manifest.txt");

  if (!existsSync(manifestFile)) {
    throw new Error(`找不到 release manifest: ${manifestFile}`);
  }

  rmSync(stageDir, { recursive: true, force: true });
  ensureDir(stageRoot);
  ensureDir(parsed.outputDir);

  const manifestLines = readFileSync(manifestFile, "utf8").split(/\r?\n/).filter((line) => line && !line.startsWith("#"));
  for (const relativePath of manifestLines) {
    const sourcePath = path.join(projectRoot, relativePath);
    if (!existsSync(sourcePath)) {
      throw new Error(`manifest 条目不存在: ${relativePath}`);
    }
    copyTree(sourcePath, path.join(stageRoot, relativePath));
  }

  removeGeneratedFiles(stageRoot);
  rmSync(releaseDir, { recursive: true, force: true });
  copyTree(stageRoot, releaseDir);

  const tarballPath = path.join(parsed.outputDir, `${archiveRoot}.tar.gz`);
  const tarProbe = spawnSync("tar", ["--version"], { encoding: "utf8" });
  if (!tarProbe.error && tarProbe.status === 0) {
    spawnChecked("tar", ["-czf", tarballPath, "-C", stageDir, archiveRoot]);
  }

  const zipPath = path.join(parsed.outputDir, `${archiveRoot}.zip`);
  const zipProbe = spawnSync("zip", ["-v"], { encoding: "utf8" });
  if (!zipProbe.error && (zipProbe.status === 0 || zipProbe.status === 1 || zipProbe.status === 2)) {
    spawnChecked("zip", ["-qr", zipPath, archiveRoot], { env: process.env, cwd: stageDir });
  }

  console.log("=============================================");
  console.log(" Codex Session Toolkit - Release Builder (Node)");
  console.log("=============================================");
  console.log(`Version:     ${version}`);
  console.log(`Output dir:  ${parsed.outputDir}`);
  console.log(`Manifest:    ${manifestFile}`);
  console.log(`Folder:      ${releaseDir}`);
  if (existsSync(tarballPath)) {
    console.log(`Tarball:     ${tarballPath}`);
  }
  if (existsSync(zipPath)) {
    console.log(`Zip:         ${zipPath}`);
  }
  return 0;
}

async function openMenu() {
  if (!process.stdin.isTTY || !process.stdout.isTTY) {
    usage();
    console.log("");
    printAvailableActions();
    return 0;
  }

  readline.emitKeypressEvents(process.stdin);
  process.stdin.setRawMode(true);
  let selectedIndex = 0;
  renderMenu(selectedIndex);

  return new Promise((resolve, reject) => {
    const onKeypress = async (_value, key) => {
      if (key.name === "up") {
        selectedIndex = (selectedIndex + actions.length - 1) % actions.length;
        renderMenu(selectedIndex);
        return;
      }
      if (key.name === "down") {
        selectedIndex = (selectedIndex + 1) % actions.length;
        renderMenu(selectedIndex);
        return;
      }
      if (key.name === "q" || key.name === "escape" || (key.ctrl && key.name === "c")) {
        cleanup();
        resolve(0);
        return;
      }
      if (key.name !== "return") {
        return;
      }
      const action = actions[selectedIndex];
      cleanup();
      if (action.id === "exit") {
        resolve(0);
        return;
      }
      try {
        const code = await action.run([]);
        resolve(code);
      } catch (error) {
        reject(error);
      }
    };

    const cleanup = () => {
      process.stdin.removeListener("keypress", onKeypress);
      if (process.stdin.isTTY) {
        process.stdin.setRawMode(false);
      }
      process.stdout.write("\x1b[2J\x1b[H");
    };

    process.stdin.on("keypress", onKeypress);
  });
}

async function main() {
  let parsed;
  try {
    parsed = parseArgs(process.argv.slice(2));
  } catch (error) {
    console.error(`错误: ${error.message}`);
    usage();
    return 2;
  }

  if (parsed.help) {
    usage();
    return 0;
  }
  if (parsed.list) {
    printAvailableActions();
    return 0;
  }
  if (parsed.action) {
    const action = findAction(parsed.action);
    if (!action || action.id === "exit") {
      console.error(`错误: 未知动作: ${parsed.action}`);
      printAvailableActions();
      return 2;
    }
    try {
      return await action.run(parsed.passthrough);
    } catch (error) {
      console.error(`错误: ${error.message}`);
      return 1;
    }
  }

  try {
    return await openMenu();
  } catch (error) {
    console.error(`错误: ${error.message}`);
    return 1;
  }
}

process.exitCode = await main();
