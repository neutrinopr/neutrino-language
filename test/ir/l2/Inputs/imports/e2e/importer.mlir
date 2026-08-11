// An l2.domain importing the governed coordinate.core_promo_campaign@1.0.0.
l2.domain "coordinate.consumer" attributes {version = "1.0.0", implements = "coordinate.consumer"} {
  l2.import "coordinate.core_promo_campaign" {version = "1.0.0"}
  l2.l1_feature "effect:debit" {kind = "primitive"}
  l2.concept "x" {kind = "state", classification = "executable"}
  l2.reduce "r" "x" -> "effect:debit" {relation = "expands", lossiness = "lossless"}
  l2.provenance "r" {source = "s", status = "accepted"}
}
