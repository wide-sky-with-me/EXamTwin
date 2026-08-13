import { Alert, Modal } from "antd";

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
    <Modal
      cancelButtonProps={{ disabled: busy }}
      cancelText={<span aria-label="取消">取消</span>}
      closable={!busy}
      confirmLoading={busy}
      keyboard={!busy}
      mask={{ closable: !busy }}
      modalRender={(node) => <div aria-label={title} role="alertdialog">{node}</div>}
      okButtonProps={{ danger }}
      okText={<span>{confirmLabel}</span>}
      onCancel={() => {
        if (!busy) onOpenChange(false);
      }}
      onOk={() => void onConfirm()}
      open={open}
      title={title}
      width={440}
    >
      <Alert
        description={description}
        showIcon
        title={danger ? "此操作不可撤销" : "请确认操作范围"}
        type={danger ? "error" : "warning"}
      />
    </Modal>
  );
}
