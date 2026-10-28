# Sprint 216: Include and exclude audience segments

Saved audience criteria may combine up to 20 active segments from the same organization scope. Inclusion segments are combined as a union with any direct profile/activity filters; exclusion segments are subtracted from that union.

Segment composition is intentionally one level deep to keep membership evaluation bounded and explainable. A referenced segment cannot be deactivated while an active segment depends on it. Preview continues to resolve membership live and applies the caller's profile visibility scope.
