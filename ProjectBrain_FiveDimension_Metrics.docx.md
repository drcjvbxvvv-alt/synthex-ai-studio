  
**PROJECT BRAIN**

五維指標範本

*走向 · 穩定性 · 新技術誠實性 · 未來性機械設計 · 壟斷策略具體化*

v0.6.0  |  2026-04-04  |  內部量測文件

**使用說明**

本範本定義 Project Brain 五個核心維度的量測指標。每個指標附有：定義與門檻值、量測方法（含 SQL 或 CLI 指令）、以及當前狀態評估。每個版本發布前，逐一核查各維度指標，確認達標後才發布。

使用流程：(1) 每個 minor 版本發布前執行完整核查  (2) 未達標的指標列入下版優先事項  (3) Gate 條件欄位的指標是硬性發布阻塞點，不可跳過

| 一、走向（Direction）   *版本閘門品質* |
| :---- |

衡量計劃的執行紀律：每個版本的功能說到就做到，不出現打勾但未實作的情況。

| 指標 | 定義 / 門檻 | 量測方法 / 現況 |
| :---- | :---- | :---- |
| 版本發布條件達成率 | 每版本列出的所有 Gate 條件必須 100% 達成才能發布。這是最重要的方向指標。 | CHANGELOG 每版本 Gate checklist 完成數 ÷ 總數。目標：100%。現況：v0.5.0\~v0.6.0 已達成。 |
| 計劃打勾 vs 程式碼實際完成率 | 每個「✅ 完成」項目必須有對應 commit 可追溯，且行號可查。 | 每版本 code review 隨機抽查 5 項。目標：100%。v0.6.0 發現 graphiti\_url 描述不精確。 |
| 技術債清零週期 | 從「發現問題」到「進入版本計劃」最長等待時間 ≤ 2 個版本；P0 問題 ≤ 當版本修復。 | IMPROVEMENT\_PLAN 歷史紀錄，計算每個 Bug ID 從出現到 ✅ 的版本跨距。 |
| Arch-Ready vs 端對端可用比例 | 功能表中 🟢 端對端可用 ÷ (🟢 \+ 🟡 架構就緒) ≥ 70%。 | 現況：LoRA 路徑、ANN HNSW 仍是 🟡。待 v0.7.0 TECH-01 完成標記後量測。 |
| 版本週期一致性 | 相鄰版本的完成項目數量差距 ≤ 30%（避免一版爆量、一版空洞）。 | CHANGELOG 各版本 completed items 數量統計。 |

| *▶  v0.5.0 \~ v0.6.0 所有 Gate 條件已達成，方向指標健康。下一個阻塞點是 REV-01 對照實驗。* |
| :---- |

| 二、穩定性（Stability）   *可觀察性 × 靜默失效數* |
| :---- |

衡量系統在異常情況下的行為品質：失敗必須可見、錯誤必須可修復、測試必須能抓到問題。

| 指標 | 定義 / 門檻 | 量測方法 / 現況 |
| :---- | :---- | :---- |
| 靜默失效路徑數 | codebase 中 except 後接 pass（無任何 logging）的數量。目標：0。 | grep \-rn 'except' \--include='\*.py' 後過濾無 logger 行。v0.6.0 修復後應為 0，每版本核查。 |
| Migration 失敗可觀察率 | schema 升級失敗必須在 brain doctor 中顯示。100% 不可靜默。 | 測試：故意破壞 schema v11 後執行 brain doctor，確認有 warning 輸出。目標：100%。 |
| Chaos test 通過率 | tests/chaos/test\_chaos\_and\_load.py 在每個版本 CI 中全數通過。目標：100%。 | 現況：Chaos test 存在但未接 CI gate。待加入 pyproject.toml 的 pytest 配置。 |
| SR node 追蹤準確率 | context.py:316 title 子字串比對的誤判率。目標：改為 node ID 比對，誤判率降至 0。 | 現況：仍是 title 子字串比對。當 title 含截斷或 emoji 時易誤判。P1 待修。 |
| ReviewBoard.db 損壞恢復能力 | 故意損壞 review\_board.db 後，brain review list 必須給出可操作的錯誤訊息，而非 stack trace。 | 現況：ReviewBoard.db 無 schema 版控，損壞無遷移路徑。計劃中未列入——是唯一的穩定性盲點。 |

| *△  SR node 追蹤 \+ ReviewBoard.db 是兩個未解決的穩定性風險。前者計劃已列，後者尚未列入。* |
| :---- |

| 三、新技術誠實性（Tech Honesty）   *說到做到的一致性* |
| :---- |

衡量對外宣稱的功能與實際可用程度之間的一致性。誠實性是技術社群信任的基礎。

| 指標 | 定義 / 門檻 | 量測方法 / 現況 |
| :---- | :---- | :---- |
| 功能狀態標記覆蓋率 | README 和 CHANGELOG 中每個功能都有 🟢 端對端可用 / 🟡 架構就緒 / 🔴 實驗性 標記。目標：100%。 | 現況：0%。TECH-01 在 v0.7.0 計劃中。但這不需要版本——現在就可以改文件。 |
| LoRA 路徑說明準確性 | README 中 brain distill 的說明必須明確：「產生 JSONL，實際訓練需自行執行 Axolotl / Unsloth」。 | 現況：README 未更新。這是最快能做的誠實性修復，不需要等 v0.7.0。 |
| Synonym Map 條目數一致性 | brain\_db.\_SYNONYM\_MAP 與 context.py.\_SYNONYM\_MAP 的條目數差距 ≤ 2。 | 現況：30 條（brain\_db）vs 45 條（context.py），差距 15 條。計劃說「已同步」但未完全。 |
| ANN 觸發條件文件化 | HNSW 的適用節點數門檻（建議 \> 2000）必須在安裝文件中標注。 | 現況：未標注。TECH-03 在 v0.7.0 計劃中。 |
| 每版本宣稱 vs 實際審計 | 每次發布前隨機抽查 CHANGELOG 裡 3 個「完成」項目，驗證程式碼裡有對應實作（commit hash \+ 行號）。 | v0.6.0 已執行：發現 graphiti\_url「已移除」描述不精確。此機制應制度化。 |

| *△  LoRA README 說明和功能狀態標記是兩個現在就能做、不需等版本的動作。* |
| :---- |

| 四、未來性機械設計（Flywheel）   *飛輪是否在轉動* |
| :---- |

衡量知識自動積累機制的實際運作狀態。飛輪轉動的條件是：知識生產不依賴人工。

| 指標 | 定義 / 門檻 | 量測方法 / 現況 |
| :---- | :---- | :---- |
| 知識庫自然成長率 | 不手動 brain add 的情況下，7 天內 complete\_task 自動寫入的節點數 ≥ 5。 | SQL：SELECT COUNT(\*) FROM nodes WHERE tags LIKE '%auto:complete\_task%' AND created\_at \>= datetime('now','-7 days')。現況：0（未開始）。 |
| NudgeEngine 命中率 | 呼叫 get\_context 時，nudge 至少出現一次的比例 ≥ 30%（知識庫 \> 20 節點後）。 | 量測：events 表 nudge\_triggered 事件數 ÷ get\_context 總呼叫數。現況：0（未量測）。 |
| REV-01 對照實驗完成 | 30 天實驗完成，有可量化輸出：Agent 重複犯錯次數（無 Brain）vs（有 Brain）的差值。 | v0.6.0 發布阻塞點。現況：尚未開始。這是飛輪效益被第三方相信的唯一依據。 |
| get\_context 召回率 | 50 節點測試庫上 ≥ 60%（sentence-transformers）或 ≥ 40%（LocalTFIDF）。 | UNQ-03 基準測試資料集待建立。沒有這個數字，飛輪效益無從量化。現況：0（未建立）。 |
| 飛輪啟動時間（Time to First Value） | 從 brain setup 到第一次 get\_context 返回有效 Pitfall 的時間 ≤ 48 小時（含冷啟動期）。 | 前提：MON-02 官方 bundle 存在。brain fed import official-bundle 讓第一天就有 20 條。現況：bundle 未建立。 |

| *✗  飛輪機械部件已接通，但四個核心量測指標全部尚未有數據。REV-01 是最緊迫的行動點。* |
| :---- |

| 五、壟斷策略具體化（Moat）   *網路效應 × 數據護城河* |
| :---- |

衡量聯邦知識網路的建設進度。壟斷的本質是數據飛輪：越多人貢獻知識，系統對所有人越有價值。

| 指標 | 定義 / 門檻 | 量測方法 / 現況 |
| :---- | :---- | :---- |
| 官方 bundle 覆蓋率 | MON-02 官方 bundle：JWT、Webhook、DB migration、Cache、CORS 各至少 3 條 Pitfall，共 20 條，每條有可引用來源。 | v0.7.0 發布前完成。現況：0 條（bundle 尚未建立）。內容設計應在 v0.6.0 期間就開始。 |
| 聯邦知識去重率 | 從外部 bundle import 的節點中，與本地知識庫語義重複（cos similarity \> 0.85）的比例 ≤ 20%。 | 量測：brain fed import 時的 dedup 報告。過高代表 bundle 內容同質化。現況：未量測。 |
| 第三方引用數 | 官方 bundle 發布後，被第三方 brain fed import 的次數 ≥ 1（v0.7.0 Gate 條件）。 | 從 GitHub release download 數量估算。現況：0。 |
| 競品差距量化追蹤 | 每季對比 MemCoder / Lore / Graphiti：F2 版本落差衰減、F3 git 活動反衰減、complete\_task 閉環是否仍為獨有。 | UNQ-02 工作。建立 docs/competitive-analysis.md，每季更新。現況：未建立。 |
| 官方 bundle 審核機制 | 進入官方 bundle 的每條 Pitfall 必須：(1) 有可引用來源，(2) KRB 人工審核通過，(3) confidence ≥ 0.85，(4) 無 global scope 污染風險。 | 現況：審核機制尚未設計。這是 MON-02 的前置條件，是聯邦知識網路能否被信任的根基。 |

| *✗  壟斷策略的商業骨架已有，但所有量測指標目前都是 0——v0.7.0 才能開始積累。先設計 bundle 審核機制。* |
| :---- |

## **立即可執行的三個動作（不需等版本）**

以下三件事不需要任何版本號，今天就能做：

* 把 brain distill 的 LoRA 說明更新到 README：「產生 JSONL，實際訓練需自行執行 Axolotl / Unsloth」（影響：新技術誠實性立即改善）

* 把 brain\_db.\_SYNONYM\_MAP 從 30 條補齊到 45 條，與 context.py 完全同步（影響：search\_knowledge 語義擴展能力提升 50%）

* 開始 REV-01 30 天對照實驗——這是 v0.6.0 唯一的發布阻塞點，也是飛輪效益和革命性聲明的唯一數據來源

*Project Brain Five-Dimension Metrics Template v0.6.0  ·  MIT License*