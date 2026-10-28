# Sprint 207: campaign content asset review

Marketing teams can save campaign-linked or reusable channel assets such as copy, images, videos, landing pages, and documents. An asset may contain text, an HTTP(S) reference, or both. Binary uploads remain owned by the connected storage product; this CRM record holds the approved content and its reference.

Assets move through draft, in-review, approved, or rejected states. Rejected assets can be edited and submitted again; reviewed assets are immutable until they are rejected and revised. Each state change writes an audit event. Campaign and organization scoping is enforced by permissions, foreign keys, and tenant row-level security.
