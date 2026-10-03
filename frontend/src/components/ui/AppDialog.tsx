import { Modal } from "antd";
import { type ReactNode, useRef } from "react";

export function AppDialog({
  children,
  contentClassName = "",
  dismissible = true,
  rootClassName,
  initialFocusSelector,
  onOpenChange,
  open,
  title,
}: {
  children: ReactNode;
  contentClassName?: string;
  dismissible?: boolean;
  initialFocusSelector?: string;
  rootClassName?: string;
  onOpenChange: (open: boolean) => void;
  open: boolean;
  title: string;
}) {
  const contentRef = useRef<HTMLDivElement>(null);

  return (
    <Modal
      afterOpenChange={(nextOpen) => {
        if (!nextOpen || !initialFocusSelector) return;
        contentRef.current?.querySelector<HTMLElement>(initialFocusSelector)?.focus();
      }}
      aria-label={title}
      className={contentClassName}
      closable={dismissible}
      footer={null}
      mask={{ closable: dismissible }}
      keyboard={dismissible}
      onCancel={() => {
        if (dismissible) onOpenChange(false);
      }}
      open={open}
      rootClassName={rootClassName}
      title={null}
      width={1180}
    >
      <div ref={contentRef}>{children}</div>
    </Modal>
  );
}

export function TaskWorkspaceDialog({
  children,
  className,
  onClose,
  title,
  width,
}: {
  children: ReactNode;
  className: string;
  onClose: () => void;
  title: string;
  width: number;
}) {
  return (
    <Modal
      footer={null}
      onCancel={onClose}
      open
      rootClassName={`app-viewport-dialog app-task-workspace ${className}`}
      title={title}
      width={width}
    >
      {children}
    </Modal>
  );
}
