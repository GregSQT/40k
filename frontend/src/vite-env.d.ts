/// <reference types="vite/client" />

// Extend ImportMeta interface to include glob
interface ImportMeta {
  glob: <T = any>(
    pattern: string,
    options?: {
      eager?: boolean;
      import?: string;
      query?: string;
      as?: string;
    }
  ) => Record<string, T>;
}
