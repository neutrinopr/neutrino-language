// Source-neutral L2 model for the pay-for-result coordination contract. Every
// concept reduces to one normalized requirement induced by verified coordination;
// the forcing harness compares this complete reduction through source and
// capability-spec construction.
l2.domain "coordinate.pay_for_result" attributes {version = "1.0.0", implements = "coordinate.pay_for_result", coverage = "full"} {
  l2.l1_feature "authorization:explicit" {kind = "primitive"}
  l2.l1_feature "effect:debit" {kind = "primitive"}
  l2.l1_feature "effect:credit" {kind = "primitive"}
  l2.l1_feature "guard:conditional" {kind = "primitive"}
  l2.l1_feature "invariant:balanced" {kind = "obligation"}
  l2.l1_feature "attestation:quorum" {kind = "primitive"}
  l2.l1_feature "terminal:success" {kind = "primitive"}
  l2.l1_feature "terminal:aborted" {kind = "primitive"}
  l2.l1_feature "replay:idempotent" {kind = "obligation"}
  l2.l1_feature "identity:explicit_instance_key" {kind = "primitive"}

  l2.concept "authorized_settlement" {kind = "concept", classification = "executable"}
  l2.concept "requester_debit" {kind = "concept", classification = "executable"}
  l2.concept "worker_credit" {kind = "concept", classification = "executable"}
  l2.concept "accepted_result_guard" {kind = "concept", classification = "executable"}
  l2.concept "balanced_incentive" {kind = "concept", classification = "executable"}
  l2.concept "admissible_result" {kind = "concept", classification = "executable"}
  l2.concept "successful_settlement" {kind = "state", classification = "executable"}
  l2.concept "aborted_settlement" {kind = "state", classification = "executable"}
  l2.concept "single_settlement" {kind = "concept", classification = "executable"}
  l2.concept "stable_job_identity" {kind = "concept", classification = "executable"}

  l2.reduce "r_authorization" "authorized_settlement" -> "authorization:explicit" {relation = "protects", lossiness = "lossless"}
  l2.reduce "r_debit" "requester_debit" -> "effect:debit" {relation = "expands", lossiness = "lossless"}
  l2.reduce "r_credit" "worker_credit" -> "effect:credit" {relation = "expands", lossiness = "lossless"}
  l2.reduce "r_guard" "accepted_result_guard" -> "guard:conditional" {relation = "protects", lossiness = "lossless"}
  l2.reduce "r_balance" "balanced_incentive" -> "invariant:balanced" {relation = "protects", lossiness = "lossless"}
  l2.reduce "r_attestation" "admissible_result" -> "attestation:quorum" {relation = "expands", lossiness = "lossless"}
  l2.reduce "r_success" "successful_settlement" -> "terminal:success" {relation = "expands", lossiness = "lossless"}
  l2.reduce "r_abort" "aborted_settlement" -> "terminal:aborted" {relation = "expands", lossiness = "lossless"}
  l2.reduce "r_replay" "single_settlement" -> "replay:idempotent" {relation = "protects", lossiness = "lossless"}
  l2.reduce "r_identity" "stable_job_identity" -> "identity:explicit_instance_key" {relation = "protects", lossiness = "lossless"}

  l2.provenance "r_authorization" {source = "pay-for-result-contract", status = "accepted"}
  l2.provenance "r_debit" {source = "pay-for-result-contract", status = "accepted"}
  l2.provenance "r_credit" {source = "pay-for-result-contract", status = "accepted"}
  l2.provenance "r_guard" {source = "pay-for-result-contract", status = "accepted"}
  l2.provenance "r_balance" {source = "pay-for-result-contract", status = "accepted"}
  l2.provenance "r_attestation" {source = "pay-for-result-contract", status = "accepted"}
  l2.provenance "r_success" {source = "pay-for-result-contract", status = "accepted"}
  l2.provenance "r_abort" {source = "pay-for-result-contract", status = "accepted"}
  l2.provenance "r_replay" {source = "pay-for-result-contract", status = "accepted"}
  l2.provenance "r_identity" {source = "pay-for-result-contract", status = "accepted"}
}
