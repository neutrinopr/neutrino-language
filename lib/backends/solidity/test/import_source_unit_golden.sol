// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "./CoordinationEnvelope.sol";

// Golden fixture for the  slice 4 import render-pair proof. These are the
// EXACT bytes legalizeSolidity's temporal path emits as the source-unit header
// (verified against neutrino-gen output for accepted_multi_policy.neu): the SPDX
// license, the version pragma, and `import "./CoordinationEnvelope.sol";`. The
// temporal contract is generated on the fly by the oracle lit tests and not
// committed as a src golden, so this pins the exact production import line the
// generated `Import` printer handler must reproduce (and a `.td` mutation breaks).
