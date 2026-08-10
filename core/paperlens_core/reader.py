"""Bounded paper-QA workflow: plan, retrieve, draft, validate, attribute, display."""

from __future__ import annotations

import json
import logging
import uuid
from collections import OrderedDict
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .evidence import EvidenceGuard, build_evidence_ledger, render_evidence_label
from .llm import StructuredModel
from .models import AnswerDraft, EvidenceItem, GroundedAnswer, SupportStatus
from .prompts import (
    ATTRIBUTION_VERIFIER_SYSTEM,
    QUERY_PLANNER_FEW_SHOT,
    QUERY_PLANNER_SYSTEM,
    READER_ADVERSARIAL_EXAMPLES,
    READER_SYSTEM,
    evidence_package,
)
from .retrieval import BM25Index, retrieval_is_sufficient

# 挂到应用日志树（server logging_config 只给 "paperlens" 树挂 handler）；
# __name__（paperlens_core.reader）propagate 到 root 会丢进文件
logger = logging.getLogger("paperlens.core.reader")

# V3.17 draft 会话缓存：同一 (论文版本, 问题, 命中证据集) 的 draft 输出复用。
# 实训/demo 反复问同一批问题（前端预设气泡是精确相同的字符串），draft 是
# 最贵一环（~13.7s）。键含命中 chunk 集：保证缓存主张引用的 evidence_id
# 一定存在于当次 ledger，确定性守卫不会因 UNKNOWN_EVIDENCE_ID 拒掉它们。
# 进程内 LRU（单进程 uvicorn），服务重启即清；论文重解析出新版本 id 后
# 键自然失效。命中时仍走 attribute 核验 + organize，管线语义不变。
_DRAFT_CACHE: OrderedDict[str, AnswerDraft] = OrderedDict()
_DRAFT_CACHE_MAX = 256


class OrganizedAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str = Field(min_length=1, max_length=2000)


class RewrittenQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rewritten_question: str = Field(min_length=1, max_length=1000)


HISTORY_REWRITE_SYSTEM = """You resolve references in the user's question using
the recent conversation, then output ONE self-contained question about the
paper. Rules:
- Resolve pronouns ("it", "this method", "上面那张表", "它") against the recent
  conversation context and the paper being discussed.
- Keep the question about the paper only; never answer it, never add facts.
- Output only the rewritten question, in the user's language."""


ORGANIZE_ANSWER_SYSTEM = """You write the final answer for a paper-QA question.

You receive the question and a list of VERIFIED claims (every claim is backed
by verbatim evidence from the paper). Write ONE coherent natural paragraph:
- Use the claims as facts; never invent numbers, names, results or methods.
- Do not enumerate claims or use bullet points; write flowing prose.
- 3-6 sentences, answer in the language of the question.
- If the claims cannot answer the question, say so briefly.""".strip()


class QueryPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent: Literal["method", "result", "limitation", "comparison", "reference", "other"]
    original_query: str = Field(min_length=1, max_length=500)
    english_query: str = Field(default="", max_length=500)
    keywords: list[str] = Field(default_factory=list, max_length=12)
    section_hints: list[str] = Field(default_factory=list, max_length=6)
    must_verify: list[str] = Field(default_factory=list, max_length=10)


class AttributionVerdict(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim_id: str
    verdict: SupportStatus
    rationale: str = Field(max_length=1200)


@dataclass(frozen=True, slots=True)
class ReaderEvent:
    event: Literal[
        "stage_started",
        "retrieval_hits",
        "claim_validated",
        "claim_rejected",
        "completed",
        "error",
    ]
    payload: dict[str, object]


def _fallback_plan(question: str) -> QueryPlan:
    lowered = question.casefold()
    if any(word in lowered for word in ("method", "方法", "训练", "algorithm")):
        intent = "method"
        hints = ["method", "approach", "algorithm"]
    elif any(word in lowered for word in ("result", "结果", "提升", "%")):
        intent = "result"
        hints = ["experiment", "result"]
    elif any(word in lowered for word in ("limit", "局限")):
        intent = "limitation"
        hints = ["limitation", "discussion"]
    else:
        intent = "other"
        hints = []
    return QueryPlan(
        intent=intent,
        original_query=question,
        english_query=question,
        keywords=[],
        section_hints=hints,
        must_verify=[],
    )


class PaperReader:
    """Run QA without exposing any unvalidated raw model token to the caller."""

    def __init__(self, model: StructuredModel):
        self.model = model

    # V4.3-4：多轮指代消解——历史只用于重写检索意图，
    # 不作为事实证据（所有事实仍回到 DocumentGraph）
    def _resolve_references(
        self, question: str, history: list[dict[str, str]], thread_id: str
    ) -> str:
        try:
            rewritten = self.model.invoke_json(
                system=HISTORY_REWRITE_SYSTEM,
                user=json.dumps(
                    {"recent_messages": history[-6:], "user_question": question},
                    ensure_ascii=False,
                ),
                schema=RewrittenQuestion,
                stage="history_rewrite",
                thread_id=thread_id,
                temperature=0.0,
            )
            result = rewritten.rewritten_question.strip()
            return result if result else question
        except Exception:  # noqa: BLE001 - rewrite is best-effort
            return question

    def plan(self, question: str, thread_id: str) -> QueryPlan:
        try:
            return self.model.invoke_json(
                system=QUERY_PLANNER_SYSTEM,
                user=f"{QUERY_PLANNER_FEW_SHOT}\n\nQuestion:\n{question}",
                schema=QueryPlan,
                stage="query_planner",
                thread_id=thread_id,
                temperature=0.0,
            )
        except Exception:
            return _fallback_plan(question)

    @staticmethod
    def _ledger_payload(ledger: list[EvidenceItem]) -> list[dict[str, object]]:
        return [
            {
                "evidence_id": item.evidence_id,
                "page": item.page_start,
                "section": item.section_path,
                "text": item.verbatim_excerpt,
            }
            for item in ledger
        ]

    def _verify_attribution(
        self, claim: object, ledger: dict[str, EvidenceItem], thread_id: str
    ) -> AttributionVerdict:
        # ``claim`` is an AnswerClaim; kept generic here to isolate serialization.
        evidence_links = claim.evidence_links
        quotes = [
            {
                "evidence_id": link.evidence_id,
                "quote": link.verbatim_quote,
                "section": ledger[link.evidence_id].section_path,
                "page": ledger[link.evidence_id].page_start,
            }
            for link in evidence_links
        ]
        user = json.dumps(
            {
                "claim_id": claim.claim_id,
                "claim": claim.text,
                "quotes": quotes,
            },
            ensure_ascii=False,
        )
        return self.model.invoke_json(
            system=ATTRIBUTION_VERIFIER_SYSTEM,
            user=user,
            schema=AttributionVerdict,
            stage="attribution_verifier",
            thread_id=thread_id,
            allow_repair=True,
            temperature=0.0,
        )

    def run_events(
        self,
        *,
        question: str,
        chunks: list[object],
        thread_id: str | None = None,
        top_k: int = 8,
        cache_namespace: str = "",
        context_scope: str = "whole_paper",
        context_block_ids: list[str] | None = None,
        history: list[dict[str, str]] | None = None,
        task_id: str = "",
    ) -> Iterator[ReaderEvent]:
        import time as _time

        t0 = _time.monotonic()
        timings: dict[str, float] = {}
        thread_id = thread_id or str(uuid.uuid4())
        question = question.strip()
        if not question:
            yield ReaderEvent("error", {"code": "EMPTY_QUESTION", "message": "问题不能为空。"})
            return
        yield ReaderEvent("stage_started", {"stage": "plan", "message": "正在理解问题边界"})
        # V4.3-4：多轮指代消解（历史只重写意图，不作证据）
        if history:
            resolved = self._resolve_references(question, history, thread_id)
            if resolved != question:
                logger.info("history rewrite: %r -> %r", question[:40], resolved[:60])
                question = resolved
        plan = self.plan(question, thread_id)
        timings["plan"] = round(_time.monotonic() - t0, 2)

        yield ReaderEvent("stage_started", {"stage": "retrieve", "message": "正在检索段落证据"})
        query = " ".join([plan.english_query or plan.original_query, *plan.keywords]).strip()
        # V4.3-3：TaskDefinition 侧重词并入检索查询与章节提示
        if task_id:
            from .tasks import get_task

            task = get_task(task_id)
            if task:
                emphasis = task.get("retrieval_emphasis")
                if emphasis:
                    query = f"{query} {' '.join(emphasis)}".strip()
                hints = list(plan.section_hints or [])
                for hint in task.get("section_hints") or []:
                    if hint not in hints:
                        hints.append(hint)
                plan = plan.model_copy(update={"section_hints": hints})
        # V4.3-1：上下文检索——当前段落/章节/选区限定
        # 检索范围（含这些 block 的 chunk），无命中则回退全文
        search_chunks = chunks
        if context_scope != "whole_paper" and context_block_ids:
            wanted = set(context_block_ids)
            scoped = [chunk for chunk in chunks if wanted & set(chunk.block_ids)]
            if scoped:
                search_chunks = scoped
        index = BM25Index(search_chunks)  # type: ignore[arg-type]
        hits = index.search(query, top_k=top_k, section_hints=plan.section_hints)
        timings["retrieve"] = round(_time.monotonic() - t0, 2)
        yield ReaderEvent(
            "retrieval_hits",
            {
                "count": len(hits),
                "hits": [
                    {
                        "chunk_id": hit.chunk.chunk_id,
                        "page": hit.chunk.page_start,
                        "section": hit.chunk.section_path,
                        "score": round(hit.lexical_score, 5),
                    }
                    for hit in hits
                ],
            },
        )
        if not retrieval_is_sufficient(hits, query):
            answer = GroundedAnswer(answer="当前解析文本中没有找到足够依据。", claims=[])
            yield ReaderEvent(
                "completed",
                {
                    "answer": answer.model_dump(mode="json"),
                    "reason": "INSUFFICIENT_RETRIEVAL_EVIDENCE",
                    "query": query,
                    "checked_sections": plan.section_hints,
                },
            )
            return

        ledger = build_evidence_ledger(f"q-{uuid.uuid4().hex[:12]}", hits)
        user = "\n\n".join(
            [
                f"QUESTION:\n{question}",
                f"RETRIEVAL_PLAN:\n{plan.model_dump_json()}",
                evidence_package(self._ledger_payload(ledger)),
                READER_ADVERSARIAL_EXAMPLES,
                "OUTPUT_SCHEMA:\n"
                + json.dumps(AnswerDraft.model_json_schema(), ensure_ascii=False),
                # V3.16 传输优化：实测模型输出 30% 是 pretty-print 空白，
                # compact 要求直接削减生成 token（draft 是输出生成主导）
                "OUTPUT_FORMAT:\n输出单一紧凑 JSON 对象。不要代码围栏、不要缩进、"
                "不要换行、不要多余空格（{\"claims\":[{\"claim_id\":\"cl-1\",\"text\":\"...\","
                "\"evidence_links\":[{\"evidence_id\":\"ev-1\",\"verbatim_quote\":\"...\","
                "\"char_start\":0,\"char_end\":10}]}],\"answer_summary_claim_ids\":[]}）",
            ]
        )
        yield ReaderEvent(
            "stage_started", {"stage": "draft", "message": "正在生成原子主张（暂不展示）"}
        )
        # V3.17 缓存命中 → 跳过 LLM 调用（键含命中集 → 缓存主张的
        # evidence_id 必在当次 ledger 中）；未命中正常调用并写缓存。
        cache_key = ""
        if cache_namespace:
            hit_ids = "|".join(sorted(hit.chunk.chunk_id for hit in hits))
            cache_key = f"{cache_namespace}|{question}|{hit_ids}"
        cached = _DRAFT_CACHE.get(cache_key) if cache_key else None
        if cached is not None:
            _DRAFT_CACHE.move_to_end(cache_key)
            draft = cached.model_copy(deep=True)
            logger.info("draft cache hit (size=%d): %s", len(_DRAFT_CACHE), question[:60])
        else:
            try:
                draft = self.model.invoke_json(
                    system=READER_SYSTEM,
                    user=user,
                    schema=AnswerDraft,
                    stage="scientific_reader",
                    thread_id=thread_id,
                )
            except Exception as exc:
                yield ReaderEvent("error", {"code": "MODEL_OUTPUT_INVALID", "message": str(exc)})
                return
            if cache_key:
                _DRAFT_CACHE[cache_key] = draft.model_copy(deep=True)
                _DRAFT_CACHE.move_to_end(cache_key)
                if len(_DRAFT_CACHE) > _DRAFT_CACHE_MAX:
                    _DRAFT_CACHE.popitem(last=False)

        timings["draft"] = round(_time.monotonic() - t0, 2)
        guard = EvidenceGuard(ledger)
        deterministic = guard.validate(draft)
        for rejected in deterministic.rejected:
            yield ReaderEvent(
                "claim_rejected",
                {
                    "claim_id": rejected.claim.claim_id,
                    "stage": "deterministic_guard",
                    "reasons": rejected.reasons,
                },
            )

        ledger_map = {item.evidence_id: item for item in ledger}
        supported: set[str] = set()
        yield ReaderEvent(
            "stage_started", {"stage": "attribute", "message": "正在逐条核验主张与证据关系"}
        )
        # 证据核验相互独立 → 并发（V3.13）：6 条主张从 ~16s 降到 ~5s。
        # 每条独立 LLM 调用；langchain ChatOpenAI 的同步 client 在线程间
        # 共享可安全使用（每次请求独立连接池分配），失败按原逻辑降级。
        from concurrent.futures import ThreadPoolExecutor

        accepted_claims = list(deterministic.accepted)
        outcomes: dict[str, object] = {}

        def verify_one(claim: object) -> tuple[str, object]:
            try:
                return claim.claim_id, self._verify_attribution(claim, ledger_map, thread_id)
            except Exception as exc:  # noqa: BLE001 - per-claim degradation
                return claim.claim_id, type(exc).__name__

        with ThreadPoolExecutor(max_workers=min(4, len(accepted_claims) or 1)) as pool:
            for claim_id, outcome in pool.map(verify_one, accepted_claims):
                outcomes[claim_id] = outcome

        for claim in accepted_claims:
            verdict = outcomes[claim.claim_id]
            if isinstance(verdict, str):
                yield ReaderEvent(
                    "claim_rejected",
                    {
                        "claim_id": claim.claim_id,
                        "stage": "attribution_verifier",
                        "reasons": [verdict],
                    },
                )
                continue
            if verdict.claim_id != claim.claim_id or verdict.verdict != SupportStatus.SUPPORTED:
                yield ReaderEvent(
                    "claim_rejected",
                    {
                        "claim_id": claim.claim_id,
                        "stage": "attribution_verifier",
                        "verdict": verdict.verdict,
                        "rationale": verdict.rationale,
                    },
                )
                continue
            supported.add(claim.claim_id)
            labels = [
                render_evidence_label(ledger_map[link.evidence_id]) for link in claim.evidence_links
            ]
            # 流式即带定位信息（fix 2026-08-04）：claim 一出现就能点 p.X 反向
            # 定位，不用等 completed 的完整 answer
            yield ReaderEvent(
                "claim_validated",
                {
                    "claim_id": claim.claim_id,
                    "text": claim.text,
                    "citations": labels,
                    "evidence_links": [
                        link.model_dump(mode="json") for link in claim.evidence_links
                    ],
                },
            )

        timings["attribute"] = round(_time.monotonic() - t0, 2)
        final = guard.finalize(draft, semantic_verified_ids=supported)
        # 答案组织（V3.9）：正文由模型基于已验证主张组织成连贯段落，
        # 证据作为逐条支撑单独展示；组织失败降级为 claim 拼接。
        # 主张 ≤ 2 时直接拼接（V3.15）：组织是锦上添花，简单问答不值得
        # 再等一次 LLM 往返（实测 3~5s），finalize 已有拼接降级。
        if len(final.claims) > 2:
            yield ReaderEvent(
                "stage_started", {"stage": "organize", "message": "正在组织最终答案"}
            )
            organized = self._organize_answer(question, final.claims, thread_id)
            if organized:
                final = final.model_copy(update={"answer": organized})
        timings["organize"] = round(_time.monotonic() - t0, 2)
        yield ReaderEvent(
            "completed",
            {
                "answer": final.model_dump(mode="json"),
                "evidence": [item.model_dump(mode="json") for item in ledger],
                "query_plan": plan.model_dump(mode="json"),
                "stage_timings": timings,
            },
        )

    def _organize_answer(self, question: str, claims: list[object], thread_id: str) -> str:
        """One coherent paragraph from verified claims; "" on failure."""
        payload = json.dumps(
            {"question": question, "verified_claims": [claim.text for claim in claims]},
            ensure_ascii=False,
        )
        try:
            organized = self.model.invoke_json(
                system=ORGANIZE_ANSWER_SYSTEM,
                user=payload,
                schema=OrganizedAnswer,
                stage="answer_organizer",
                thread_id=thread_id,
                temperature=0.2,
            )
            return organized.answer
        except Exception:  # organizing is an enhancement
            return ""
