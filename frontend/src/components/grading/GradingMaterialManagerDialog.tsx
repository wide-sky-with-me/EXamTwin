import {
  BookOpenCheck,
  Check,
  FileCheck2,
  LoaderCircle,
  Pencil,
  Search,
  Trash2,
  X,
} from "lucide-react";
import { Button, Tooltip } from "antd";
import { useMemo, useState } from "react";

import { paperMaterialMeta, schemeMaterialMeta } from "../../lib/grading-materials";
import type { GradingPaper, SourceDocument } from "../../types";
import { ErrorBanner } from "../Feedback";
import { AppConfirmDialog } from "../ui/AppConfirmDialog";
import { AppDialog } from "../ui/AppDialog";

const DATE_FORMATTER = new Intl.DateTimeFormat("zh-CN", {
  dateStyle: "medium",
  timeStyle: "short",
});

function formatDate(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : DATE_FORMATTER.format(date);
}

type ManagerItem = {
  id: string;
  name: string;
  sourceFilename: string;
  meta: string;
  detail?: string;
};

function MaterialManagerDialog({
  items,
  kind,
  onDelete,
  onOpenChange,
  onRename,
  onSelect,
  open,
  selectedId,
}: {
  items: ManagerItem[];
  kind: "paper" | "scheme";
  onDelete: (id: string) => Promise<void>;
  onOpenChange: (open: boolean) => void;
  onRename: (id: string, displayName: string) => Promise<void>;
  onSelect: (id: string) => void;
  open: boolean;
  selectedId: string;
}) {
  const [query, setQuery] = useState("");
  const [pendingDelete, setPendingDelete] = useState<ManagerItem | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draftName, setDraftName] = useState("");
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const isPaper = kind === "paper";
  const title = isPaper ? "管理作答记录" : "管理 Mark Scheme";
  const normalizedQuery = query.trim().toLocaleLowerCase();
  const visibleItems = useMemo(
    () => normalizedQuery
      ? items.filter((item) => (
        `${item.name} ${item.sourceFilename} ${item.meta}`.toLocaleLowerCase().includes(normalizedQuery)
      ))
      : items,
    [items, normalizedQuery],
  );

  async function confirmDelete() {
    if (!pendingDelete) return;
    setDeletingId(pendingDelete.id);
    setError(null);
    try {
      await onDelete(pendingDelete.id);
      setPendingDelete(null);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "删除失败，请稍后重试");
    } finally {
      setDeletingId(null);
    }
  }

  function beginRename(item: ManagerItem) {
    setEditingId(item.id);
    setDraftName(item.name);
    setError(null);
  }

  async function confirmRename(item: ManagerItem) {
    const normalized = draftName.trim();
    if (!normalized) {
      setError("显示名称不能为空");
      return;
    }
    if (normalized === item.name) {
      setEditingId(null);
      return;
    }
    setRenamingId(item.id);
    setError(null);
    try {
      await onRename(item.id, normalized);
      setEditingId(null);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "名称保存失败，请稍后重试");
    } finally {
      setRenamingId(null);
    }
  }

  function selectItem(id: string) {
    onSelect(id);
    onOpenChange(false);
  }

  return (
    <>
      <AppDialog
        contentClassName="modal-card grading-material-manager-modal"
        dismissible={deletingId === null}
        initialFocusSelector="[data-material-search]"
        onOpenChange={(nextOpen) => {
          if (!nextOpen) {
            setQuery("");
            setError(null);
            setEditingId(null);
          }
          onOpenChange(nextOpen);
        }}
        open={open}
        title={title}
      >
        <header className="modal-header">
          <div>
            <span>{isPaper ? "ANSWER RECORDS" : "MARK SCHEMES"}</span>
            <h2>{title}</h2>
          </div>
          <button
            aria-label="关闭"
            className="icon-button"
            disabled={deletingId !== null}
            onClick={() => onOpenChange(false)}
            type="button"
          >
            <X size={19} />
          </button>
        </header>

        <div className="grading-material-manager-toolbar">
          <label className="search-field">
            <Search aria-hidden="true" size={16} />
            <input
              data-material-search
              onChange={(event) => setQuery(event.target.value)}
              placeholder={isPaper ? "搜索文件名、Unit 或状态" : "搜索文件名、来源或状态"}
              type="search"
              value={query}
            />
          </label>
          <span>{visibleItems.length} 项</span>
        </div>

        <div className="grading-material-manager-body">
          <ErrorBanner message={error} />
          {visibleItems.length ? (
            <ul className="grading-material-manager-list">
              {visibleItems.map((item) => {
                const selected = item.id === selectedId;
                return (
                  <li aria-current={selected ? "true" : undefined} key={item.id}>
                    <span className="grading-material-manager-icon">
                      {isPaper ? <FileCheck2 size={18} /> : <BookOpenCheck size={18} />}
                    </span>
                    <span className="grading-material-manager-copy">
                      {editingId === item.id ? (
                        <input
                          aria-label={`修改 ${item.name} 的显示名称`}
                          autoFocus
                          className="grading-material-rename-input"
                          disabled={renamingId === item.id}
                          maxLength={200}
                          onChange={(event) => setDraftName(event.target.value)}
                          onKeyDown={(event) => {
                            if (event.key === "Enter") void confirmRename(item);
                            if (event.key === "Escape") setEditingId(null);
                          }}
                          value={draftName}
                        />
                      ) : (
                        <strong title={item.name}>{item.name}</strong>
                      )}
                      <small>{item.meta}</small>
                      {item.name !== item.sourceFilename && <small>原文件：{item.sourceFilename}</small>}
                      {item.detail && <small>{item.detail}</small>}
                    </span>
                    <span className="grading-material-manager-actions">
                      {editingId === item.id ? (
                        <>
                          <Tooltip mouseEnterDelay={0.25} title="取消修改">
                            <button
                              aria-label="取消修改名称"
                              className="icon-button"
                              disabled={renamingId === item.id}
                              onClick={() => setEditingId(null)}
                              type="button"
                            >
                              <X size={15} />
                            </button>
                          </Tooltip>
                          <Tooltip mouseEnterDelay={0.25} title="保存名称">
                            <button
                              aria-label="保存显示名称"
                              className="icon-button material-save-name"
                              disabled={renamingId === item.id || !draftName.trim()}
                              onClick={() => void confirmRename(item)}
                              type="button"
                            >
                              {renamingId === item.id
                                ? <LoaderCircle className="spin" size={15} />
                                : <Check size={15} />}
                            </button>
                          </Tooltip>
                        </>
                      ) : selected ? (
                        <span className="grading-material-current"><Check size={14} />当前使用</span>
                      ) : (
                        <button
                          className="secondary"
                          disabled={deletingId !== null}
                          onClick={() => selectItem(item.id)}
                          type="button"
                        >
                          设为当前
                        </button>
                      )}
                      {editingId !== item.id && (
                        <>
                          <Tooltip mouseEnterDelay={0.25} title="修改显示名称">
                            <button
                              aria-label={`修改 ${item.name} 的显示名称`}
                              className="icon-button"
                              disabled={deletingId !== null || renamingId !== null}
                              onClick={() => beginRename(item)}
                              type="button"
                            >
                              <Pencil size={15} />
                            </button>
                          </Tooltip>
                          <Tooltip mouseEnterDelay={0.25} title="删除">
                            <button
                              aria-label={`删除 ${item.name}`}
                              className="icon-button danger"
                              disabled={deletingId !== null || renamingId !== null}
                              onClick={() => setPendingDelete(item)}
                              type="button"
                            >
                              <Trash2 size={15} />
                            </button>
                          </Tooltip>
                        </>
                      )}
                    </span>
                  </li>
                );
              })}
            </ul>
          ) : (
            <div className="grading-material-manager-empty">
              {query ? "没有匹配的材料" : isPaper ? "暂无可评分作答记录" : "暂无可用 Mark Scheme"}
            </div>
          )}
        </div>

        <footer className="modal-actions grading-material-manager-footer">
          <Button
            disabled={deletingId !== null || renamingId !== null}
            icon={<Check size={15} />}
            onClick={() => onOpenChange(false)}
            type="primary"
          >
            完成
          </Button>
        </footer>
      </AppDialog>

      <AppConfirmDialog
        busy={deletingId !== null}
        confirmLabel={isPaper ? "删除作答记录" : "删除 Mark Scheme"}
        danger
        description={pendingDelete
          ? isPaper
            ? `将删除“${pendingDelete.name}”及其作答结果。此操作无法从页面恢复。`
            : `将从当前科目的可用材料中删除“${pendingDelete.name}”。已生成的历史评分记录仍按审计规则保留。`
          : ""}
        onConfirm={confirmDelete}
        onOpenChange={(nextOpen) => {
          if (!nextOpen) setPendingDelete(null);
        }}
        open={pendingDelete !== null}
        title={isPaper ? "确认删除作答记录" : "确认删除 Mark Scheme"}
      />
    </>
  );
}

export function AnswerRecordManagerDialog({
  onDelete,
  onOpenChange,
  onRename,
  onSelect,
  open,
  papers,
  selectedId,
}: {
  onDelete: (id: string) => Promise<void>;
  onOpenChange: (open: boolean) => void;
  onRename: (id: string, displayName: string) => Promise<void>;
  onSelect: (id: string) => void;
  open: boolean;
  papers: GradingPaper[];
  selectedId: string;
}) {
  return (
    <MaterialManagerDialog
      items={papers.map((item) => ({
        id: item.job_id,
        name: item.display_name || item.filename,
        sourceFilename: item.filename,
        meta: paperMaterialMeta(item),
        detail: `更新于 ${formatDate(item.updated_at)}`,
      }))}
      kind="paper"
      onDelete={onDelete}
      onOpenChange={onOpenChange}
      onRename={onRename}
      onSelect={onSelect}
      open={open}
      selectedId={selectedId}
    />
  );
}

export function MarkSchemeManagerDialog({
  documents,
  onDelete,
  onOpenChange,
  onRename,
  onSelect,
  open,
  selectedId,
}: {
  documents: SourceDocument[];
  onDelete: (id: string) => Promise<void>;
  onOpenChange: (open: boolean) => void;
  onRename: (id: string, displayName: string) => Promise<void>;
  onSelect: (id: string) => void;
  open: boolean;
  selectedId: string;
}) {
  return (
    <MaterialManagerDialog
      items={documents.map((item) => ({
        id: item.id,
        name: item.display_name || item.filename,
        sourceFilename: item.filename,
        meta: schemeMaterialMeta(item),
      }))}
      kind="scheme"
      onDelete={onDelete}
      onOpenChange={onOpenChange}
      onRename={onRename}
      onSelect={onSelect}
      open={open}
      selectedId={selectedId}
    />
  );
}
