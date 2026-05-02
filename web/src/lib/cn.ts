import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'

// Compose Tailwind class names with conflict resolution.
// `clsx` handles conditional / array / object class inputs; `twMerge`
// resolves conflicts (e.g., `p-2 p-4` → `p-4`). Standard shadcn pattern.
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs))
}
