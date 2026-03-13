import { cn } from "./cn";
import type { InputHTMLAttributes, TextareaHTMLAttributes, SelectHTMLAttributes, ReactNode } from "react";

export function Input({ className, ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      className={cn(
        "w-full px-3 py-2 bg-bg border border-border rounded-md text-text text-sm",
        "focus:outline-none focus:border-accent transition-colors",
        className
      )}
      {...props}
    />
  );
}

export function Textarea({ className, ...props }: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return (
    <textarea
      className={cn(
        "w-full px-3 py-3 bg-bg border border-border rounded-md text-text text-sm resize-y min-h-[120px]",
        "focus:outline-none focus:border-accent transition-colors",
        className
      )}
      {...props}
    />
  );
}

export function Select({ className, children, ...props }: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select
      className={cn(
        "w-full px-3 py-2 bg-bg border border-border rounded-md text-text text-sm appearance-none",
        "focus:outline-none focus:border-accent transition-colors",
        "bg-[url('data:image/svg+xml,%3Csvg%20xmlns%3D%22http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg%22%20width%3D%2212%22%20height%3D%2212%22%20viewBox%3D%220%200%2024%2024%22%20fill%3D%22none%22%20stroke%3D%22%238b949e%22%20stroke-width%3D%222%22%3E%3Cpath%20d%3D%22M6%209l6%206%206-6%22%2F%3E%3C%2Fsvg%3E')]",
        "bg-no-repeat bg-[right_12px_center] pr-8",
        className
      )}
      {...props}
    >
      {children}
    </select>
  );
}

export function Label({ children, className, ...props }: { children: ReactNode; className?: string; htmlFor?: string }) {
  return (
    <label className={cn("block text-sm font-medium text-text mb-1.5", className)} {...props}>
      {children}
    </label>
  );
}

export function FormField({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cn("mb-4", className)}>{children}</div>;
}
