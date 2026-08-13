import { Modal } from "antd";
import { type ReactNode, useRef } from "react";

export function AppDialog({
  children,
  contentClassName = "",
  dismissible = true,
  initialFocusSelector,
  onOpenChange,
  open,
  title,
}: {
  children: ReactNode;
  contentClassName?: string;
  dismissible?: boolean;
  initialFocusSelector?: string;
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
      mask={{ closable: dismissible }}
      keyboard={dismissible}
      onCancel={() => {
        if (dismissible) onOpenChange(false);
      }}
      open={open}
      title={null}
      width={1180}
    >
      <div ref={contentRef}>{children}</div>
    </Modal>
  );
}
