# Sprint 111: Follow-up outcome visibility

The lifecycle manager queue now shows the latest outcome recorded on a generated follow-up task, including its outcome code and timestamp. This lets managers review whether the task resulted in contact, a callback request, or another recorded outcome without opening each work item individually.

The latest result is scoped to the tenant and selected organization unit through the existing linked task query. When no outcome has been recorded on the task, the new fields are null.
