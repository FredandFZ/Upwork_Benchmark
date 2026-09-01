// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

import { ProjectStateModel } from "../contracts/ProjectStateModel.sol";

contract ProjectStateModelSmoke {
    function testCurrentModelLoads() public {
        ProjectStateModel model = new ProjectStateModel();
        assert(model.FEATURE_COUNT() == 30);
        assert(model.CONFIGURATION_DIGEST() != bytes32(0));
    }

    function testReferralBoundary() public {
        ProjectStateModel model = new ProjectStateModel();
        assert(!model.isReferralCodeValid(0, 10));
        assert(model.isReferralCodeValid(1, 10));
        assert(!model.isReferralCodeValid(11, 10));
    }
}
