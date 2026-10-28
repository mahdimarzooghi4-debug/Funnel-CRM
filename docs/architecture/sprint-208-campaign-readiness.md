# Sprint 208: campaign readiness review

A campaign readiness endpoint combines schedule completeness, audience segment activity, and content approval state for a draft campaign. It marks a campaign ready for manager review only when all three checks pass; this remains a review checklist, not an automatic launch approval.

Open CRM work items linked to the campaign are shown only when the caller also has work-item view permission. Asset status counts and review state are scoped to the campaign's organization and tenant.
