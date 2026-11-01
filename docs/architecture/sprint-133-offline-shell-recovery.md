# Sprint 133: Reopen the activity capture page offline

A same-origin service worker caches only the data-free capture page and its client script. It serves the cached shell for that navigation when the network is unavailable, while the IndexedDB queue remains the only offline business-data store. API requests, workspace content, and CRM responses are never intercepted or cached.

The service worker is restricted to the two shell routes, uses a versioned cache, removes older versions on activation, and claims the client after activation. The capture page registers it only in a secure context. The first successful online visit installs the shell; subsequent visits can reopen it without network access.

Validation: Node service-worker behavior tests cover installation, activation cleanup, offline navigation fallback, and API pass-through; FastAPI tests verify the worker scope and response headers.
