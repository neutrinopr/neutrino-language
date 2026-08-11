# Public, source-complete M6/Web3 publication checks.
add_test(NAME public-pack-receipts
  COMMAND python3 ${PROJECT_SOURCE_DIR}/scripts/verify_public_pack_receipt.py --all)
set_tests_properties(public-pack-receipts PROPERTIES LABELS "public;receipt")

add_test(NAME public-pack-receipts-selftest
  COMMAND python3 ${PROJECT_SOURCE_DIR}/scripts/verify_public_pack_receipt.py
    --all --self-test)
set_tests_properties(public-pack-receipts-selftest
  PROPERTIES LABELS "public;receipt;mutation")

add_test(NAME public-pack-resolver
  COMMAND python3 ${PROJECT_SOURCE_DIR}/scripts/gates/m6_pack_resolver.py
    --repo ${PROJECT_SOURCE_DIR}
    --manifest ${PROJECT_SOURCE_DIR}/docs/m6-curated-example-corpus.json)
set_tests_properties(public-pack-resolver
  PROPERTIES LABELS "public;receipt;resolver")
