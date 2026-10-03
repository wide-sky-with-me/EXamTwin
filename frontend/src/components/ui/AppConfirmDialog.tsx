import { Button, Modal } from "antd";
import { AlertTriangle, Check, ShieldAlert, Trash2, X } from "lucide-react";

import { ErrorBanner } from "../Feedback";

export function AppConfirmDialog({
  busy = false,
  confirmLabel,
  danger = false,
  description,
  error = null,
  onConfirm,
  onOpenChange,
  open,
  title,
}: {
  busy?: boolean;
  confirmLabel: string;
  danger?: boolean;
  description: string;
  error?: string | null;
  onConfirm: () => void | Promise<void>;
  onOpenChange: (open: boolean) => void;
  open: boolean;
  title: string;
}) {
  const destructive = danger && /删除/.test(confirmLabel);
  return (
    <Modal
      centered
      closable={!busy}
      destroyOnHidden
      footer={null}
      keyboard={!busy}
      mask={{ closable: !busy }}
      modalRender={(node) => <div aria-label={title} role="alertdialog">{node}</div>}
      onCancel={() => {
        if (!busy) onOpenChange(false);
      }}
      open={open}
      rootClassName={`app-confirm-modal${danger ? " is-danger" : " is-warning"}`}
      title={null}
      width={480}
    >
      <div className="app-confirm-dialog">
        <div className="app-confirm-heading">
          <span className={`app-confirm-icon ${danger ? "danger" : "warning"}`}>
            {destructive ? <Trash2 size={21} /> : danger ? <ShieldAlert size={21} /> : <AlertTriangle size={21} />}
          </span>
          <strong className="app-confirm-title">{title}</strong>
        </div>
        <p className="app-confirm-description">{description}</p>
        <ErrorBanner message={error} />
        <div className="app-confirm-actions">
          <Button aria-label="取消" disabled={busy} icon={<X size={16} />} onClick={() => onOpenChange(false)}>取消</Button>
          <Button
            danger={danger}
            icon={destructive ? <Trash2 size={16} /> : <Check size={16} />}
            loading={busy}
            onClick={() => void onConfirm()}
            type="primary"
          >
            {confirmLabel}
          </Button>
        </div>
      </div>
    </Modal>
  );
}
