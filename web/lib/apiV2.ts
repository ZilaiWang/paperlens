/**
 * PaperLens vNext API client (改进方案2 Phase A / G / H / I).
 *
 * Workspace identity is anonymous-first. The server mints an opaque session
 * and stores it in an HttpOnly cookie; JavaScript never chooses or reads the
 * workspace credential.
 */

const API = process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8700";

let sessionPromise: Promise<WorkspaceInfo> | null = null;

export function ensureWorkspace(): Promise<WorkspaceInfo> {
  if (!sessionPromise) {
    sessionPromise = fetch(`${API}/api/v2/workspaces/me`, {
      credentials: "include",
    }).then(async (response) => {
      if (response.ok) return response.json() as Promise<WorkspaceInfo>;
      const created = await fetch(`${API}/api/v2/workspaces/anonymous`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });
      if (!created.ok) throw new Error(`无法创建工作空间 (${created.status})`);
      return created.json() as Promise<WorkspaceInfo>;
    }).catch((error) => {
      sessionPromise = null;
      throw error;
    });
  }
  return sessionPromise;
}

async function request<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  await ensureWorkspace();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...((init?.headers as Record<string, string>) ?? {}),
  };
  const response = await fetch(`${API}${path}`, {
    ...init,
    headers,
    credentials: "include",
  });
  if (!response.ok) {
    let detail = `${response.status}`;
    try {
      const body = await response.json();
      if (body?.detail) detail = String(body.detail);
    } catch {
      /* keep status text */
    }
    throw new Error(detail);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

// ---------------------------------------------------------------------------
// Workspace
// ---------------------------------------------------------------------------
export interface WorkspaceInfo {
  workspace_id: string;
  name: string;
  kind: string;
  created_at: string;
}

export const getWorkspace = () =>
  request<WorkspaceInfo>("/api/v2/workspaces/me");

// ---------------------------------------------------------------------------
// Projects
// ---------------------------------------------------------------------------
export interface Project {
  project_id: string;
  workspace_id: string;
  name: string;
  description: string;
  goal: string;
  paper_ids: string[];
  question_ids: string[];
  status: string;
  created_at: string;
  updated_at: string;
}

export interface ResearchQuestion {
  question_id: string;
  project_id: string;
  text: string;
  detail: string;
  status: string;
  answer: string;
  evidence: Record<string, unknown>[];
  created_at: string;
}

export interface Hypothesis {
  hypothesis_id: string;
  project_id: string;
  question_id: string;
  statement: string;
  rationale: string;
  status: string;
  created_at: string;
}

export const listProjects = () =>
  request<Project[]>("/api/v2/projects");

export const createProject = (payload: {
  name: string;
  description?: string;
  goal?: string;
}) => request<Project>("/api/v2/projects", { method: "POST", body: JSON.stringify(payload) });

export const getProject = (projectId: string) =>
  request<Project>(`/api/v2/projects/${projectId}`);

export const addProjectPaper = (projectId: string, paperId: string) =>
  request<Project>(`/api/v2/projects/${projectId}/papers`, {
    method: "POST",
    body: JSON.stringify({ paper_id: paperId }),
  });

export const listQuestions = (projectId: string) =>
  request<ResearchQuestion[]>(`/api/v2/projects/${projectId}/questions`);

export const createQuestion = (projectId: string, text: string, detail = "") =>
  request<ResearchQuestion>(`/api/v2/projects/${projectId}/questions`, {
    method: "POST",
    body: JSON.stringify({ text, detail }),
  });

export const listHypotheses = (projectId: string) =>
  request<Hypothesis[]>(`/api/v2/projects/${projectId}/hypotheses`);

export const createHypothesis = (projectId: string, statement: string, questionId = "", rationale = "") =>
  request<Hypothesis>(`/api/v2/projects/${projectId}/hypotheses`, {
    method: "POST",
    body: JSON.stringify({ question_id: questionId, statement, rationale }),
  });

// ---------------------------------------------------------------------------
// Research runs (agent)
// ---------------------------------------------------------------------------
export interface RunSummary {
  run_id: string;
  project_id: string;
  question: string;
  status: string;
  tasks: Array<{
    task_id: string;
    task_type: string;
    name: string;
    tool: string;
    description: string;
  }>;
  artifact: { artifact_id: string; kind: string; title: string; content: string } | null;
  findings: string[];
  created_at: string;
}

export const createRun = (projectId: string, question: string, paperVersionIds: string[] = []) =>
  request<RunSummary>(`/api/v2/projects/${projectId}/runs`, {
    method: "POST",
    body: JSON.stringify({ question, paper_version_ids: paperVersionIds }),
  });

export const executeRun = (projectId: string, runId: string) =>
  request<RunSummary & { ok_count: number; task_count: number }>(
    `/api/v2/projects/${projectId}/runs/${runId}/execute`,
    { method: "POST" },
  );

export const listRuns = (projectId: string) =>
  request<RunSummary[]>(`/api/v2/projects/${projectId}/runs`);

// ---------------------------------------------------------------------------
// Comparison sets v2
// ---------------------------------------------------------------------------
export interface ComparisonSet {
  comparison_id: string;
  workspace_id: string;
  name: string;
  description: string;
  question: string;
  paper_version_ids: string[];
  dimensions: string[];
  cells: unknown[];
  synthesis: { summary: string; consensus: string[]; contradictions: string[]; gaps: string[] };
  status: string;
  created_at: string;
}

export const listComparisonSets = () =>
  request<ComparisonSet[]>("/api/v2/comparison-sets");

export const createComparisonSet = (payload: {
  name: string;
  description?: string;
  question?: string;
  paper_version_ids?: string[];
}) =>
  request<ComparisonSet>("/api/v2/comparison-sets", {
    method: "POST",
    body: JSON.stringify(payload),
  });

// ---------------------------------------------------------------------------
// Termbase
// ---------------------------------------------------------------------------
export interface TermEntry {
  scope: string;
  source: string;
  target: string;
  domain: string;
  policy: string;
  locked: boolean;
  keep_english: boolean;
}

export const listTermbase = () =>
  request<TermEntry[]>("/api/v2/termbase");

export const upsertTerm = (entry: {
  source: string;
  target: string;
  scope: string;
  policy?: string;
  domain?: string;
  keep_english?: boolean;
  locked?: boolean;
}) =>
  request<TermEntry>("/api/v2/termbase", {
    method: "POST",
    body: JSON.stringify(entry),
  });

export const deleteTerm = (scope: string, source: string) =>
  request<{ deleted: string }>(
    `/api/v2/termbase/${encodeURIComponent(scope)}/${encodeURIComponent(source)}`,
    { method: "DELETE" },
  );

export interface TermPack {
  pack_id: string;
  name: string;
  domain: string;
  version: string;
  description: string;
  language_pair: string;
  license: string;
  recommended: boolean;
  term_count: number;
  installed: boolean;
}

export const listTermPacks = () => request<TermPack[]>("/api/v2/term-packs");

export const installTermPack = (packId: string) =>
  request<TermPack>(`/api/v2/term-packs/${encodeURIComponent(packId)}/install`, {
    method: "POST",
  });

export const uninstallTermPack = (packId: string) =>
  request<{ pack_id: string; installed: boolean }>(
    `/api/v2/term-packs/${encodeURIComponent(packId)}`,
    { method: "DELETE" },
  );
