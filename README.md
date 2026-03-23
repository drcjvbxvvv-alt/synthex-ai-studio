# SYNTHEX AI STUDIO — 完整發布包

## 這個包含什麼

```
synthex-release/
│
├── README.md                        ← 你正在讀的這個
│
├── synthex-ai-studio/               ← CLI 工具（Python）
│   ├── synthex.py                   ← 主入口
│   ├── requirements.txt
│   ├── README.md                    ← 完整使用說明
│   ├── CLAUDE.md                    ← 最新版（同 project-template）
│   ├── core/
│   │   ├── base_agent.py            ← Agent 基底
│   │   ├── orchestrator.py          ← 智能路由
│   │   ├── tools.py                 ← 基礎工具（讀寫檔案、執行命令）
│   │   ├── web_tools.py             ← 網頁開發工具（npm、git）
│   │   └── web_orchestrator.py      ← /discover + /ship 流水線
│   ├── agents/
│   │   └── all_agents.py            ← 全部 24 位 Agent 定義
│   └── memory/                      ← Agent 記憶（執行後自動產生）
│
└── project-template/                ← 複製到每個專案根目錄
    ├── CLAUDE.md                    ← 給 Claude Code 的公司作業系統
    └── agents/                      ← 8 位高頻角色的完整技能手冊
        ├── SPARK/SKILL.md           ← UX 方法論、線框格式
        ├── PRISM/SKILL.md           ← 設計系統、tokens.css 規範
        ├── NEXUS/SKILL.md           ← 技術選型、架構文件格式
        ├── BYTE/SKILL.md            ← 前端實作標準
        ├── STACK/SKILL.md           ← 後端實作標準
        ├── FORGE/SKILL.md           ← 設定檔範本、CI/CD
        ├── PROBE/SKILL.md           ← 測試策略框架
        └── SHIELD/SKILL.md          ← 安全審查清單
```

---

## 兩個部分的用途

### `synthex-ai-studio/` — 放在你的工具目錄

```bash
mv synthex-ai-studio ~/tools/
cd ~/tools/synthex-ai-studio

pip install -r requirements.txt
export ANTHROPIC_API_KEY="your-key"

# 設定你的專案目錄
python synthex.py workdir ~/projects/my-app

# 需求模糊時
python synthex.py discover "我想做一個..."

# 需求清楚時，一氣呵成
python synthex.py ship "電商平台：商品瀏覽、購物車、Stripe 結帳..."
```

### `project-template/` — 複製到每個專案

```bash
# 每次開新專案，把這個目錄的內容複製進去
cp -r project-template/CLAUDE.md  ~/projects/my-app/
cp -r project-template/agents     ~/projects/my-app/

# 然後開啟 Claude Code
cd ~/projects/my-app
claude

# 在 Claude Code 裡輸入
/ship 你的需求
```

---

## 標準工作流程

```
Step 1  需求模糊？
        python synthex.py discover "模糊想法"
        → 產出 docs/DISCOVER.md + 建議的 /ship 指令

Step 2  確認需求，執行 /ship
        python synthex.py ship "完整需求描述"
        → 產出程式碼骨架 + PRD + 架構文件

Step 3  開啟 Claude Code 精修
        cd ~/projects/my-app && claude
        → 帶著 docs/ 裡的文件，用角色指令繼續開發
        → "@BYTE 根據 docs/PRD.md 完善表單驗證"
```

---

## 需要填寫的地方

`project-template/CLAUDE.md` 中的「專案資訊」區塊：

```
目錄結構  ← 第一次 /ship 後，把產出的目錄結構貼進來
常用指令  ← 補充你的 DB migration 等自訂指令
環境變數  ← 第一次 /ship 後，把 .env.local.example 的 key 列表貼進來
禁止事項  ← 你的專案特有限制
```

品牌和技術由角色決定（已在 CLAUDE.md 設定），這四個由你補充。

---

*SYNTHEX AI STUDIO · 24 Agents · 18 Tools · Built with Claude*
