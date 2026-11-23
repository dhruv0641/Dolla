-- One canonical attempt per publication/window/registry/requested raw metric set.

CREATE UNIQUE INDEX analytics_metric_snapshot_identity
  ON analytics_metric_collection_attempts
  (publication_id, window_name, registry_version, metric_ids);
