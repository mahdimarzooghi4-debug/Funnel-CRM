# Sprint 30: campaign planning

A marketing campaign is a tenant-owned plan scoped to an organization and linked to an active saved audience segment in that same scope. Plans record an objective, channel, and optional time window.

Campaign permissions are separate from segment permissions. Listing and mutations honor the caller's organization hierarchy and tenant boundary. Changes are audited.

The current campaign lifecycle is `draft → archived`. This slice deliberately has no activation, recipient materialization, dispatch, or sending endpoint. Campaign planning does not imply customer contact or consent.
