"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, type ClaimIR, type EvidenceLocator, type BlockIR, type SectionIR } from "@/lib/api";

interface Message {
  role: "user" | "assistant";
  content: string;
  claims?: ClaimIR[];
  streaming?: boolean;
  // V3.20：新问题发出时历史回答的主张自动折叠，可点开查看
  claimsCollapsed?: boolean;
  // 论文质量评估消息（2026-08-05）：渲染为对话内的评分卡片
  kind?: "quality";
  qualityData?: Record<string, unknown>;
}

// 后端 stage_started 事件 → 用户可见的阶段文案（reader.py run_events）。
// 从消息发出起每个阶段都有文案，draft/organize 这种十几秒的 LLM 调用
// 也不会让界面看起来卡死。
const STAGE_LABELS: Record<string, string> = {
  plan: "正在理解问题并规划检索路径…",
  retrieve: "正在检索段落证据…",
  draft: "正在生成候选主张…",
  attribute: "正在逐条核验主张与证据…",
  organize: "正在组织最终答案…",
};

// V4.6-5（检查 3）：气泡大字的阶段文案由 STAGE_LABELS 提供；小字行显示
// 不同的实时内容（草稿撰写中 / 核验进度计数），避免两处重复
const SUB_LABELS: Record<string, string> = {
  plan: "正在理解问题并规划检索路径…",
  retrieve: "正在检索段落证据…",
  draft: "正在撰写原子主张…",
  attribute: "正在逐条核验…",
  organize: "正在组织答案…",
};

export function AgentPanel({
  paperId,
  onClose,
  blocks,
  sections,
  pendingPrompt,
  onPromptConsumed,
  onLocateEvidence,
  width,
  contextBlockIds,
  exampleQuestion,
}: {
  paperId: string;
  onClose: () => void;
  blocks: BlockIR[];
  sections: SectionIR[];
  pendingPrompt?: string;
  onPromptConsumed?: () => void;
  onLocateEvidence?: (locator: EvidenceLocator) => void;
  width?: number;
  // V4.3-1：上下文检索——当前章节的 block ids（Workbench 滚动跟踪）
  contextBlockIds?: string[];
  // 2026-08-07（教师优化 1）：解析时按摘要生成的示例问题（placeholder）
  exampleQuestion?: string;
}) {
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [busy, setBusy] = useState(false);
  // 论文质量评估（质量评估子 Agent）：方法论合理性/数据支撑等 7 维度打分
  const [qualityBusy, setQualityBusy] = useState(false);
  // 上下文开关（2026-08-05）：默认整篇检索；开启后提问才限定当前章节
  const [contextFollow, setContextFollow] = useState(false);
  const sessionRef = useRef<string | null>(null);
  // 保存 createSession 的 promise：用户在会话建好前就发送时，
  // runQuestion 会先等它，而不是静默丢弃消息（fix 2026-08-04）
  const sessionPromiseRef = useRef<Promise<string> | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const [status, setStatusState] = useState("");
  const statusRef = useRef("");
  // V4.6-5：小字行实时内容（核验计数/命中数）
  const [subLabel, setSubLabel] = useState("");
  const [verifiedCount, setVerifiedCount] = useState(0);
  const [hitsCount, setHitsCount] = useState<number | null>(null);
  // 阶段文案同时写入 state 和 ref：state 驱动 UI，ref 供事件回调读当前值
  const setStatus = (text: string) => {
    statusRef.current = text;
    setStatusState(text);
  };

  // V4.0-3：进入论文恢复最近会话（刷新后对话
  // 完整、多轮不丢），无会话才新建；恢复时加载历史消息
  useEffect(() => {
    sessionPromiseRef.current = api
      .latestSession(paperId)
      .then((session) => session.session_id)
      .catch(() => api.createSession(paperId).then((session) => session.session_id))
      .then((sid) => {
        sessionRef.current = sid;
        void api
          .messages(sid)
          .then((rows) => {
            const restored = (rows as Array<Record<string, unknown>>).map((row) => ({
              role: row.role === "user" ? "user" : "assistant",
              content: String(row.content ?? ""),
              claims: Array.isArray(row.evidence)
                ? (row.evidence as Array<Record<string, unknown>>)
                    .map((item) => {
                      // 存储结构为 {event, payload:{claim_id,text,citations}}；
                      // 解包 payload（修复 undefined 显示）
                      const claim = (item.payload as Record<string, unknown>) ?? item;
                      return {
                        claim_id: String(claim.claim_id ?? ""),
                        text: String(claim.text ?? ""),
                        claim_type: "AUTHOR_CLAIM",
                        evidence_links: Array.isArray(claim.evidence_links)
                          ? (claim.evidence_links as ClaimIR["evidence_links"])
                          : [],
                      };
                    })
                    .filter((claim) => claim.text)
                : undefined,
              streaming: false,
              // 2026-08-07：恢复历史会话时主张默认折叠（进入即收起，
              // 点"展开"查看），避免一屏证据铺满
              claimsCollapsed: true,
            })) as Message[];
            setMessages((list) => (list.length === 0 ? restored : list));
          })
          .catch(() => undefined);
        return sid;
      });
  }, [paperId]);

  // V4.6-1 会话管理（§3.4）：列表/切换/新建/重命名/删除
  const [sessions, setSessions] = useState<Array<{ session_id: string; title: string }>>([]);
  const [sessionMenuOpen, setSessionMenuOpen] = useState(false);

  const loadSessions = useCallback(() => {
    void api
      .sessions(paperId)
      .then((rows) => setSessions(rows as Array<{ session_id: string; title: string }>))
      .catch(() => undefined);
  }, [paperId]);

  const sessionTitle = sessions.find(
    (session) => session.session_id === sessionRef.current
  )?.title;

  const switchSession = useCallback(
    async (sid: string) => {
      sessionRef.current = sid;
      setSessionMenuOpen(false);
      setMessages([]);
      try {
        const rows = await api.messages(sid);
        const restored = (rows as Array<Record<string, unknown>>).map((row) => ({
          role: row.role === "user" ? "user" : "assistant",
          content: String(row.content ?? ""),
          claims: Array.isArray(row.evidence)
            ? (row.evidence as Array<Record<string, unknown>>)
                .map((item) => {
                  const claim = (item.payload as Record<string, unknown>) ?? item;
                  return {
                    claim_id: String(claim.claim_id ?? ""),
                    text: String(claim.text ?? ""),
                    claim_type: "AUTHOR_CLAIM",
                    evidence_links: Array.isArray(claim.evidence_links)
                      ? (claim.evidence_links as ClaimIR["evidence_links"])
                      : [],
                  };
                })
                .filter((claim) => claim.text)
            : undefined,
          streaming: false,
          claimsCollapsed: true,
        })) as Message[];
        setMessages(restored);
      } catch {
        /* keep empty */
      }
      void loadSessions();
    },
    [loadSessions]
  );

  const createNewSession = useCallback(async () => {
    const session = await api.createSession(paperId);
    sessionRef.current = session.session_id;
    setSessionMenuOpen(false);
    setMessages([]);
    void loadSessions();
  }, [paperId, loadSessions]);

  const renameSession = useCallback(
    async (sid: string) => {
      const title = window.prompt("会话标题", sessions.find((s) => s.session_id === sid)?.title ?? "");
      if (title === null) return;
      await api.renameSession(sid, title.trim() || "未命名");
      void loadSessions();
    },
    [sessions, loadSessions]
  );

  const deleteSession = useCallback(
    async (sid: string) => {
      if (!window.confirm("删除该会话？对话记录将一并清除。")) return;
      await api.deleteSession(sid);
      if (sessionRef.current === sid) {
        sessionRef.current = null;
        setMessages([]);
        const session = await api.createSession(paperId);
        sessionRef.current = session.session_id;
      }
      void loadSessions();
    },
    [paperId, loadSessions]
  );

  // Consume prompts handed over from the reader (e.g. "解释这张图").
  useEffect(() => {
    if (pendingPrompt) {
      void runInsight(pendingPrompt);
      onPromptConsumed?.();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pendingPrompt]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // SSE streaming: claims appear as they are verified ;
  // the buffered POST is the fallback when streaming fails.
  const runQuestion = useCallback(
    async (question: string) => {
      // 会话还没建好就发送时先等它，避免点击后毫无反应
      const sid =
        sessionRef.current ??
        (sessionPromiseRef.current ? await sessionPromiseRef.current : null);
      if (!sid) return;
      setBusy(true);
      setStatus(STAGE_LABELS.plan);
      // 占位气泡立即出现（同步 setState），文字随 stage_started 事件实时变化，
      // 配合同步加入的弹跳圆点——从发出消息到完成全程有可见的"思考中"
      setMessages((list) => [
        ...list,
        { role: "assistant", content: STAGE_LABELS.plan, claims: [], streaming: true },
      ]);
      const controller = new AbortController();
      const patchLast = (patch: Partial<Message> | ((last: Message) => Partial<Message>)) => {
        setMessages((list) => {
          const copy = [...list];
          const last = copy[copy.length - 1];
          if (last && last.role === "assistant" && last.streaming) {
            copy[copy.length - 1] =
              typeof patch === "function" ? { ...last, ...patch(last) } : { ...last, ...patch };
          }
          return copy;
        });
      };
      try {
        await api.streamChat(
          sid,
          question,
          (event) => {
            if (event.event === "stage_started") {
              const stage = String((event.payload as { stage?: unknown }).stage ?? "");
              const label = STAGE_LABELS[stage];
              if (label) {
                // 阶段推进 → 气泡文字更新，配合 pl-fade 重放，持续可见的推进感
                setStatus(label);
                patchLast({ content: label });
              }
              if (stage === "attribute") setVerifiedCount(0);
              setSubLabel(SUB_LABELS[stage] ?? label);
            } else if (event.event === "retrieval_hits") {
              const count = (event.payload as { count?: unknown }).count;
              const hits = Number(count ?? 0);
              setHitsCount(hits);
              setStatus(`已锁定 ${hits} 段候选证据`);
              patchLast({ content: `已锁定 ${hits} 段候选证据` });
              setSubLabel(`已锁定 ${hits} 段候选证据`);
            } else if (event.event === "claim_validated") {
              // 核验进度计数（小字实时更新）
              setVerifiedCount((count) => {
                setSubLabel(`已核验 ${count + 1} 条主张`);
                return count + 1;
              });
              patchLast((last) => ({
                claims: [
                  ...(last.claims ?? []),
                  {
                    claim_id: event.payload.claim_id,
                    text: event.payload.text,
                    claim_type: "AUTHOR_CLAIM",
                    // 流式即带定位信息（V3.11）：服务端在 claim_validated
                    // 事件里附带 evidence_links.locators
                    evidence_links:
                      "evidence_links" in event.payload
                        ? (event.payload as { evidence_links: ClaimIR["evidence_links"] })
                            .evidence_links
                        : [],
                  },
                ],
              }));
            } else if (event.event === "claim_rejected") {
              setVerifiedCount((count) => {
                setSubLabel(`已核验 ${count + 1} 条主张`);
                return count + 1;
              });
            } else if (event.event === "completed") {
              patchLast({
                content: event.payload.answer.answer || "当前证据不足，无法给出可靠回答。",
                // 关键：用完整 answer.claims 替换（含 evidence_links.locators），
                // 流式期间的 claim 只有文本没有定位信息（fix 2026-08-04）
                claims: event.payload.answer.claims,
                streaming: false,
              });
              setStatus("");
              setSubLabel("");
            } else if (event.event === "error") {
              patchLast({
                content: `出错：${event.payload.message}`,
                streaming: false,
              });
              setStatus("");
              setSubLabel("");
            }
          },
          controller.signal,
          contextFollow ? contextBlockIds : undefined
        );
      } catch (err) {
        // fallback: drop the streaming placeholder, use the buffered endpoint
        setMessages((list) => [
          ...list.filter((message) => !(message.role === "assistant" && message.streaming)),
          {
            role: "assistant",
            content: statusRef.current || STAGE_LABELS.plan,
            claims: [],
            streaming: true,
          },
        ]);
        try {
          const result = await api.chat(sid, question, contextFollow ? contextBlockIds : undefined);
          setMessages((list) => [
            ...list.filter((message) => !(message.role === "assistant" && message.streaming)),
            { role: "assistant", content: result.answer.answer, claims: result.answer.claims },
          ]);
          setStatus("");
        } catch (err2) {
          setMessages((list) => [
            ...list.filter((message) => !(message.role === "assistant" && message.streaming)),
            {
              role: "assistant",
              content: `出错：${err2 instanceof Error ? err2.message : String(err2)}`,
            },
          ]);
          setStatus("");
        }
      } finally {
        setBusy(false);
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    []
  );

  // V3.20：新问题发出 → 历史回答的主张自动折叠（可点开恢复）
  const collapseHistoryClaims = useCallback((list: Message[]) => {
    return list.map((message) =>
      message.role === "assistant" && message.claims && message.claims.length > 0
        ? { ...message, claimsCollapsed: true }
        : message
    );
  }, []);

  const toggleClaims = useCallback((index: number) => {
    setMessages((list) =>
      list.map((message, i) =>
        i === index ? { ...message, claimsCollapsed: !message.claimsCollapsed } : message
      )
    );
  }, []);

  const send = useCallback(async () => {
    const question = input.trim();
    if (!question || busy) return;
    setInput("");
    setMessages((list) => [
      ...collapseHistoryClaims(list),
      { role: "user", content: question },
    ]);
    await runQuestion(question);
  }, [input, busy, runQuestion, collapseHistoryClaims]);

  const runInsight = useCallback(
    async (prompt: string) => {
      if (busy) return;
      setMessages((list) => [
        ...collapseHistoryClaims(list),
        { role: "user", content: prompt },
      ]);
      await runQuestion(prompt);
    },
    [busy, runQuestion, collapseHistoryClaims]
  );

  // 论文质量评估（质量评估子 Agent）：以对话消息形式展示——
  // 追加"用户请求 + 助手占位"两条消息，评估完成后把评分写入助手消息
  const runQuality = useCallback(async () => {
    if (qualityBusy) return;
    setQualityBusy(true);
    setMessages((list) => [
      ...list,
      { role: "user", content: "请对这篇论文做一次质量评估（方法论合理性、数据支撑等维度打分）。" },
      { role: "assistant", content: "正在从原文检索证据并逐维度评分…", streaming: true, kind: "quality" },
    ]);
    try {
      const result = await api.quality(paperId);
      setMessages((list) =>
        list.map((message) =>
          message.kind === "quality"
            ? { ...message, streaming: false, content: "", qualityData: result }
            : message
        )
      );
    } catch (err) {
      setMessages((list) =>
        list.map((message) =>
          message.kind === "quality"
            ? { ...message, streaming: false, content: `评估失败：${String(err)}` }
            : message
        )
      );
    } finally {
      setQualityBusy(false);
    }
  }, [paperId, qualityBusy]);

  return (
    <aside
      style={{ width: width ?? 380 }}
      className="shrink-0 border-l border-[#e6e7ea] bg-white flex flex-col min-h-0"
    >
      <div className="flex items-center justify-between px-4 py-3 border-b border-[#e6e7ea]">
        <span className="text-sm font-medium">论文 Agent</span>
        <div className="flex items-center gap-1">
          {/* V4.6-1 会话菜单（§3.4）：恢复/切换/新建/重命名/删除 */}
          <div className="relative">
            <button
              onClick={() => {
                void loadSessions();
                setSessionMenuOpen((open) => !open);
              }}
              className="text-xs text-[#9aa0a6] hover:text-[#2f4b7c]"
              title="会话管理"
            >
              {sessionTitle || "新会话"} ▾
            </button>
            {sessionMenuOpen && (
              <div className="absolute right-0 top-7 z-20 w-56 rounded-xl border border-[#e6e7ea] bg-white shadow-lg p-1.5">
                <button
                  onClick={() => void createNewSession()}
                  className="w-full rounded-lg px-2.5 py-1.5 text-left text-xs text-[#2f4b7c] hover:bg-[#f0f4f8]"
                >
                  ＋ 新会话
                </button>
                <div className="my-1 border-t border-[#e6e7ea]" />
                {sessions.map((session) => (
                  <div
                    key={session.session_id}
                    className="group flex items-center gap-1 rounded-lg px-2.5 py-1.5 hover:bg-[#f0f4f8]"
                  >
                    <button
                      onClick={() => void switchSession(session.session_id)}
                      className={`flex-1 truncate text-left text-xs ${
                        sessionRef.current === session.session_id
                          ? "font-medium text-[#2f4b7c]"
                          : "text-[#3d4451]"
                      }`}
                      title={session.title || "未命名会话"}
                    >
                      {session.title || `会话 ${session.session_id.slice(4, 10)}`}
                    </button>
                    <button
                      onClick={() => void renameSession(session.session_id)}
                      className="hidden text-[10px] text-[#9aa0a6] hover:text-[#2f4b7c] group-hover:inline"
                      title="重命名"
                    >
                      改
                    </button>
                    <button
                      onClick={() => void deleteSession(session.session_id)}
                      className="hidden text-[10px] text-[#9aa0a6] hover:text-red-600 group-hover:inline"
                      title="删除"
                    >
                      删
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
          <button onClick={onClose} className="text-[#9aa0a6] hover:text-[#202124] text-sm">
            ✕
          </button>
        </div>
      </div>

      {
        <>
          <div className="flex-1 overflow-y-auto px-4 py-4 space-y-4">
            <p className="text-xs text-[#9aa0a6]">
              上下文：整篇论文 · {blocks.length} 个段落块 · 回答中的每条事实都绑定证据
            </p>
            {messages.map((message, index) => (
              <div key={index} className={message.role === "user" ? "text-right" : "text-left"}>
                <div
                  className={`inline-block max-w-full text-left text-sm rounded-xl px-3.5 py-2.5 pl-fade ${
                    message.role === "user"
                      ? "bg-[#2f4b7c] text-white"
                      : "bg-[#f0f2f5] text-[#202124]"
                  }`}
                >
                  {message.kind === "quality" && message.qualityData ? (
                    <div className="min-w-[280px] max-w-[420px]">
                      <QualityAssessmentCard data={message.qualityData} />
                    </div>
                  ) : (
                    <div className="whitespace-pre-wrap leading-relaxed">{message.content}</div>
                  )}
                  {message.streaming && (
                    // 弹跳圆点常驻动画 + 实时阶段文案；key=content 让每次
                    // 阶段切换重放 pl-fade，用户始终能看到处理在推进
                    <div
                      key={message.content}
                      className="mt-1.5 flex items-center gap-1.5 text-[11px] text-[#6b7280] pl-fade"
                    >
                      <span className="pl-typing" aria-hidden>
                        <span />
                        <span />
                        <span />
                      </span>
                      {subLabel || status}
                    </div>
                  )}
                  {message.claims && message.claims.length > 0 &&
                    message.claimsCollapsed && (
                      // V3.20 折叠态：一行摘要 + 展开入口
                      <button
                        onClick={() => toggleClaims(index)}
                        className="mt-1.5 text-[11px] text-[#9aa0a6] hover:text-[#2f4b7c] hover:underline"
                      >
                        {message.claims.length} 条证据主张 · 展开
                      </button>
                    )}
                  {message.claims && message.claims.length > 0 && !message.claimsCollapsed && (
                    <div className="mt-2 space-y-1">
                      {message.claims.map((claim) => {
                        // V3.19：整句主张作为跳转链接（软黄高亮），p.X 按钮移除；
                        // 定位用第一条证据的 locator（V3.11 起 claim_validated 即带）
                        const target = claim.evidence_links.flatMap(
                          (link) => link.locators
                        )[0];
                        return (
                          <div
                            key={claim.claim_id}
                            className="pl-claim-enter text-xs text-[#6b7280] border-t border-[#e6e7ea] pt-1.5 flex items-baseline gap-1.5"
                          >
                            {/* V3.20：flex baseline 保证对号与主张首行同行，
                                长句换行时对号保持在首行 */}
                            <span className="text-emerald-600 shrink-0">✓</span>
                            <button
                              onClick={() => target && onLocateEvidence?.(target)}
                              disabled={!target}
                              title={
                                target ? `定位到第 ${target.page} 页证据` : "暂无定位"
                              }
                              // V3.19b：对话框内保持朴素样式（黄高亮在跳转
                              // 后的原文证据上），悬停下划线提示可点
                              className="cursor-pointer text-left transition-colors hover:text-[#2f4b7c] hover:underline disabled:cursor-default"
                            >
                              {claim.text}
                            </button>
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>
              </div>
            ))}
            <div ref={bottomRef} />
          </div>
          {/* 预设气泡（2026-08-05）：核心思路 / 结果解读 / 局限与疑点 /
              论文评估 平级一行，单层排列 */}
          <div className="border-t border-[#e6e7ea] px-3 pt-2.5 pb-1">
            <div className="flex flex-wrap gap-1.5">
              {(
                [
                  ["核心思路", "这篇论文的方法核心思路是什么？关键的创新点落在哪个环节？", "insight"],
                  ["结果解读", "这篇论文的主要结果如何？在哪些任务或指标上领先、领先多少？", "insight"],
                  ["局限与疑点", "这篇论文有哪些局限？除了作者承认的，实验设计上还有没有值得质疑的地方？", "insight"],
                  ["论文评估", "", "quality"],
                ] as [string, string, string][]
              ).map(([label, prompt, kind]) => (
                <button
                  key={label}
                  onClick={() =>
                    kind === "quality" ? void runQuality() : void runInsight(prompt)
                  }
                  disabled={kind === "quality" ? qualityBusy : busy}
                  className="rounded-full border border-[#dbe3ee] px-3 py-1.5 text-xs text-[#2f4b7c] hover:bg-[#f0f4f8] disabled:opacity-50 transition-colors"
                >
                  {kind === "quality" && qualityBusy ? "评估中…" : label}
                </button>
              ))}
            </div>
          </div>
          <div className="border-t border-[#e6e7ea] p-3">
            {/* V4.3-1 检索范围分段开关（2026-08-05）：整篇 / 仅当前滚动章节，
                选中态白底凸起；开启后提问才带 contextBlockIds */}
            <div className="mb-2 flex rounded-lg bg-[#f0f2f5] p-0.5 text-[11px]">
              <button
                onClick={() => setContextFollow(false)}
                className={`flex-1 rounded-md py-1 transition-colors ${
                  !contextFollow
                    ? "bg-white shadow-sm font-medium text-[#2f4b7c]"
                    : "text-[#9aa0a6] hover:text-[#6b7280]"
                }`}
              >
                整篇检索
              </button>
              <button
                onClick={() => setContextFollow(true)}
                className={`flex-1 rounded-md py-1 transition-colors ${
                  contextFollow
                    ? "bg-white shadow-sm font-medium text-[#2f4b7c]"
                    : "text-[#9aa0a6] hover:text-[#6b7280]"
                }`}
              >
                仅当前章节
              </button>
            </div>
            {contextFollow && !(contextBlockIds && contextBlockIds.length > 0) && (
              <p className="-mt-1 mb-2 text-[10px] text-[#9aa0a6]">
                滚动正文后按当前章节检索
              </p>
            )}
            <div className="flex gap-2">
              <input
                value={input}
                onChange={(event) => setInput(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") void send();
                }}
                placeholder={
                  exampleQuestion
                    ? `例如：${exampleQuestion}`
                    : "输入你的问题…"
                }
                className="flex-1 px-3.5 py-2.5 rounded-lg border border-[#e6e7ea] text-sm focus:outline-none focus:border-[#2f4b7c]"
              />
              <button
                onClick={() => void send()}
                disabled={busy || !input.trim()}
                className="px-4 py-2.5 rounded-lg bg-[#2f4b7c] text-white text-sm hover:bg-[#263d64] disabled:opacity-40"
              >
                发送
              </button>
            </div>
          </div>
        </>
      }
    </aside>
  );
}

// 论文质量评估卡片（2026-08-05）：作为对话内消息渲染，中文文案。
// data 来自 POST /api/papers/{id}/analyses/quality 的 QualityAssessment。
function QualityAssessmentCard({ data }: { data: Record<string, unknown> }) {
  const total = Math.round(Number(data.weighted_score ?? 0));
  const coverage = Math.round(Number(data.evidence_coverage ?? 0) * 100);
  const dimensions = (data.dimensions as Array<Record<string, unknown>> | undefined) ?? [];
  return (
    <div className="w-full rounded-lg bg-white p-3">
      {/* 总分行 */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1.5">
          <span className="text-[11px] font-medium text-[#3d4451]">📊 论文质量评估</span>
          <span
            className={`rounded-full px-1.5 py-0.5 text-[10px] ${
              total >= 80
                ? "bg-emerald-50 text-emerald-600"
                : total >= 60
                  ? "bg-amber-50 text-amber-600"
                  : "bg-red-50 text-red-600"
            }`}
          >
            {total >= 80 ? "优秀" : total >= 60 ? "良好" : "待改进"}
          </span>
        </div>
        <div className="flex items-baseline gap-1">
          <span className="text-xl font-semibold text-[#2f4b7c]">{total}</span>
          <span className="text-[10px] text-[#9aa0a6]">/ 100</span>
        </div>
      </div>
      <div className="mt-0.5 text-[10px] text-[#9aa0a6]">
        证据覆盖 <span className="text-[#2f4b7c]">{coverage}%</span> · 从原文检索证据后评分
      </div>
      {/* 维度列表 */}
      <div className="mt-2 space-y-2">
        {dimensions.map((dimension) => {
          const score = Math.max(0, Math.min(4, Number(dimension.score ?? 0)));
          return (
            <div key={String(dimension.name)}>
              <div className="flex items-center justify-between text-[11px]">
                <span className="text-[#3d4451]">{String(dimension.name)}</span>
                <span className={`font-medium ${score >= 3 ? "text-[#2f4b7c]" : "text-[#9aa0a6]"}`}>
                  {score} / 4
                </span>
              </div>
              <div className="mt-1 flex gap-1">
                {[1, 2, 3, 4].map((dot) => (
                  <span
                    key={dot}
                    className={`h-1 flex-1 rounded-full ${
                      dot <= score ? "bg-[#2f4b7c]" : "bg-[#eef0f3]"
                    }`}
                  />
                ))}
              </div>
              {dimension.rationale ? (
                <p className="mt-1 text-[10px] leading-relaxed text-[#6b7280]">
                  {String(dimension.rationale)}
                </p>
              ) : null}
            </div>
          );
        })}
      </div>
      {data.summary ? (
        <p className="mt-2.5 border-t border-[#eceef1] pt-2 text-[10px] leading-relaxed text-[#9aa0a6]">
          {String(data.summary)}
        </p>
      ) : null}
    </div>
  );
}
