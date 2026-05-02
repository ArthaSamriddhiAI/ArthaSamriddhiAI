"""T1 event names emitted by the cluster 0 system surface.

Currently small (just role-tree home visits per chunk 0.2). Future
clusters add system-level events (rule corpus version updates, model
portfolio version activations, etc.) here.
"""

from __future__ import annotations

# Chunk 0.2 — emitted whenever the user lands on a role-tree home page.
# Per chunk 0.2 acceptance criterion 11:
# "Each role's home page emits a T1 telemetry event for the role tree
#  visit (`role_home_visited` with payload `{role, user_id}`); useful
#  for understanding role-tree usage patterns."
ROLE_HOME_VISITED = "role_home_visited"
