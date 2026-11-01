# Sprint 132: Browser-local field activity queue

The field activity capture page stores small metadata-only entries in IndexedDB so an already-open page can accept entries without a network connection. Each item retains its generated event UUID, workspace, profile, optional campaign, activity type, channel, and occurrence time. It stores no customer note or copied profile details.

When connectivity is available, the page sends queued items to the authenticated sync endpoint with the workspace header. The server decides authorization and duplicate handling. Successful receipts are marked synced; authorization, validation, missing-record, and conflict responses are shown as requiring attention. Network and server failures retain the same event UUID for retry. The list is scoped to the workspace selected in the form.

This sprint supports offline entry from an already-open page; the next step caches the data-free page shell for reopening after connectivity is lost. Validation covers the client queue in Node and page/security behavior through FastAPI tests.
