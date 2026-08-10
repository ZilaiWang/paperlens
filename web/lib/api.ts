// PaperLens API client. Server origin is configurable so the web app can be
// served separately from the FastAPI backend in the cloud layout.

const API = process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8700";

export interface PaperRow {
  paper_id: string;
  title: string;
  source: string;
  versions: number;
  // V4.6-0：当前版本 id（比较等接口需要 version_id）
  version_id?: string;
}

export interface JobInfo {
  job_id: string;
  job_type: string;
  paper_id: string;
  paper_version_id: string;
  status: string;
  progress: number;
  stages: Record<
    string,
    {
      key: string;
      status: string;
      ratio: number;
      detail: string;
      started_at: string;
      finished_at: string;
      duration_seconds?: number;
    }
  >;
  error_code: string;
  error_message: string;
  result_uri: string;
  created_at: string;
}

export interface SectionIR {
  section_id: string;
  title: string;
  raw_title: string;
  canonical_name: string;
  level: number;
  start_page: number;
  end_page: number | null;
  confidence: number;
}

export interface BlockIR {
  block_id: string;
  page: number;
  block_type: string;
  bbox: number[];
  text: string;
  font_size: number | null;
  is_bold: boolean;
  section_id: string | null;
  paragraph_index: number;
  metadata: Record<string, unknown>;
}

export interface AssetIR {
  asset_id: string;
  asset_kind: string;
  page: number;
  bbox: number[];
  caption_original: string;
  caption_translation: string;
  source_kind: string;
  extraction_status: string;
  // arXiv HTML 论文的图直链（无需 PDF 裁剪）；空则客户端裁剪
  content_uri?: string;
  // 结构化表格（V3.12）：rows = cell 文本网格，csv = 可下载文本
  structured_data?: {
    rows: string[][];
    csv: string;
    html?: string;
  };
}

export interface ReferenceIR {
  reference_id: string;
  sequence_number: number;
  raw_text: string;
  parsed_title: string;
  authors: string[];
  year: string;
  venue: string;
  doi: string;
  arxiv_id: string;
  format_issues: string[];
  identity_status: string;
}

export interface EvidenceLocator {
  block_id: string;
  block_char_start: number;
  block_char_end: number;
  page: number;
  bboxes: number[][];
}

export interface EvidenceLinkIR {
  evidence_id: string;
  verbatim_quote: string;
  char_start: number;
  char_end: number;
  quote_sha256: string;
  locators: EvidenceLocator[];
}

export interface ClaimIR {
  claim_id: string;
  text: string;
  claim_type: string;
  evidence_links: EvidenceLinkIR[];
}

export interface PaperMeta {
  title: string;
  authors: string;
  abstract: string;
  arxiv_id?: string;
}

export interface ChatAnswer {
  answer: string;
  claims: ClaimIR[];
}

export type StreamChatEvent =
  | { event: "stage_started"; payload: { stage: string; message?: string } }
  | { event: "retrieval_hits"; payload: { count: number; hits: object[] } }
  | { event: "claim_validated"; payload: { claim_id: string; text: string; citations: string[] } }
  | { event: "claim_rejected"; payload: object }
  | { event: "completed"; payload: { message_id: string; answer: ChatAnswer } }
  | { event: "error"; payload: { code: string; message: string } };

async function jsonFetch<T>(url: string, init?: RequestInit, timeoutMs = 180000): Promise<T> {
  // Always target the FastAPI backend: relative /api/* paths would be
  // intercepted by Next.js itself and 404.
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(`${API}${url}`, {
      ...init,
      signal: controller.signal,
    });
    if (!response.ok) {
      let detail = response.statusText;
      try {
        const body = await response.json();
        detail = body.detail ?? detail;
      } catch {
        /* keep statusText */
      }
      throw new Error(`${response.status}: ${detail}`);
    }
    return (await response.json()) as T;
  } finally {
    clearTimeout(timer);
  }
}

export const api = {
  listPapers: () => jsonFetch<PaperRow[]>("/api/papers"),
  upload: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return jsonFetch<{ job_id: string; status: string; matched_arxiv?: string }>(
      "/api/papers/upload",
      {
        method: "POST",
        body: form,
      }
    );
  },
  importArxiv: (arxivInput: string) =>
    jsonFetch<{ job_id: string; status: string }>("/api/papers/import/arxiv", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ arxiv_input: arxivInput }),
    }),
  job: (jobId: string) => jsonFetch<JobInfo>(`/api/jobs/${jobId}`),
  outline: (paperId: string) =>
    jsonFetch<{ paper_id: string; version_id: string; sections: SectionIR[] }>(
      `/api/papers/${paperId}/outline`
    ),
  document: (paperId: string, page?: number) =>
    jsonFetch<{ paper_id: string; version_id: string; page_count: number; blocks: BlockIR[] }>(
      `/api/papers/${paperId}/document${page ? `?page=${page}` : ""}`
    ),
  pdfUrl: (paperId: string) => `${API}/api/papers/${paperId}/pdf`,
  assetDownloadUrl: (assetId: string) => `${API}/api/assets/${assetId}/download`,
  assets: (paperId: string) => jsonFetch<AssetIR[]>(`/api/papers/${paperId}/assets`),
  references: (paperId: string) => jsonFetch<ReferenceIR[]>(`/api/papers/${paperId}/references`),
  meta: (paperId: string) => jsonFetch<PaperMeta>(`/api/papers/${paperId}/meta`),
  sampleQuestions: (paperId: string) =>
    jsonFetch<{ questions: string[] }>(`/api/papers/${paperId}/sample-questions`),
  pageQuality: (paperId: string) =>
    jsonFetch<
      Array<{
        page: number;
        verdict: "GOOD" | "SUSPECT" | "LOW";
        fallback_reasons: string[];
        single_char_ratio: number;
        tiny_block_ratio: number;
        table_contamination: number;
      }>
    >(`/api/papers/${paperId}/page-quality`),
  createSession: (paperId: string) =>
    jsonFetch<{ session_id: string; paper_version_id: string }>(`/api/sessions?paper_id=${paperId}`, {
      method: "POST",
    }),
  // V4.0-3：进入论文恢复最近会话（刷新后对话完整）；无会话时 404 → 前端新建
  // V4.4 单篇旗舰功能
  methodGraph: (paperId: string) =>
    jsonFetch<Record<string, unknown>>(
      `/api/papers/${paperId}/analyses/method-graph`,
      { method: "POST" }
    ),
  experiments: (paperId: string) =>
    jsonFetch<Array<Record<string, unknown>>>(`/api/papers/${paperId}/experiments`),
  // V4.6-1 会话管理（§3.4/§十五-1）
  sessions: (paperId: string) =>
    jsonFetch<Array<{ session_id: string; title: string; created_at: string; updated_at: string }>>(
      `/api/sessions?paper_id=${paperId}`
    ),
  renameSession: (sessionId: string, title: string) =>
    jsonFetch<{ status: string }>(`/api/sessions/${sessionId}/rename`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title }),
    }),
  deleteSession: (sessionId: string) =>
    jsonFetch<{ status: string }>(`/api/sessions/${sessionId}`, { method: "DELETE" }),
  latestSession: (paperId: string) =>
    jsonFetch<{ session_id: string; paper_version_id: string }>(
      `/api/sessions/latest?paper_id=${paperId}`
    ),
  chat: (sessionId: string, question: string, contextBlockIds?: string[]) =>
    jsonFetch<{ message_id: string; answer: ChatAnswer; events: unknown[] }>(
      `/api/sessions/${sessionId}/messages`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question,
          context: contextBlockIds?.length ? "section" : "whole_paper",
          context_block_ids: contextBlockIds ?? [],
        }),
      }
    ),
  // SSE: claims stream in as they are verified
  streamChat: async (
    sessionId: string,
    question: string,
    onEvent: (event: StreamChatEvent) => void,
    signal?: AbortSignal,
    contextBlockIds?: string[]
  ): Promise<ChatAnswer> => {
    const response = await fetch(`${API}/api/sessions/${sessionId}/messages/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        question,
        context: contextBlockIds?.length ? "section" : "whole_paper",
        context_block_ids: contextBlockIds ?? [],
      }),
      signal,
    });
    if (!response.ok || !response.body) {
      throw new Error(`流式请求失败（${response.status}）`);
    }
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let answer: ChatAnswer = { answer: "", claims: [] };
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let boundary: number;
      while ((boundary = buffer.indexOf("\n\n")) !== -1) {
        const raw = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        const eventLine = raw.split("\n").find((line) => line.startsWith("event: "));
        const dataLine = raw.split("\n").find((line) => line.startsWith("data: "));
        if (!eventLine || !dataLine) continue;
        let payload: StreamChatEvent["payload"] = {} as StreamChatEvent["payload"];
        try {
          payload = JSON.parse(dataLine.slice(6));
        } catch {
          continue;
        }
        const name = eventLine.slice(7).trim();
        const event = { event: name, payload } as StreamChatEvent;
        onEvent(event);
        if (name === "completed" && "answer" in payload && payload.answer) {
          answer = payload.answer;
        }
      }
    }
    return answer;
  },
  messages: (sessionId: string) =>
    jsonFetch<Array<Record<string, unknown>>>(`/api/sessions/${sessionId}/messages`),
  quality: (paperId: string) =>
    jsonFetch<Record<string, unknown>>(`/api/papers/${paperId}/analyses/quality`, { method: "POST" }),
  callouts: (paperId: string) =>
    jsonFetch<Array<{ callout_id: string; block_id: string; char_start: number; char_end: number; raw: string; reference_id: string }>>(
      `/api/papers/${paperId}/callouts`
    ),
  importReference: (referenceId: string) =>
    jsonFetch<{ job_id?: string; status: string; message?: string; error?: string }>(
      `/api/references/${referenceId}/import`,
      { method: "POST" }
    ),
  resolveReference: (referenceId: string) =>
    jsonFetch<{
      reference_id: string;
      identity_status: string;
      identifier_resolution: string;
      record_match: string;
      doi: string;
      arxiv_id: string;
      provider_evidence: unknown[];
      errors: Record<string, string>;
    }>(`/api/references/${referenceId}/resolve`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    }),
  resolveAllReferences: (paperId: string) =>
    jsonFetch<{ total: number; state: string; message?: string }>(
      `/api/papers/${paperId}/references/resolve-all`,
      { method: "POST" }
    ),
  resolveAllStatus: (paperId: string) =>
    jsonFetch<{
      state: string;
      done: number;
      total: number;
      verified?: number;
      probable?: number;
      ambiguous?: number;
      unresolved?: number;
      error?: string;
    }>(`/api/papers/${paperId}/references/resolve-all/status`),
  translate: (paperId: string, pages: number[]) =>
    jsonFetch<{ translated: number; cached: number; units: number }>(
      `/api/papers/${paperId}/translations`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ pages }),
      }
    ),
  translations: (paperId: string, page: number) =>
    jsonFetch<Array<{ unit_id: string; source_block_ids: string[]; target_text: string; status: string }>>(
      `/api/papers/${paperId}/translations?page=${page}`
    ),
};
