/**
 * Project Brain VS Code Extension
 *
 * 安全設計：
 *   - 所有子進程呼叫用固定的 argv 陣列，不使用 shell=true
 *   - 使用者輸入透過 vscode.window.showInputBox 取得，有長度限制
 *   - 只讀取 workspaceFolder 下的 .brain/ 目錄
 *   - API 呼叫有 timeout，防止 UI 卡住
 *
 * 記憶體管理：
 *   - Debounce 自動刷新，避免頻繁呼叫
 *   - TreeItem 按需建立，不快取全部節點
 *   - EventEmitter 在 deactivate 時釋放
 */

import * as vscode from 'vscode';
import * as cp from 'child_process';
import * as path from 'path';
import * as fs from 'fs';

// ── 型別定義 ───────────────────────────────────────────────────

interface KnowledgeNode {
  title:   string;
  content: string;
  type:    'Decision' | 'Pitfall' | 'Rule' | 'ADR' | 'Component' | string;
  tags?:   string[];
  similarity?: number;
}

interface BrainStatus {
  nodes:    number;
  edges:    number;
  by_type?: Record<string, number>;
}

// ── 常數 ────────────────────────────────────────────────────────

const ICONS: Record<string, string> = {
  Decision:  '🎯',
  Pitfall:   '⚠️',
  Rule:      '📋',
  ADR:       '📄',
  Component: '🔧',
  default:   '💡',
};

const MAX_INPUT_LEN = 200;       // 使用者輸入最大長度
const CMD_TIMEOUT   = 10_000;    // 命令執行超時（ms）

// ── Tree Provider ────────────────────────────────────────────────

class KnowledgeItem extends vscode.TreeItem {
  constructor(
    public readonly label: string,
    public readonly collapsibleState: vscode.TreeItemCollapsibleState,
    public readonly nodeData?: KnowledgeNode,
    public readonly itemType: 'section' | 'node' | 'empty' = 'node',
  ) {
    super(label, collapsibleState);

    if (itemType === 'node' && nodeData) {
      const icon = ICONS[nodeData.type] ?? ICONS.default;
      this.description   = nodeData.type;
      this.tooltip       = new vscode.MarkdownString(
        `**${nodeData.type}**\n\n${nodeData.content.slice(0, 300)}`
      );
      this.iconPath      = new vscode.ThemeIcon(
        nodeData.type === 'Pitfall' ? 'warning' :
        nodeData.type === 'Decision' ? 'lightbulb' :
        nodeData.type === 'Rule' ? 'law' :
        nodeData.type === 'ADR' ? 'file-text' : 'symbol-module'
      );
      this.command = {
        command:   'projectBrain.openNode',
        title:     '開啟知識',
        arguments: [nodeData],
      };
    } else if (itemType === 'section') {
      this.iconPath = new vscode.ThemeIcon('folder');
    } else if (itemType === 'empty') {
      this.iconPath    = new vscode.ThemeIcon('info');
      this.description = '點擊重新整理';
    }
  }
}

class ProjectBrainProvider implements vscode.TreeDataProvider<KnowledgeItem> {
  private _onDidChangeTreeData =
    new vscode.EventEmitter<KnowledgeItem | undefined | null>();
  readonly onDidChangeTreeData = this._onDidChangeTreeData.event;

  private _items: KnowledgeNode[] = [];
  private _status: BrainStatus | null = null;
  private _refreshTimer: NodeJS.Timeout | null = null;

  constructor(private readonly workspaceRoot: string) {}

  refresh(): void {
    this._onDidChangeTreeData.fire(undefined);
  }

  scheduleRefresh(delay = 2000): void {
    if (this._refreshTimer) {
      clearTimeout(this._refreshTimer);
    }
    this._refreshTimer = setTimeout(() => {
      this._refreshTimer = null;
      this.refresh();
    }, delay);
  }

  updateItems(items: KnowledgeNode[]): void {
    // 限制顯示數量
    const max = vscode.workspace.getConfiguration('projectBrain')
                      .get<number>('maxResults', 5);
    this._items = items.slice(0, max);
    this.refresh();
  }

  updateStatus(status: BrainStatus): void {
    this._status = status;
    this.refresh();
  }

  // 釋放資源
  dispose(): void {
    if (this._refreshTimer) {
      clearTimeout(this._refreshTimer);
    }
    this._onDidChangeTreeData.dispose();
  }

  getTreeItem(element: KnowledgeItem): vscode.TreeItem {
    return element;
  }

  getChildren(element?: KnowledgeItem): KnowledgeItem[] {
    if (!element) {
      // 根節點：狀態列 + 知識列表
      const children: KnowledgeItem[] = [];

      if (this._status) {
        const statusItem = new KnowledgeItem(
          `${this._status.nodes} 個知識節點 · ${this._status.edges} 條關係`,
          vscode.TreeItemCollapsibleState.None,
          undefined,
          'section',
        );
        statusItem.iconPath    = new vscode.ThemeIcon('database');
        statusItem.description = '知識圖譜';
        children.push(statusItem);
      }

      if (this._items.length === 0) {
        children.push(new KnowledgeItem(
          '暫無相關知識',
          vscode.TreeItemCollapsibleState.None,
          undefined,
          'empty',
        ));
      } else {
        for (const node of this._items) {
          children.push(new KnowledgeItem(
            node.title,
            vscode.TreeItemCollapsibleState.None,
            node,
            'node',
          ));
        }
      }

      return children;
    }
    return [];
  }
}

// ── 命令執行輔助（安全版本）────────────────────────────────────

function runBrainCommand(
  pythonPath: string,
  workdir:    string,
  args:       string[],
): Promise<string> {
  return new Promise((resolve, reject) => {
    // 安全：用 argv 陣列而不是 shell string
    const proc = cp.spawn(pythonPath, [
      path.join(workdir, 'brain.py'),
      ...args,
    ], {
      cwd:     workdir,
      timeout: CMD_TIMEOUT,
      env:     { ...process.env },   // 繼承環境變數
      // 不使用 shell，防止注入
    });

    let stdout = '';
    let stderr = '';

    proc.stdout.on('data', (chunk: Buffer) => {
      stdout += chunk.toString('utf8');
      // 限制緩衝大小（防止記憶體洩漏）
      if (stdout.length > 50_000) {
        stdout = stdout.slice(-50_000);
      }
    });
    proc.stderr.on('data', (chunk: Buffer) => {
      stderr += chunk.toString('utf8').slice(0, 5_000);
    });

    proc.on('close', (code) => {
      if (code === 0) {
        resolve(stdout.trim());
      } else {
        // 不回傳 stderr（可能包含路徑等敏感資訊），只記錄到 console
        console.error(`[ProjectBrain] brain command 失敗 (exit ${code}):`, stderr);
        reject(new Error(`命令執行失敗（exit code ${code}）`));
      }
    });

    proc.on('error', (err) => {
      reject(new Error(`無法執行 Python：${err.message}`));
    });
  });
}

// ── 擴充套件 Activate / Deactivate ──────────────────────────────

let provider: ProjectBrainProvider | null = null;
const disposables: vscode.Disposable[] = [];

export function activate(context: vscode.ExtensionContext): void {
  const workspaceRoot = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath ?? '';

  // 確認 .brain/ 存在
  const brainDir = path.join(workspaceRoot, '.brain');
  if (!fs.existsSync(brainDir)) {
    return;  // 靜默退出，不顯示錯誤
  }

  provider = new ProjectBrainProvider(workspaceRoot);

  // 註冊 Tree View
  const treeView = vscode.window.createTreeView('projectBrain', {
    treeDataProvider:   provider,
    showCollapseAll:    false,
    canSelectMany:      false,
  });
  disposables.push(treeView);

  // 取得設定
  const cfg = () => vscode.workspace.getConfiguration('projectBrain');
  const getPython = () => cfg().get<string>('pythonPath', 'python');

  // 載入初始狀態
  loadStatus(workspaceRoot, getPython());

  // ── 指令：重新整理 ──────────────────────────────────────────
  disposables.push(vscode.commands.registerCommand('projectBrain.refresh', () => {
    loadStatus(workspaceRoot, getPython());
    if (vscode.window.activeTextEditor) {
      loadContextForEditor(vscode.window.activeTextEditor, workspaceRoot, getPython());
    }
  }));

  // ── 指令：語義搜尋 ──────────────────────────────────────────
  disposables.push(vscode.commands.registerCommand('projectBrain.search', async () => {
    const input = await vscode.window.showInputBox({
      prompt:      '輸入搜尋詞（自然語言）',
      placeHolder: '例如：支付模組的已知問題',
      validateInput: (v) => {
        if (v.length > MAX_INPUT_LEN) return `請輸入 ${MAX_INPUT_LEN} 字以內`;
        return null;
      },
    });
    if (!input?.trim()) return;

    const python = getPython();
    vscode.window.withProgress(
      { location: vscode.ProgressLocation.Window, title: '搜尋中...' },
      async () => {
        try {
          const out = await runBrainCommand(python, workspaceRoot, [
            'context', input.trim().slice(0, MAX_INPUT_LEN)
          ]);
          // 顯示在輸出面板
          const channel = vscode.window.createOutputChannel('Project Brain 搜尋結果');
          channel.appendLine(out || '（無相關知識）');
          channel.show();
        } catch (e: unknown) {
          vscode.window.showErrorMessage(`搜尋失敗：${(e as Error).message}`);
        }
      }
    );
  }));

  // ── 指令：手動加入知識 ──────────────────────────────────────
  disposables.push(vscode.commands.registerCommand('projectBrain.addKnowledge', async () => {
    const title = await vscode.window.showInputBox({
      prompt:      '知識標題',
      placeHolder: '例如：支付金額必須以分為單位',
      validateInput: (v) => v.length > MAX_INPUT_LEN
        ? `最多 ${MAX_INPUT_LEN} 字` : null,
    });
    if (!title?.trim()) return;

    const kindPick = await vscode.window.showQuickPick(
      ['Decision（架構決策）', 'Pitfall（踩坑記錄）', 'Rule（業務規則）', 'ADR（決策記錄）'],
      { placeHolder: '知識類型' }
    );
    if (!kindPick) return;
    const kind = kindPick.split('（')[0];

    const content = await vscode.window.showInputBox({
      prompt:    '詳細說明（包含背景、原因、解法）',
      placeHolder: '...',
      validateInput: (v) => v.length > 1000 ? '最多 1000 字' : null,
    });
    if (!content?.trim()) return;

    const python = getPython();
    try {
      await runBrainCommand(python, workspaceRoot, [
        'add',
        title.trim().slice(0, MAX_INPUT_LEN),
        '--content', content.trim().slice(0, 1000),
        '--kind', kind,
      ]);
      vscode.window.showInformationMessage(`已加入：${title}`);
      provider?.refresh();
    } catch (e: unknown) {
      vscode.window.showErrorMessage(`加入失敗：${(e as Error).message}`);
    }
  }));

  // ── 指令：在瀏覽器開啟知識圖譜 ────────────────────────────
  disposables.push(vscode.commands.registerCommand('projectBrain.openGraph', () => {
    const port = 7890;
    vscode.env.openExternal(vscode.Uri.parse(`http://127.0.0.1:${port}`));
  }));

  // ── 指令：顯示 Context ──────────────────────────────────────
  disposables.push(vscode.commands.registerCommand('projectBrain.showContext', async () => {
    const editor = vscode.window.activeTextEditor;
    if (!editor) {
      vscode.window.showInformationMessage('請先開啟一個檔案');
      return;
    }
    const filePath = editor.document.uri.fsPath;
    const relPath  = path.relative(workspaceRoot, filePath);

    const task = await vscode.window.showInputBox({
      prompt:      '描述你要做的任務',
      placeHolder: '例如：修復訂單服務的金額計算',
      validateInput: (v) => v.length > MAX_INPUT_LEN ? `最多 ${MAX_INPUT_LEN} 字` : null,
    });
    if (!task?.trim()) return;

    const python = getPython();
    vscode.window.withProgress(
      { location: vscode.ProgressLocation.Window, title: '組裝知識...' },
      async () => {
        try {
          const out = await runBrainCommand(python, workspaceRoot, [
            'context', task.trim().slice(0, MAX_INPUT_LEN), '--file', relPath
          ]);
          const doc = await vscode.workspace.openTextDocument({
            content:  out || '（無相關知識，請先執行 brain init 或 brain scan）',
            language: 'markdown',
          });
          await vscode.window.showTextDocument(doc, { preview: true });
        } catch (e: unknown) {
          vscode.window.showErrorMessage(`Context 組裝失敗：${(e as Error).message}`);
        }
      }
    );
  }));

  // ── 自動刷新：監聽編輯器切換 ──────────────────────────────
  disposables.push(vscode.window.onDidChangeActiveTextEditor((editor) => {
    if (!editor) return;
    const autoRefresh = cfg().get<boolean>('autoRefresh', true);
    if (!autoRefresh) return;

    const delay = cfg().get<number>('autoRefreshDelay', 2000);
    provider?.scheduleRefresh(delay);
    loadContextForEditor(editor, workspaceRoot, getPython());
  }));

  // 加入所有 disposable 到 context
  disposables.push(provider);
  context.subscriptions.push(...disposables);
}

export function deactivate(): void {
  for (const d of disposables) {
    try { d.dispose(); } catch {}
  }
  provider = null;
}

// ── 輔助函數 ─────────────────────────────────────────────────────

async function loadStatus(workdir: string, python: string): Promise<void> {
  try {
    const out = await runBrainCommand(python, workdir, ['status']);
    // 支援中英文格式：「123 個知識節點」或「nodes: 123」
    const nodeMatch = out.match(/(\d+)\s*(?:個知識節點|nodes)/i);
    const edgeMatch = out.match(/(\d+)\s*(?:條關係|edges)/i);
    if (nodeMatch) {
      provider?.updateStatus({
        nodes: parseInt(nodeMatch[1], 10),
        edges: edgeMatch ? parseInt(edgeMatch[1], 10) : 0,
      });
    }
  } catch {
    // 靜默失敗，不顯示錯誤
  }
}

async function loadContextForEditor(
  editor: vscode.TextEditor,
  workdir: string,
  python: string,
): Promise<void> {
  const filePath = editor.document.uri.fsPath;
  const relPath  = path.relative(workdir, filePath);

  // 只處理工作區內的檔案
  if (relPath.startsWith('..') || path.isAbsolute(relPath)) return;

  // 從檔案名稱和當前游標附近的文字推測任務
  const cursor    = editor.selection.active;
  const lineText  = editor.document.lineAt(cursor.line).text.slice(0, 100);
  const taskHint  = `正在編輯 ${path.basename(filePath)}：${lineText}`.slice(0, MAX_INPUT_LEN);

  try {
    const out = await runBrainCommand(python, workdir, [
      'context', taskHint, '--file', relPath
    ]);

    if (!out.trim()) {
      provider?.updateItems([]);
      return;
    }

    // 簡單解析 context 輸出為 KnowledgeNode 陣列
    const items = parseContextOutput(out);
    provider?.updateItems(items);
  } catch {
    // 靜默失敗
  }
}

function parseContextOutput(raw: string): KnowledgeNode[] {
  const items: KnowledgeNode[] = [];
  const sections = raw.split(/###\s+/);
  for (const section of sections.slice(1)) {
    const lines = section.split('\n');
    const header = lines[0] || '';
    const typeMatch = header.match(/^(⚠️?|🎯|📋|📄)\s+(.+?)：(.+)/u);
    if (typeMatch) {
      const typeMap: Record<string, string> = {
        '⚠️': 'Pitfall', '⚠': 'Pitfall',
        '🎯': 'Decision', '📋': 'Rule', '📄': 'ADR',
      };
      items.push({
        type:    typeMap[typeMatch[1]] ?? 'Decision',
        title:   typeMatch[3].trim(),
        content: lines.slice(1).join('\n').trim(),
      });
    }
  }
  return items.slice(0, 10);  // 最多 10 筆
}
