# Sprint 180: decision queue commerce access

The regression test now checks both authorized and restricted campaign viewers. A viewer with campaign and commerce-event permissions sees linked currency outcomes; after removing commerce-event permission, the campaign queue remains available but returns an empty commerce summary.

This protects the boundary between campaign visibility and commerce-data visibility.
