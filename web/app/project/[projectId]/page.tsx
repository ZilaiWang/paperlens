"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { api, type PaperRow } from "@/lib/api";
import {
  addProjectPaper, createHypothesis, createQuestion, createRun, executeRun,
  getProject, listHypotheses, listQuestions, listRuns,
  type Hypothesis, type Project, type ResearchQuestion, type RunSummary,
} from "@/lib/apiV2";

const taskLabel: Record<string, string> = {
  RETRIEVE: "检索证据", PROFILE: "构建画像", COMPARE: "对齐比较",
  SYNTHESIZE: "综合发现", PRODUCE: "生成报告", VERIFY: "校验证据",
};

export default function ProjectPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const [project, setProject] = useState<Project | null>(null);
  const [questions, setQuestions] = useState<ResearchQuestion[]>([]);
  const [hypotheses, setHypotheses] = useState<Hypothesis[]>([]);
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [papers, setPapers] = useState<PaperRow[]>([]);
  const [questionText, setQuestionText] = useState("");
  const [hypothesisText, setHypothesisText] = useState("");
  const [runQuestion, setRunQuestion] = useState("");
  const [selectedPaper, setSelectedPaper] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const refresh = useCallback(() => {
    if (!projectId) return;
    getProject(projectId).then(setProject).catch(() => setProject(null));
    listQuestions(projectId).then(setQuestions).catch(() => setQuestions([]));
    listHypotheses(projectId).then(setHypotheses).catch(() => setHypotheses([]));
    listRuns(projectId).then(setRuns).catch(() => setRuns([]));
    api.listPapers().then(setPapers).catch(() => setPapers([]));
  }, [projectId]);
  useEffect(() => refresh(), [refresh]);

  const act = async (action: () => Promise<unknown>, reset: () => void) => {
    if (busy) return;
    setBusy(true); setError(""); setNotice("");
    try { await action(); reset(); refresh(); }
    catch (err) { setError(err instanceof Error ? err.message : "操作失败"); }
    finally { setBusy(false); }
  };

  const startRun = async () => {
    if (!runQuestion.trim() || busy) return;
    setBusy(true); setError(""); setNotice("正在创建任务图…");
    try {
      const run = await createRun(projectId, runQuestion.trim(), project?.paper_ids ?? []);
      setNotice(`正在执行 ${run.tasks.length} 个任务…`);
      const result = await executeRun(projectId, run.run_id);
      setNotice(result.status === "COMPLETED" ? `运行完成 · ${result.ok_count}/${result.task_count} 个任务成功` : `运行未完成 · ${result.ok_count}/${result.task_count} 个任务成功`);
      setRunQuestion(""); refresh();
    } catch (err) { setError(err instanceof Error ? err.message : "运行失败"); }
    finally { setBusy(false); }
  };

  if (!project) return <main className="grid min-h-screen place-items-center text-sm text-[var(--pl-faint)]">项目不存在，或当前工作区无权访问。</main>;
  const availablePapers = papers.filter((paper) => paper.version_id && !project.paper_ids.includes(paper.version_id));

  return (
    <main className="min-h-screen px-5 py-8 sm:px-8 lg:px-12 lg:py-10">
      <div className="mx-auto max-w-[1120px]">
        <Link href="/library" className="font-mono text-[10px] uppercase tracking-wider text-[var(--pl-faint)] hover:text-[var(--pl-clay)]">← Projects</Link>
        <header className="mt-6 border-b border-[var(--pl-line)] pb-7">
          <div className="flex flex-wrap items-start justify-between gap-5">
            <div><h1 className="text-[30px] font-medium tracking-[-0.03em]">{project.name}</h1><p className="mt-2 max-w-2xl text-sm leading-6 text-[var(--pl-muted)]">{project.goal || "尚未定义研究目标"}</p></div>
            <span className="rounded-md border border-[var(--pl-line)] bg-white/60 px-2 py-1 font-mono text-[9px] uppercase text-[var(--pl-muted)]">{project.status}</span>
          </div>
          <div className="mt-5 flex flex-wrap gap-5 font-mono text-[9px] uppercase text-[var(--pl-faint)]"><span>{project.paper_ids.length} papers</span><span>{questions.length} questions</span><span>{hypotheses.length} hypotheses</span><span>{runs.length} runs</span></div>
        </header>

        {(error || notice) && <div className={`mt-4 rounded-lg border px-4 py-2.5 text-xs ${error ? "border-[#e4c9c2] bg-[#fbf3f1] text-[#a23f32]" : "border-[var(--pl-line)] bg-white/65 text-[var(--pl-muted)]"}`}>{error || notice}</div>}

        <div className="mt-8 grid gap-10 lg:grid-cols-[minmax(0,1fr)_350px]">
          <div className="space-y-10">
            <section>
              <div className="mb-3 flex items-center justify-between"><h2 className="font-mono text-[10px] uppercase tracking-[0.14em] text-[var(--pl-muted)]">Research questions</h2><span className="font-mono text-[9px] text-[var(--pl-faint)]">{questions.length}</span></div>
              <div className="flex gap-2"><input value={questionText} onChange={(event) => setQuestionText(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") void act(() => createQuestion(projectId, questionText.trim()), () => setQuestionText("")); }} placeholder="这个项目最终要回答什么？" className="h-10 min-w-0 flex-1 rounded-lg border border-[var(--pl-line)] bg-white px-3 text-sm outline-none focus:border-[var(--pl-clay)]" /><button disabled={busy || !questionText.trim()} onClick={() => void act(() => createQuestion(projectId, questionText.trim()), () => setQuestionText(""))} className="rounded-lg bg-[var(--pl-ink)] px-4 text-xs text-white disabled:opacity-35">添加</button></div>
              <div className="mt-3 space-y-2">{questions.length === 0 ? <Empty text="先写下一个可回答的研究问题。" /> : questions.map((item, index) => <article key={item.question_id} className="grid grid-cols-[24px_minmax(0,1fr)_auto] gap-3 rounded-xl border border-[var(--pl-line)] bg-white/70 p-4"><span className="font-mono text-[9px] text-[var(--pl-faint)]">Q{index + 1}</span><div><p className="text-[13px] font-medium leading-5">{item.text}</p>{item.answer && <p className="mt-2 text-xs leading-5 text-[var(--pl-muted)]">{item.answer}</p>}</div><span className="font-mono text-[8px] uppercase text-[var(--pl-faint)]">{item.status}</span></article>)}</div>
            </section>

            <section>
              <div className="mb-3 flex items-center justify-between"><h2 className="font-mono text-[10px] uppercase tracking-[0.14em] text-[var(--pl-muted)]">Hypotheses</h2><span className="font-mono text-[9px] text-[var(--pl-faint)]">{hypotheses.length}</span></div>
              <div className="flex gap-2"><input value={hypothesisText} onChange={(event) => setHypothesisText(event.target.value)} placeholder="写下一条可证伪的假设…" className="h-10 min-w-0 flex-1 rounded-lg border border-[var(--pl-line)] bg-white px-3 text-sm outline-none focus:border-[var(--pl-clay)]" /><button disabled={busy || !hypothesisText.trim()} onClick={() => void act(() => createHypothesis(projectId, hypothesisText.trim()), () => setHypothesisText(""))} className="rounded-lg border border-[var(--pl-line-strong)] bg-white px-4 text-xs disabled:opacity-35">添加</button></div>
              <div className="mt-3 space-y-2">{hypotheses.length === 0 ? <Empty text="假设会把调研变成可以验证的过程。" /> : hypotheses.map((item, index) => <article key={item.hypothesis_id} className="grid grid-cols-[24px_minmax(0,1fr)_auto] gap-3 rounded-xl border border-[var(--pl-line)] bg-white/70 p-4"><span className="font-mono text-[9px] text-[var(--pl-faint)]">H{index + 1}</span><p className="text-[13px] leading-5">{item.statement}</p><span className="font-mono text-[8px] uppercase text-[var(--pl-faint)]">{item.status}</span></article>)}</div>
            </section>

            <section>
              <div className="mb-3 flex items-center justify-between"><h2 className="font-mono text-[10px] uppercase tracking-[0.14em] text-[var(--pl-muted)]">Run history</h2><span className="font-mono text-[9px] text-[var(--pl-faint)]">{runs.length}</span></div>
              {runs.length === 0 ? <Empty text="运行结果、发现和报告会保存在这里。" /> : <div className="space-y-2">{runs.map((run) => <details key={run.run_id} className="group rounded-xl border border-[var(--pl-line)] bg-white/70 open:bg-white"><summary className="flex cursor-pointer list-none items-center gap-3 px-4 py-3.5"><span className={`size-2 rounded-full ${run.status === "COMPLETED" ? "bg-[#6d9a73]" : run.status === "FAILED" ? "bg-[#b95842]" : "bg-[#c79b4c]"}`} /><span className="min-w-0 flex-1 truncate text-[13px] font-medium">{run.question}</span><span className="font-mono text-[8px] uppercase text-[var(--pl-faint)]">{run.status}</span><span className="text-[var(--pl-faint)] transition group-open:rotate-90">›</span></summary><div className="border-t border-[var(--pl-line)] px-4 py-4"><div className="flex flex-wrap gap-1.5">{run.tasks.map((task, index) => <span key={task.task_id} className="rounded bg-[#f0ede7] px-2 py-1 font-mono text-[8px] uppercase text-[var(--pl-muted)]">{index + 1}. {taskLabel[task.task_type] ?? task.task_type}</span>)}</div>{run.findings.length > 0 && <ul className="mt-4 space-y-1 text-xs leading-5 text-[var(--pl-muted)]">{run.findings.map((finding, index) => <li key={index}>— {finding}</li>)}</ul>}{run.artifact?.content && <pre className="mt-4 max-h-80 overflow-auto whitespace-pre-wrap rounded-lg border border-[var(--pl-line)] bg-[#f7f5f0] p-4 font-sans text-xs leading-5 text-[var(--pl-ink)]">{run.artifact.content}</pre>}</div></details>)}</div>}
            </section>
          </div>

          <aside className="space-y-4 lg:sticky lg:top-8 lg:self-start">
            <div className="rounded-2xl border border-[var(--pl-line)] bg-[#292722] p-5 text-white shadow-[0_12px_30px_rgba(32,29,24,.12)]">
              <div className="flex items-center justify-between"><h2 className="text-sm font-medium">启动研究运行</h2><span className="font-mono text-[9px] text-white/45">AGENT DAG</span></div>
              <textarea value={runQuestion} onChange={(event) => setRunQuestion(event.target.value)} placeholder="让 Agent 回答一个具体问题…" rows={5} className="mt-4 block w-full resize-none rounded-lg border border-white/10 bg-white/[.06] px-3 py-2.5 text-sm leading-5 text-white outline-none placeholder:text-white/35 focus:border-white/30" />
              <div className="mt-3 flex flex-wrap gap-1 font-mono text-[8px] uppercase text-white/40"><span>retrieve</span><span>→</span><span>profile</span><span>→</span><span>compare</span><span>→</span><span>report</span></div>
              <button disabled={busy || !runQuestion.trim()} onClick={() => void startRun()} className="mt-4 h-10 w-full rounded-lg bg-[#d06d4d] text-xs font-medium text-white transition hover:bg-[#dc7959] disabled:opacity-35">{busy ? "执行中…" : "运行任务图 →"}</button>
            </div>

            <div className="rounded-xl border border-[var(--pl-line)] bg-white/65 p-4">
              <div className="mb-3 flex items-center justify-between"><h2 className="text-xs font-medium">项目论文</h2><span className="font-mono text-[9px] text-[var(--pl-faint)]">{project.paper_ids.length}</span></div>
              {project.paper_ids.length > 0 && <div className="mb-3 space-y-1">{project.paper_ids.map((id) => <div key={id} className="truncate rounded bg-[#f0ede7] px-2 py-1.5 font-mono text-[9px] text-[var(--pl-muted)]">{papers.find((paper) => paper.version_id === id)?.title || id}</div>)}</div>}
              {availablePapers.length > 0 ? <div className="flex gap-2"><select value={selectedPaper} onChange={(event) => setSelectedPaper(event.target.value)} className="h-9 min-w-0 flex-1 rounded-lg border border-[var(--pl-line)] bg-white px-2 text-xs outline-none"><option value="">选择论文…</option>{availablePapers.map((paper) => <option key={paper.version_id} value={paper.version_id}>{paper.title}</option>)}</select><button disabled={busy || !selectedPaper} onClick={() => void act(() => addProjectPaper(projectId, selectedPaper), () => setSelectedPaper(""))} className="rounded-lg border border-[var(--pl-line-strong)] bg-white px-3 text-xs disabled:opacity-35">加入</button></div> : <p className="text-[11px] leading-5 text-[var(--pl-faint)]">资料库中没有可加入的新论文。<Link href="/" className="ml-1 text-[var(--pl-clay)]">导入论文</Link></p>}
            </div>
          </aside>
        </div>
      </div>
    </main>
  );
}

function Empty({ text }: { text: string }) {
  return <div className="rounded-xl border border-dashed border-[var(--pl-line-strong)] px-4 py-7 text-center text-xs text-[var(--pl-faint)]">{text}</div>;
}
