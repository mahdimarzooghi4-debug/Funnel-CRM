# Sprint 218: Consent-aware campaign readiness

Campaign readiness now checks whether at least one member of the linked audience has a verified contact point and the latest explicit granted consent for the selected communication purpose and mapped channel. The purpose defaults to `marketing` and can be provided as a query parameter.

Supported mappings are email-to-email, phone-to-phone, messaging-to-phone, and social-to-social-handle. Other campaign channels are reported as unsupported because the CRM does not currently define an equivalent consent/contact channel. Missing access is shown as not authorized; neither condition is treated as ready. Readiness remains a manager checklist and does not itself send messages or approve launch.
