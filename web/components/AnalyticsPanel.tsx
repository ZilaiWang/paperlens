"use client";

// 2026-08-07 重构：分析面板精简为「方法流程」+「实验记录」两个实用功能。
// - 方法流程：服务端抽取的方法步骤节点，按依赖关系排成横向流程图；
// - 实验记录：从论文表格提取的结构化结果（方法/数据集/指标/条件/值）。
// 数据均来自服务端结构化抽取，点击即用，无需额外等待。
import { useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";

type Tab = "method" | "experiments";

interface MethodGraph {
  nodes: Array<{
    node_id: string;
    name: string;
    node_type: string;
    description: string;
    evidence_ids: string[];
    training_difference: string;
    inference_difference: string;
  }>;
  edges: Array<{ source: string; target: string }>;
}

const NODE_TYPE_LABELS: Record<string, string> = {
  INPUT: "输入",
  PROCESS: "处理",
  MODULE: "模块",
  OUTPUT: "输出",
};

export function AnalyticsPanel({ paperId }: { paperId: string }) {
  const [tab, setTab] = useState<Tab>("method");
  const [graph, setGraph] = useState<MethodGraph | null>(null);
  const [experiments, setExperiments] = useState<Array<Record<string, unknown>> | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    setError("");
    setBusy(true);
    if (tab === "method") {
      api
        .methodGraph(paperId)
        .then((data) => setGraph(data as unknown as MethodGraph))
        .catch((err) => setError(String(err)))
        .finally(() => setBusy(false));
    } else {
      api
        .experiments(paperId)
        .then(setExperiments)
        .catch((err) => setError(String(err)))
        .finally(() => setBusy(false));
    }
  }, [paperId, tab]);

  // 把方法步骤按依赖链排成顺序：从入度为 0 的节点出发沿边遍历
  const flowOrder = useMemo(() => {
    if (!graph || graph.edges.length === 0) return graph?.nodes ?? [];
    const byId = new Map(graph.nodes.map((node) => [node.node_id, node]));
    const outDegree = new Map<string, number>();
    for (const node of graph.nodes) outDegree.set(node.node_id, 0);
    for (const edge of graph.edges) {
      outDegree.set(edge.source, (outDegree.get(edge.source) ?? 0) + 1);
    }
    // 起点 = 没有入边的节点（入度即作为 target 的次数）
    const inDegree = new Map<string, number>();
    for (const node of graph.nodes) inDegree.set(node.node_id, 0);
    for (const edge of graph.edges) {
      inDegree.set(edge.target, (inDegree.get(edge.target) ?? 0) + 1);
    }
    const starts = graph.nodes
      .filter((node) => (inDegree.get(node.node_id) ?? 0) === 0)
      .sort((a, b) => (outDegree.get(a.node_id) ?? 0) - (outDegree.get(b.node_id) ?? 0));
    const ordered: typeof graph.nodes = [];
    const visited = new Set<string>();
    const walk = (nodeId: string) => {
      if (visited.has(nodeId)) return;
      visited.add(nodeId);
      const node = byId.get(nodeId);
      if (node) ordered.push(node);
      for (const edge of graph.edges) {
        if (edge.source === nodeId) walk(edge.target);
      }
    };
    for (const start of starts) walk(start.node_id);
    // 兜底：环或孤立节点
    for (const node of graph.nodes) {
      if (!visited.has(node.node_id)) ordered.push(node);
    }
    return ordered;
  }, [graph]);

  const tabs: Array<[Tab, string]> = [
    ["method", "方法流程"],
    ["experiments", "实验记录"],
  ];

  return (
    <div className="p-3 space-y-3">
      <div className="flex flex-wrap gap-1.5">
        {tabs.map(([key, label]) => (
          <button
            key={key}
            onClick={() => setTab(key)}
            className={`rounded-full px-3 py-1 text-xs transition-colors ${
              tab === key
                ? "bg-[#2f4b7c] text-white"
                : "border border-[#dbe3ee] text-[#2f4b7c] hover:bg-[#f0f4f8]"
            }`}
          >
            {label}
          </button>
        ))}
      </div>
      {busy && <p className="text-xs text-[#9aa0a6]">分析中…</p>}
      {error && <p className="text-xs text-red-600">{error}</p>}

      {tab === "method" && (
        <div className="space-y-2">
          {graph && flowOrder.length > 0 ? (
            <>
              {/* 横向流程图 */}
              <div className="flex flex-wrap items-center gap-1.5">
                {flowOrder.map((node, index) => (
                  <div key={node.node_id} className="flex items-center gap-1.5">
                    <div className="rounded-lg border border-[#dbe3ee] bg-[#f7f9fc] px-2.5 py-1.5">
                      <div className="flex items-center gap-1.5">
                        <span className="text-[11px] font-medium text-[#202124]">
                          {node.name}
                        </span>
                        <span className="rounded bg-[#e8eef6] px-1 py-0.5 text-[9px] text-[#2f4b7c]">
                          {NODE_TYPE_LABELS[node.node_type] ?? node.node_type}
                        </span>
                      </div>
                      {node.description && (
                        <p className="mt-0.5 max-w-[220px] text-[10px] leading-relaxed text-[#6b7280]">
                          {node.description}
                        </p>
                      )}
                    </div>
                    {index < flowOrder.length - 1 && (
                      <span className="text-[#9aa0a6]">→</span>
                    )}
                  </div>
                ))}
              </div>
              {/* 训练/推理差异补充说明 */}
              {flowOrder.some((node) => node.training_difference || node.inference_difference) && (
                <div className="mt-2 space-y-1.5 rounded-lg border border-[#e6e7ea] p-2">
                  <p className="text-[10px] font-medium text-[#9aa0a6]">阶段差异说明</p>
                  {flowOrder.map(
                    (node) =>
                      (node.training_difference || node.inference_difference) && (
                        <div key={node.node_id} className="text-[11px] text-[#6b7280]">
                          <span className="font-medium text-[#3d4451]">{node.name}</span>
                          {node.training_difference && (
                            <p className="mt-0.5">训练：{node.training_difference}</p>
                          )}
                          {node.inference_difference && (
                            <p className="mt-0.5">推理：{node.inference_difference}</p>
                          )}
                        </div>
                      )
                  )}
                </div>
              )}
            </>
          ) : (
            !busy &&
            !error && (
              <p className="text-xs text-[#9aa0a6]">未抽取到方法流程（可能是综述或理论类论文）。</p>
            )
          )}
        </div>
      )}

      {tab === "experiments" && experiments && (
        <div className="overflow-x-auto rounded-lg border border-[#e6e7ea]">
          <table className="w-full text-[11px] border-collapse">
            <thead>
              <tr className="bg-[#f7f8fa] text-left text-[#3d4451]">
                <th className="px-2 py-1.5">方法</th>
                <th className="px-2 py-1.5">数据集</th>
                <th className="px-2 py-1.5">指标</th>
                <th className="px-2 py-1.5">条件</th>
                <th className="px-2 py-1.5">值</th>
              </tr>
            </thead>
            <tbody>
              {experiments.slice(0, 100).map((record, index) => (
                <tr key={index} className="border-t border-[#eceef1]">
                  <td className="px-2 py-1 text-[#202124]">{String(record.method)}</td>
                  <td className="px-2 py-1 text-[#6b7280]">{String(record.dataset)}</td>
                  <td className="px-2 py-1 text-[#6b7280]">{String(record.metric)}</td>
                  <td className="px-2 py-1 text-[#9aa0a6]">{String(record.condition)}</td>
                  <td className="px-2 py-1 font-medium text-[#2f4b7c]">{String(record.value)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {experiments.length === 0 && (
            <p className="p-3 text-xs text-[#9aa0a6]">未从表格中提取到结构化结果记录。</p>
          )}
          {experiments.length > 100 && (
            <p className="p-2 text-[10px] text-[#9aa0a6]">仅显示前 100 条（共 {experiments.length} 条）</p>
          )}
        </div>
      )}
    </div>
  );
}
