#!/usr/bin/env node

import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
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

const actions = [
  {
    id: "install",
    label: "安装本地 .venv",
    description: "运行隔离的本地安装脚本。",
    command: buildInstallCommand,
  },
  {
    id: "launch",
    label: "启动 TUI",
    description: "进入工具箱主菜单。",
    command: buildLaunchCommand,
  },
  {
    id: "version",
    label: "查看版本",
    description: "输出当前工具版本。",
    command: () => appendArgs(buildLaunchCommand(), ["--version"]),
  },
  {
    id: "advanced-help",
    label: "查看高级帮助",
    description: "输出稳定自动化 CLI 帮助。",
    command: () => appendArgs(buildLaunchCommand(), ["--advanced-help"]),
  },
  {
    id: "release",
    label: "构建发布目录",
    description: "运行 release 构建脚本。",
    command: buildReleaseCommand,
  },
  {
    id: "exit",
    label: "退出",
    description: "关闭启动器。",
    command: null,
  },
];

function buildInstallCommand() {
  if (isWindows) {
    return {
      file: "powershell.exe",
      args: ["-ExecutionPolicy", "Bypass", "-File", path.join(projectRoot, "install.ps1")],
    };
  }
  return {
    file: "sh",
    args: [path.join(projectRoot, "install.sh")],
  };
}

function buildLaunchCommand() {
  if (isWindows) {
    return {
      file: "powershell.exe",
      args: ["-ExecutionPolicy", "Bypass", "-File", path.join(projectRoot, "codex-session-toolkit.ps1")],
    };
  }
  return {
    file: "sh",
    args: [path.join(projectRoot, "codex-session-toolkit")],
  };
}

function buildReleaseCommand() {
  return {
    file: "sh",
    args: [path.join(projectRoot, "release.sh")],
  };
}

function appendArgs(command, extraArgs) {
  return {
    file: command.file,
    args: [...command.args, ...extraArgs],
  };
}

function usage() {
  console.log("用法: node ./start.mjs [--help] [--list] [--action <id>] [-- <extra args>]");
  console.log("");
  console.log("现有 install / launch / release 脚本的可视化启动器。");
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
  const parsed = {
    help: false,
    list: false,
    action: "",
    passthrough: [],
  };

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

function findAction(actionId) {
  return actions.find((action) => action.id === actionId) || null;
}

function ensureActionFiles(action) {
  if (!action || !action.command || action.id === "exit") {
    return;
  }
  const command = action.command();
  const scriptArg = command.args.find((value) => value.startsWith(projectRoot));
  if (scriptArg && !existsSync(scriptArg)) {
    throw new Error(`找不到启动目标: ${scriptArg}`);
  }
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

function runCommand(action, passthroughArgs = []) {
  if (!action.command) {
    return Promise.resolve(0);
  }
  const command = action.command();
  const child = spawn(command.file, [...command.args, ...passthroughArgs], {
    cwd: projectRoot,
    stdio: "inherit",
  });
  return new Promise((resolve, reject) => {
    child.on("error", reject);
    child.on("exit", (code, signal) => {
      if (signal) {
        reject(new Error(`Action ${action.id} terminated by signal ${signal}`));
        return;
      }
      resolve(code ?? 0);
    });
  });
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
        ensureActionFiles(action);
        const code = await runCommand(action);
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
      ensureActionFiles(action);
      return await runCommand(action, parsed.passthrough);
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
