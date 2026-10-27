# Sprint 183: order values in campaign decision queue

Campaign queue commerce summaries now include distinct paid/refunded order counts and net paid amount per paid order for each currency. The net per-order value is computed as net paid amount divided by distinct paid orders; it is descriptive and does not allocate campaign spend.

Validation covers multiple USD orders, one refunded order, and an independent EUR result.
