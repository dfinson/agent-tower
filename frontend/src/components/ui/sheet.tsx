import * as DialogPrimitive from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import { cn } from "../../lib/utils";

interface SheetProps {
  open: boolean;
  onClose: () => void;
  title?: React.ReactNode;
  children: React.ReactNode;
  side?: "left" | "right";
}

export function Sheet({ open, onClose, title, children, side = "right" }: SheetProps) {
  return (
    <DialogPrimitive.Root open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-black/60 data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0" />
        <DialogPrimitive.Content
          className={cn(
            "fixed inset-y-0 z-50 w-[min(16rem,85vw)] sm:w-[min(18rem,85vw)] bg-card shadow-xl flex flex-col",
            "data-[state=open]:animate-in data-[state=closed]:animate-out",
            "duration-200",
            side === "left"
              ? "left-0 border-r border-border data-[state=closed]:slide-out-to-left data-[state=open]:slide-in-from-left"
              : "right-0 border-l border-border data-[state=closed]:slide-out-to-right data-[state=open]:slide-in-from-right",
          )}
        >
          <div className="flex items-center justify-between px-4 py-3 border-b border-border shrink-0">
            <DialogPrimitive.Title className="font-semibold text-sm text-foreground">
              {title}
            </DialogPrimitive.Title>
            <DialogPrimitive.Close className="rounded-md p-1 text-muted-foreground hover:text-foreground hover:bg-accent transition-colors focus:outline-none focus:ring-1 focus:ring-ring">
              <X size={16} />
              <span className="sr-only">Close</span>
            </DialogPrimitive.Close>
          </div>
          <div className="flex-1 overflow-y-auto p-4">{children}</div>
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}
