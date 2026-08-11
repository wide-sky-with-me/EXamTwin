import { AlertDialog } from "@radix-ui/themes";
import { AlertTriangle, LoaderCircle } from "lucide-react";

export function AppConfirmDialog({
  busy = false,
  confirmLabel,
  danger = false,
  description,
  onConfirm,
  onOpenChange,
  open,
  title,
}: {
  busy?: boolean;
  confirmLabel: string;
  danger?: boolean;
  description: string;
  onConfirm: () => void | Promise<void>;
  onOpenChange: (open: boolean) => void;
  open: boolean;
  title: string;
}) {
  return (
    <AlertDialog.Root
      onOpenChange={(nextOpen) => {
        if (!busy) onOpenChange(nextOpen);
      }}
      open={open}
    >
      <AlertDialog.Content className="app-confirm-dialog" maxWidth="440px">
        <div className={`app-confirm-icon ${danger ? "danger" : "warning"}`}>
          <AlertTriangle aria-hidden="true" size={20} />
        </div>
        <div>
          <AlertDialog.Title>{title}</AlertDialog.Title>
          <AlertDialog.Description>{description}</AlertDialog.Description>
        </div>
        <div className="app-confirm-actions">
          <button
            className="secondary"
            disabled={busy}
            onClick={() => onOpenChange(false)}
            type="button"
          >
            取消
          </button>
          <button
            aria-busy={busy || undefined}
            className={danger ? "danger-button" : "primary"}
            disabled={busy}
            onClick={() => void onConfirm()}
            type="button"
          >
            {busy && <LoaderCircle aria-hidden="true" className="spin" size={16} />}
            {confirmLabel}
          </button>
        </div>
      </AlertDialog.Content>
    </AlertDialog.Root>
  );
}
