namespace anti_inference_fixture {

const char *domainAlpha = "__neu_gate_synthetic_domain_alpha";
const char domainBeta[] = {
    '_', '_', 'n', 'e', 'u', '_', 'g', 'a', 't', 'e', '_', 's', 'y', 'n',
    't', 'h', 'e', 't', 'i', 'c', '_', 'd', 'o', 'm', 'a', 'i', 'n', '_',
    'b', 'e', 't', 'a',
};

void semanticInferenceCases(const llvm::json::Object &spec) {
  (void)effects[0];
  (void)spec.getString("workflowKey");
  (void)spec.getArray("invariants");
  (void)spec.getObject("lifecycle");
}

} // namespace anti_inference_fixture
