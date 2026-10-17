# Saved CRM audience segments

- Sprint: 20
- Related: CRM-DOM-03 and CRM-DOM-06
- API: `/api/v1/crm/segments`

Marketing users can save live audience definitions by profile kind and lifecycle stage, scope each definition to an organization unit, and preview matching profiles. Membership is evaluated against current profile data at preview time; the system does not keep a stale membership copy.

Segment visibility and management use separate `crm.segment:view` and `crm.segment:manage` permissions. Preview also applies the caller's profile-view scope in SQL and excludes archived and merged profiles. Preview results show only profile ID, kind, name, and lifecycle stage, with a bounded page and total count.

Changes and previews create actor-attributed audit events containing counts and criterion field names, not profile data or criterion values. A segment is an audience definition only: it does not enroll people in a campaign or send communications. Sending remains subject to a later campaign action and the exact purpose/channel consent rules.

PostgreSQL/API tests cover authorization, live preview, update/deactivation, and audit events.
