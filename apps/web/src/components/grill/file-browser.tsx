"use client";

import { FileText, Folder, Search } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { apiFetch } from "@/lib/api";
import { cn } from "@/lib/utils";

interface TreeResponse {
  repo_root: string;
  files: string[];
}

interface FileResponse {
  path: string;
  total_lines: number;
  lines: string[];
}

/** 文件树节点（由扁平相对路径列表构建，目录懒展开）。 */
interface TreeNode {
  name: string;
  path: string;
  isDir: boolean;
  children: TreeNode[];
}

function buildTree(files: string[]): TreeNode[] {
  const root: TreeNode = { name: "", path: "", isDir: true, children: [] };
  for (const rel of files) {
    const isDir = rel.endsWith("/");
    const parts = rel.replace(/\/$/, "").split("/");
    let current = root;
    parts.forEach((part, index) => {
      const isLast = index === parts.length - 1;
      const path = parts.slice(0, index + 1).join("/");
      let child = current.children.find((candidate) => candidate.name === part);
      if (!child) {
        child = { name: part, path, isDir: isLast ? isDir : true, children: [] };
        current.children.push(child);
      }
      current = child;
    });
  }
  const sortNode = (node: TreeNode) => {
    node.children.sort((a, b) => (a.isDir === b.isDir ? a.name.localeCompare(b.name) : a.isDir ? -1 : 1));
    node.children.forEach(sortNode);
  };
  sortNode(root);
  return root.children;
}

function TreeItem({
  node,
  depth,
  openedFile,
  onOpenFile,
}: {
  node: TreeNode;
  depth: number;
  openedFile: string | null;
  onOpenFile: (path: string) => void;
}) {
  const [open, setOpen] = useState(depth < 1);
  if (node.isDir) {
    return (
      <div>
        <button
          className="flex w-full items-center gap-1 rounded px-1 py-0.5 text-left text-[11px] text-ink-dim hover:bg-surface"
          style={{ paddingLeft: depth * 10 + 2 }}
          onClick={() => setOpen((value) => !value)}
        >
          <Folder className="size-3 shrink-0 text-accent/70" />
          {node.name}
        </button>
        {open &&
          node.children.map((child) => (
            <TreeItem key={child.path} node={child} depth={depth + 1} openedFile={openedFile} onOpenFile={onOpenFile} />
          ))}
      </div>
    );
  }
  return (
    <button
      className={cn(
        "flex w-full items-center gap-1 rounded px-1 py-0.5 text-left font-mono text-[11px] hover:bg-surface",
        openedFile === node.path ? "bg-accent-soft text-accent" : "text-ink-faint",
      )}
      style={{ paddingLeft: depth * 10 + 2 }}
      onClick={() => onOpenFile(node.path)}
    >
      <FileText className="size-3 shrink-0" />
      <span className="truncate">{node.name}</span>
    </button>
  );
}

/**
 * 拷打侧栏文件浏览器：树 + 行号查看器。
 * 外部经 ref API 打开指定文件并高亮滚动到行（file:line 引用跳转的落点）。
 */
export function FileBrowser({ projectId }: { projectId: number }) {
  const [tree, setTree] = useState<TreeNode[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [file, setFile] = useState<FileResponse | null>(null);
  const [loadingFile, setLoadingFile] = useState(false);
  const [highlightLine, setHighlightLine] = useState<number | null>(null);
  const [filter, setFilter] = useState("");
  const viewerRef = useRef<HTMLDivElement>(null);
  const highlightRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    void apiFetch<TreeResponse>(`/api/grill/projects/${projectId}/tree`)
      .then((data) => setTree(buildTree(data.files)))
      .catch((caught) => setError(caught instanceof Error ? caught.message : String(caught)));
  }, [projectId]);

  const openFile = useCallback(
    async (path: string, line?: number) => {
      setLoadingFile(true);
      setError(null);
      try {
        const data = await apiFetch<FileResponse>(`/api/grill/projects/${projectId}/file?path=${encodeURIComponent(path)}`);
        setFile(data);
        setHighlightLine(line ?? null);
        requestAnimationFrame(() => {
          if (line !== undefined && highlightRef.current) {
            highlightRef.current.scrollIntoView({ block: "center" });
          } else {
            viewerRef.current?.scrollTo({ top: 0 });
          }
        });
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : String(caught));
      } finally {
        setLoadingFile(false);
      }
    },
    [projectId],
  );

  // file:line 引用跳转的命令式入口（父组件经 data 属性约定触发）
  useEffect(() => {
    const handler = (event: Event) => {
      const detail = (event as CustomEvent<{ path: string; line?: number }>).detail;
      if (detail?.path) void openFile(detail.path, detail.line);
    };
    window.addEventListener("wenqu:open-file", handler);
    return () => window.removeEventListener("wenqu:open-file", handler);
  }, [openFile]);

  const filteredTree = useMemo(() => {
    if (!tree || !filter.trim()) return tree;
    const needle = filter.trim().toLowerCase();
    const prune = (nodes: TreeNode[]): TreeNode[] =>
      nodes
        .map((node) => {
          if (node.isDir) {
            const children = prune(node.children);
            return children.length > 0 ? { ...node, children } : null;
          }
          return node.path.toLowerCase().includes(needle) ? node : null;
        })
        .filter((node): node is TreeNode => node !== null);
    return prune(tree);
  }, [tree, filter]);

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-2">
      <div className="flex items-center gap-1.5 rounded-md border border-line bg-surface-2 px-2">
        <Search className="size-3 shrink-0 text-ink-faint" />
        <input
          className="h-7 w-full bg-transparent text-[11px] text-ink outline-none placeholder:text-ink-faint"
          placeholder="过滤文件…"
          value={filter}
          onChange={(event) => setFilter(event.target.value)}
        />
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto rounded-md border border-line bg-surface/60 p-1.5">
        {tree === null && !error && <p className="px-1 text-[11px] text-ink-faint">加载文件树…</p>}
        {error && <p className="px-1 text-[11px] text-danger">{error}</p>}
        {filteredTree?.map((node) => (
          <TreeItem key={node.path} node={node} depth={0} openedFile={file?.path ?? null} onOpenFile={(path) => void openFile(path)} />
        ))}
      </div>
      <div ref={viewerRef} className="min-h-0 flex-1 overflow-auto rounded-md border border-line bg-[#0d0f13] p-0">
        {file === null ? (
          <p className="p-3 text-[11px] leading-relaxed text-ink-faint">
            点击左侧文件查看内容；拷打官回复中的 文件:行号 引用可直接点开并定位。
          </p>
        ) : (
          <div className="min-w-max py-1 font-mono text-[11px] leading-[1.5]">
            {file.lines.map((line, index) => {
              const lineNo = index + 1;
              const highlighted = highlightLine === lineNo;
              return (
                <div
                  key={lineNo}
                  ref={highlighted ? highlightRef : undefined}
                  className={cn("flex gap-2 px-2", highlighted && "bg-accent/20")}
                >
                  <span className="w-9 shrink-0 select-none text-right text-ink-faint/60">{lineNo}</span>
                  <span className={cn("whitespace-pre", highlighted ? "text-ink" : "text-ink-dim")}>{line}</span>
                </div>
              );
            })}
          </div>
        )}
        {loadingFile && <p className="p-2 text-[11px] text-ink-faint">读取中…</p>}
      </div>
    </div>
  );
}
