-- Bind a generation attempt to the one account-scoped quote it consumes.
ALTER TABLE generation_jobs
  ADD COLUMN credit_reservation_id uuid
  REFERENCES flow_credit_reservations(id);

CREATE UNIQUE INDEX idx_generation_job_credit_reservation
  ON generation_jobs(credit_reservation_id)
  WHERE credit_reservation_id IS NOT NULL;
