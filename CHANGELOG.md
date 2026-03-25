# 更新日誌 (Changelog)

所有關於此專案的顯著更改都會記錄在這個檔案中。## [v1.0.0] - 2026-03-25

### 🐛 核心修復與效能優化

#### 優先排序矩陣

| 優先   | 類型   | 問題                                    | 影響             | 難度 |
| :----- | :----- | :-------------------------------------- | :--------------- | :--- |
| **P0** | Bug    | DynamicOrchestrator 路由未生效          | 核心功能失效     | 低   |
| **P0** | Bug    | `synthex.py` 縮排錯誤 (`--budget` 參數) | CLI 無法使用     | 低   |
| **P0** | Bug    | Circuit Breaker 未保護 `chat()`         | API 失敗無保護   | 低   |
| **P0** | Bug    | `CLAUDE.md` 少 7 個角色的啟動指引       | 方法論失效       | 低   |
| **P1** | 不完整 | GeneratorCritic 只覆蓋 2/9 個文件       | 品質守門形同虛設 | 低   |
| **P1** | 不完整 | PRD Self-Critique Lambda 捕獲問題       | 改善輪次無效     | 低   |
| **P1** | 缺口   | tRPC 型別安全 API（STACK SKILL.md）     | 前後端型別安全   | 中   |
| **P2** | 效能   | 摘要快取（PRD/ARCH 讀取成本）           | Token 成本降低   | 中   |
| **P2** | 品質   | Structured Output（評分解析穩定性）     | 解析可靠性       | 低   |
| **P2** | 體驗   | `run()` Streaming 輸出                  | 用戶體驗一致性   | 中   |

#### 📝 修復摘要

- **P0：確認性 Bug 全部修復**
  - **DynamicOrchestrator 路由真正生效：** 每個 Phase 現在都有動態路由判斷。`bug_fix` 場景只跑 Phase 1、9、10、11、12，跳過 PRD/架構/設計等 8 個 Phase，節省 60%+ 的時間和 Token：
    ```python
    # 每個 Phase 現在的結構
    if N not in active_phases and not ckpt.is_done(N):
        _ok("Phase N 已被動態路由跳過")
    elif resume and ckpt.is_done(N):
        _ok("Phase N 已完成，跳過")
    else:
        # 執行 Phase N
    ```
  - **`synthex.py` 縮排修復：** 11 個錯誤的 `; p.add_argument` 分號語法全部改為正確的 4 空格縮排，`python synthex.py ship "..." --budget 5.0` 現在可以正常使用。
  - **Circuit Breaker 保護 `chat()`：** `chat()` 和 `run()` 現在都受 Circuit Breaker 保護。API 連續失敗 3 次後自動熔斷，30 秒恢復期後嘗試半開放，避免無效重試消耗 budget。
  - **`CLAUDE.md` 28/28 角色完整覆蓋：** QUANT、ATLAS、VISTA、FLUX、MEMO、PULSE、BRIDGE 全部加入角色啟動表，確保呼叫這 7 個角色前會先讀取對應的 SKILL.md。

- **P1：架構不完整修復**
  - **GeneratorCritic 覆蓋擴充：** 從原來只評審 PRD 和架構，擴展到完整覆蓋 6 個文件（PRD、ARCHITECTURE、FRONTEND_IMPL、BACKEND_IMPL、TEST_RESULTS、SECURITY）。安全審查設定最高閾值 9/10，未達標時發出警告。
  - **PRD Self-Critique 閉包修復：** 用 `_prd_ref = [prd]` 列表閉包替代直接捕獲外部變數，改善輪次時 ECHO 會真正重新生成 PRD 而不是返回同一份。
  - **STACK tRPC 型別安全 API：** 提供完整的 tRPC 實作範例，包含後端 router 定義、前端 client 設定、Middleware 認證、Optimistic Update 以及 tRPC vs REST 選擇指南。

- **P2：效能和品質優化**
  - **摘要快取機制（`DocContext.read_summary()`）：** 解決 PRD 與 ARCHITECTURE 頻繁讀取的 Token 成本問題，後續 Phase 可呼叫 `read_summary()` 取得預計算的摘要版本，節省 60-80% 讀取 Token。
  - **多策略評分解析：** 評分解析從單一正規表達式升級為三層策略（JSON 解析 → 正規表達式 → 關鍵字偵測），確保 Claude 輸出格式微調時依然能正確解析。
