/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_TOKEN_SERVER_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}

/** Web-client build identity, injected by vite.config.ts `define` at build
 * time (session-export header, issue #40). Null when unknowable. */
declare const __APP_VERSION__: string | null;
declare const __GIT_SHA__: string | null;
