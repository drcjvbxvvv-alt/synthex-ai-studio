"""
core/brain/knowledge_distiller.py — 多模型知識蒸餾（v4.0）

功能：
  把整個 Project Brain 的知識庫壓縮成可攜帶的「知識摘要」。
  
  v4.0 實作三個層次：
  
  Layer 1 — Context Distillation（已實作）：
    把知識圖譜壓縮成結構化 Markdown 摘要（SYNTHEX_KNOWLEDGE.md）
    任何 LLM 都可以直接讀取，零外部依賴。
    → 可注入任何 AI 系統的 system prompt
    
  Layer 2 — System Prompt Injection（已實作）：
    生成針對不同 Agent 角色優化的 system prompt fragment
    → BYTE 得到前端知識，SHIELD 得到安全知識
    
  Layer 3 — LoRA Adapter（架構就緒，需要 GPU）：
    把知識轉換為訓練數據（instruction-following 格式）
    可用 Axolotl / Unsloth 訓練 LoRA adapter
    → 知識成為模型權重的一部分，推理時零延遲

設計哲學：
  知識蒸餾的目標不是「替代」 Project Brain，而是「延伸」它：
  - 在網路受限的環境（離線開發）
  - 在不支援工具調用的 LLM（需要知識但無法呼叫 API）
  - 在需要超低延遲的場景（system prompt 直接注入）
  
安全設計：
  - 輸出到 .brain/distilled/（不自動提交 git）
  - LoRA 訓練數據過濾 PII（與 federation.py 共用清理邏輯）
  - 摘要大小限制（防止 context window 被撐爆）
"""

from __future__ import annotations
from .output import OK, WARN, ERR, R, B, G, Y, C, P, GR, D, W, hr, section, badge

import re
import json
import time
import logging
import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ── 常數 ──────────────────────────────────────────────────────
MAX_SUMMARY_TOKENS    = 4_000    # 知識摘要的最大 token 估算
MAX_NODES_PER_LAYER   = 30       # 每個蒸餾類型最多節點數
MAX_NODE_CONTENT_CHARS= 400      # 單節點內容的最大字元數

# LoRA 訓練格式模板（Alpaca-style Instruction Tuning）
LORA_INSTRUCTION_TEMPLATE = """\
{{
  "instruction": "{instruction}",
  "input": "{context}",
  "output": "{answer}"
}}"""

# 角色知識映射（哪個 Agent 需要哪些類型的知識）
ROLE_KNOWLEDGE_MAP: dict[str, list[str]] = {
    "NEXUS": ["Decision", "ADR", "Component"],
    "SHIELD": ["Pitfall", "Rule"],
    "BYTE":   ["Pitfall", "Rule", "Component"],
    "STACK":  ["Decision", "Rule", "Component"],
    "ECHO":   ["Decision", "Rule"],
    "TRACE":  ["Pitfall", "Component"],
    "ARIA":   ["Decision", "ADR", "Pitfall"],
}


@dataclass
class DistillationResult:
    """蒸餾產出摘要"""
    total_nodes:    int
    token_estimate: int
    output_files:   list[str]
    layers_done:    list[str]
    elapsed_ms:     int

    def summary(self) -> str:
        from .output import OK, B, G, Y, C, GR, R, W, hr
        files_str = "\n    ".join(self.output_files)
        return (
            f"\n{G}{B}⚗  知識蒸餾完成{R}\n{GR}{hr()}{R}\n"
            f"  {B}節點{R}      {W}{self.total_nodes}{R} 筆  "
            f"{GR}│{R}  {B}token 估算{R}  {W}{self.token_estimate:,}{R}\n"
            f"  {B}完成層次{R}  {G}{', '.join(self.layers_done)}{R}\n"
            f"  {B}輸出{R}\n    {GR}{files_str}{R}\n"
            f"  {B}耗時{R}      {W}{self.elapsed_ms}{R} ms\n"
            f"{GR}{hr()}{R}"
        )


# ══════════════════════════════════════════════════════════════
#  KnowledgeDistiller
# ══════════════════════════════════════════════════════════════

class KnowledgeDistiller:
    """
    多層知識蒸餾器（v4.0）。
    
    使用方式：
        distiller = KnowledgeDistiller(graph, brain_dir=Path(".brain"))
        result = distiller.distill_all()
        print(result.summary())
        
        # 只蒸餾特定角色
        prompt_fragment = distiller.distill_for_agent("SHIELD")
    """

    def __init__(
        self,
        graph,                          # KnowledgeGraph 實例
        brain_dir:   Path,
        workdir:     Path | None = None,
    ):
        self.graph    = graph
        self.brain_dir = Path(brain_dir)
        self.workdir  = workdir
        self.out_dir  = self.brain_dir / "distilled"
        self.out_dir.mkdir(parents=True, exist_ok=True)

    # ── 主入口 ────────────────────────────────────────────────

    def distill_all(self, layers: list[str] | None = None) -> DistillationResult:
        """
        執行完整知識蒸餾。

        Args:
            layers: 要執行的層次（None = 全部）
                    "context"  — Markdown 摘要
                    "prompts"  — 角色 system prompt 片段
                    "lora"     — LoRA 訓練數據（JSON）
        """
        t0     = time.monotonic()
        layers = layers or ["context", "prompts", "lora"]
        done_layers  = []
        output_files = []
        all_nodes    = self._get_all_nodes()

        if "context" in layers:
            path = self._distill_context(all_nodes)
            output_files.append(str(path.relative_to(self.brain_dir)))
            done_layers.append("context")
            print(f"  {OK} {B}Layer 1{R} Context Distillation  {GR}→{R} {W}{path.name}{R}")

        if "prompts" in layers:
            paths = self._distill_role_prompts(all_nodes)
            output_files.extend(str(p.relative_to(self.brain_dir)) for p in paths)
            done_layers.append("prompts")
            print(f"  {OK} {B}Layer 2{R} Role Prompts  {GR}→{R} {W}{len(paths)}{R} 個角色")

        if "lora" in layers:
            path = self._distill_lora_dataset(all_nodes)
            output_files.append(str(path.relative_to(self.brain_dir)))
            done_layers.append("lora")
            print(f"  {OK} {B}Layer 3{R} LoRA Dataset  {GR}→{R} {W}{path.name}{R}")

        token_est = sum(
            len(n.get("content", n.get("description", ""))) // 4
            for n in all_nodes
        )

        return DistillationResult(
            total_nodes    = len(all_nodes),
            token_estimate = token_est,
            output_files   = output_files,
            layers_done    = done_layers,
            elapsed_ms     = int((time.monotonic() - t0) * 1_000),
        )

    # ── Layer 1：Context Distillation ─────────────────────────

    def _distill_context(self, nodes: list[dict]) -> Path:
        """
        壓縮整個知識圖譜為結構化 Markdown（SYNTHEX_KNOWLEDGE.md）。
        任何 LLM 都可以直接讀取，作為 system prompt 的一部分。
        """
        sections: dict[str, list[str]] = {
            "Pitfall": [], "Rule": [], "Decision": [], "ADR": [], "Component": [],
        }

        token_budget = MAX_SUMMARY_TOKENS
        high_conf    = sorted(nodes, key=lambda x: -float(x.get("confidence", 0)))

        for node in high_conf:
            if token_budget <= 0:
                break
            kind    = node.get("kind", "")
            title   = node.get("title", "")
            content = node.get("content", node.get("description", ""))[:MAX_NODE_CONTENT_CHARS]
            conf    = float(node.get("confidence", 0.5))
            tags    = ", ".join(node.get("tags", []))

            if kind not in sections or not title.strip():
                continue
            if len(sections[kind]) >= MAX_NODES_PER_LAYER:
                continue

            entry = f"### {title} ({conf:.0%})\n{content}"
            if tags:
                import json as _json
                try:
                    _tlist = _json.loads(tags) if isinstance(tags, str) and tags.startswith('[') else (tags if isinstance(tags, list) else [])
                    _tstr = ", ".join(str(t) for t in _tlist)
                except Exception:
                    _tstr = ""
                if _tstr:
                    entry += f"\n`{_tstr}`"
            sections[kind].append(entry)
            token_budget -= len(entry) // 4

        # 組裝 Markdown
        lines = [
            "# SYNTHEX 專案知識庫 — 蒸餾版",
            f"> 生成時間：{datetime.now(timezone.utc).isoformat()[:10]}",
            f"> 節點總數：{len(nodes)} | 版本：v4.0",
            "",
            "---",
        ]

        type_labels = {
            "Pitfall":   "⚠ 踩坑記錄",
            "Rule":      "📋 業務規則",
            "Decision":  "🎯 架構決策",
            "ADR":       "📄 ADR",
            "Component": "🧩 系統組件",
        }

        for kind, entries in sections.items():
            if not entries:
                continue
            lines.append(f"\n## {type_labels.get(kind, kind)}")
            lines.extend(entries)

        lines.extend([
            "",
            "---",
            "*此文件由 Project Brain v4.0 自動生成，禁止手動編輯*"
        ])

        content = "\n".join(lines)
        path    = self.out_dir / "SYNTHEX_KNOWLEDGE.md"
        path.write_text(content, encoding="utf-8")
        return path

    # ── Layer 2：角色 System Prompt 片段 ──────────────────────

    def _distill_role_prompts(self, nodes: list[dict]) -> list[Path]:
        """
        為每個 SYNTHEX Agent 角色生成針對性的 system prompt 片段。
        SHIELD 看到安全知識，BYTE 看到前端知識。
        """
        paths = []

        for role, kinds in ROLE_KNOWLEDGE_MAP.items():
            role_nodes = [n for n in nodes if n.get("kind") in kinds]
            role_nodes = sorted(role_nodes,
                                key=lambda x: -float(x.get("confidence", 0)))[:15]

            if not role_nodes:
                continue

            lines = [
                f"## {role} 專屬知識（Project Brain v4.0 蒸餾）",
                f"以下是與 {role} 職責相關的歷史知識，請納入工作考量：",
                "",
            ]

            for node in role_nodes:
                kind    = node.get("kind", "")
                title   = node.get("title", "")
                content = node.get("content",
                          node.get("description", ""))[:200]
                conf    = float(node.get("confidence", 0.5))
                icon    = {"Pitfall": "⚠", "Rule": "📋",
                           "Decision": "🎯", "ADR": "📄"}.get(kind, "•")
                lines.append(f"{icon} [{kind}] **{title}** ({conf:.0%})")
                if content:
                    lines.append(f"   {content}")
                lines.append("")

            content = "\n".join(lines)
            path    = self.out_dir / f"prompt_{role.lower()}.md"
            path.write_text(content, encoding="utf-8")
            paths.append(path)

        return paths

    def distill_for_agent(self, agent_name: str) -> str:
        """
        為指定 Agent 生成 system prompt 注入片段（即時版本）。
        不需要事先執行 distill_all()。
        """
        kinds    = ROLE_KNOWLEDGE_MAP.get(agent_name.upper(), ["Pitfall", "Rule"])
        all_nodes = self._get_all_nodes(kinds=kinds)
        top_nodes = sorted(all_nodes,
                           key=lambda x: -float(x.get("confidence", 0)))[:10]

        if not top_nodes:
            return ""

        lines = [f"## 來自 Project Brain 的專案知識（for {agent_name}）"]
        for node in top_nodes:
            icon = {"Pitfall": "⚠", "Rule": "📋",
                    "Decision": "🎯", "ADR": "📄"}.get(node.get("kind", ""), "•")
            title   = node.get("title", "")
            content = node.get("content",
                      node.get("description", ""))[:200]
            conf    = float(node.get("confidence", 0.5))
            lines.append(f"{icon} [{node.get('kind','')}] {title} ({conf:.0%})")
            if content:
                lines.append(f"   {content}")

        return "\n".join(lines)

    # ── Layer 3：LoRA 訓練數據 ─────────────────────────────────

    def _distill_lora_dataset(self, nodes: list[dict]) -> Path:
        """
        生成 LoRA adapter 訓練數據（Alpaca instruction-following 格式）。
        
        輸出：.brain/distilled/lora_dataset.jsonl
        
        可用以下工具訓練：
          - Axolotl：  axolotl finetune config.yml
          - Unsloth：  pip install unsloth && python train.py
          - LLaMA-Factory：llamafactory-cli train config.json
          
        注意：
          訓練 LoRA 需要 GPU（>= 24GB VRAM for 7B models）
          v4.0 只生成訓練數據，不執行訓練
        """
        dataset: list[dict] = []

        for node in nodes:
            kind    = node.get("kind", "")
            title   = node.get("title", "")
            content = node.get("content", node.get("description", ""))
            conf    = float(node.get("confidence", 0.5))
            tags    = " ".join(node.get("tags", []))

            if not title or not content or conf < 0.3:
                continue

            # 過濾 PII
            if self._contains_pii(title + " " + content):
                continue

            # 生成問答對（instruction-following 格式）
            entries = self._node_to_qa(kind, title, content, tags)
            dataset.extend(entries)

        # 寫入 JSONL（每行一個 JSON 物件）
        path = self.out_dir / "lora_dataset.jsonl"
        with path.open("w", encoding="utf-8") as f:
            for entry in dataset:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")

        # 訓練配置模板（供參考）
        config_path = self.out_dir / "lora_training_config.yaml"
        config_path.write_text(self._generate_training_config(len(dataset)),
                               encoding="utf-8")

        logger.info("lora_dataset_generated | count=%s", len(dataset), path=str(path))
        return path

    def _node_to_qa(
        self, kind: str, title: str, content: str, tags: str
    ) -> list[dict]:
        """把一個知識節點轉換成多個問答對"""
        pairs = []
        context = f"專案背景：{tags}" if tags else ""

        if kind == "Pitfall":
            pairs.append({
                "instruction": f"在實作「{title}」相關功能時，有什麼需要特別注意的踩坑？",
                "input":       context,
                "output":      content,
            })
            pairs.append({
                "instruction": f"如何避免「{title}」這個問題？",
                "input":       context,
                "output":      f"根據歷史記錄：{content}",
            })

        elif kind == "Rule":
            pairs.append({
                "instruction": f"「{title}」這條業務規則的具體要求是什麼？",
                "input":       context,
                "output":      content,
            })

        elif kind in ("Decision", "ADR"):
            pairs.append({
                "instruction": f"關於「{title}」，我們的架構決策是什麼？背後的理由是什麼？",
                "input":       context,
                "output":      content,
            })

        elif kind == "Component":
            pairs.append({
                "instruction": f"「{title}」這個組件的主要功能和注意事項是什麼？",
                "input":       context,
                "output":      content,
            })

        return pairs

    def _generate_training_config(self, dataset_size: int) -> str:
        """生成 Axolotl 風格的訓練配置（供用戶參考）"""
        return f"""\
# LoRA 訓練配置（由 Project Brain v4.0 自動生成）
# 使用 Axolotl 訓練：axolotl finetune lora_training_config.yaml

base_model: unsloth/Meta-Llama-3.1-8B-Instruct
model_type: LlamaForCausalLM
tokenizer_type: AutoTokenizer

# 資料集（由 Project Brain 生成的知識蒸餾數據）
datasets:
  - path: {str(self.out_dir / 'lora_dataset.jsonl')}
    type: alpaca

# 訓練樣本數：{dataset_size}
val_set_size: 0.05
sequence_len: 2048

adapter: lora
lora_r: 16
lora_alpha: 32
lora_dropout: 0.05
lora_target_modules:
  - q_proj
  - v_proj
  - k_proj
  - o_proj

micro_batch_size: 2
gradient_accumulation_steps: 4
num_epochs: 3
learning_rate: 0.0002
optimizer: adamw_torch
lr_scheduler: cosine
warmup_steps: 10

output_dir: ./outputs/project-brain-lora
# 注意：需要 GPU >= 24GB VRAM（RTX 3090 / A100 / H100）
"""

    # ── 工具方法 ──────────────────────────────────────────────

    def _get_all_nodes(self, kinds=None):
        """取得所有節點（適配 KnowledgeGraph 的 type 欄位）"""
        try:
            conn = self.graph._conn
            if kinds:
                ph = ",".join("?" * len(kinds))
                rows = conn.execute(
                    f"SELECT id, type as kind, title, content, tags, created_at "
                    f"FROM nodes WHERE type IN ({ph}) LIMIT 500", kinds
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT id, type as kind, title, content, tags, created_at "
                    "FROM nodes LIMIT 500"
                ).fetchall()
            result = []
            for r in rows:
                d = dict(r)
                d.setdefault("confidence", 0.7)
                d.setdefault("description", "")
                result.append(d)
            return result
        except Exception as e:
            import logging
            logging.getLogger(__name__).error("get_nodes_failed: %s", str(e)[:100])
            return []

    def _contains_pii(self, text: str) -> bool:
        """簡單 PII 偵測（複用 federation.py 的邏輯）"""
        pii_patterns = [
            re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'),
            re.compile(r'\b(?:\d{1,3}\.){3}\d{1,3}\b'),
            re.compile(r'sk-[a-zA-Z0-9]{20,}'),
        ]
        for p in pii_patterns:
            if p.search(text):
                return True
        return False

    def distillation_status(self) -> dict:
        """查詢蒸餾輸出狀態"""
        files = list(self.out_dir.glob("*")) if self.out_dir.exists() else []
        return {
            "output_dir":   str(self.out_dir),
            "files":        [f.name for f in files],
            "total_size_kb": sum(f.stat().st_size for f in files
                                  if f.is_file()) // 1024,
        }
