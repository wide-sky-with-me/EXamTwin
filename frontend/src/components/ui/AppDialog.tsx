import { Dialog } from "@radix-ui/themes";
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
    <Dialog.Root
      onOpenChange={(nextOpen) => {
        if (!nextOpen && !dismissible) return;
        onOpenChange(nextOpen);
      }}
      open={open}
    >
      <Dialog.Content
        aria-describedby={undefined}
        className={contentClassName}
        maxWidth="1180px"
        onEscapeKeyDown={(event) => {
          if (!dismissible) event.preventDefault();
        }}
        onOpenAutoFocus={(event) => {
          if (!initialFocusSelector) return;
          const target = contentRef.current?.querySelector<HTMLElement>(initialFocusSelector);
          if (!target) return;
          event.preventDefault();
          target.focus();
        }}
        onPointerDownOutside={(event) => {
          if (!dismissible) event.preventDefault();
        }}
        ref={contentRef}
      >
        <Dialog.Title className="sr-only">{title}</Dialog.Title>
        {children}
      </Dialog.Content>
    </Dialog.Root>
  );
}
