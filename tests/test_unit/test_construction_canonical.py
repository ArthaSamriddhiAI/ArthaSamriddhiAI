"""Pass 16 — construction pipeline acceptance tests.

§5.13:
  Test 5 — Construction approval surface displays version diff (prior vs proposed),
           blast radius (clients in tolerance who'd breach, AUM moved, txn/tax cost,
           day-1 N0 alert count).
  Test 6 — Shadow mode triggered when blast share exceeds threshold.
  Test 7 — L4 substitution cascade — Fund A removed, Fund B added; affected clients listed.
  Test 8 — Out-of-bucket flag triggers single-client construction.

Plus run-level tests:
  * `ConstructionRun` envelope assembly + round-trip.
  * Determinism within version (input_hash stable on identical inputs).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from artha.canonical.construction import (
    BlastRadius,
    BucketConstructionProposal,
    BucketVersionDiff,
    ClientPortfolioSlice,
    ConstructionInputs,
    ConstructionRun,
    ConstructionRunStatus,
    ConstructionTrigger,
    L4SubstitutionImpact,
    RolloutMode,
)
from artha.canonical.governance import G3Evaluation
from artha.canonical.model_portfolio import (
    ConstructionContext,
    ModelPortfolioObject,
    TargetWithTolerance,
)
from artha.common.types import (
    AssetClass,
    Bucket,
    Permission,
    VehicleType,
)
from artha.construction import (
    ConstructionOrchestrator,
    compute_blast_radius,
    compute_substitution_impacts,
    compute_version_diff,
    should_use_shadow_mode,
)

# ===========================================================================
# Fixtures
# ===========================================================================


def _model(
    *,
    model_id: str,
    bucket: Bucket = Bucket.MOD_LT,
    version: str = "1.0.0",
    equity_target: float = 0.50,
    equity_band: float = 0.05,
) -> ModelPortfolioObject:
    """Build a 2-class equity/debt model. Debt is auto-computed as 1 - equity."""
    debt_target = 1.0 - equity_target
    return ModelPortfolioObject(
        model_id=model_id,
        bucket=bucket,
        version=version,
        firm_id="firm_test",
        created_at=datetime(2026, 4, 1, tzinfo=UTC),
        effective_at=datetime(2026, 4, 1, tzinfo=UTC),
        approved_by="cio_jane",
        approval_rationale="construction test model",
        l1_targets={
            AssetClass.EQUITY: TargetWithTolerance(
                target=equity_target, tolerance_band=equity_band
            ),
            AssetClass.DEBT: TargetWithTolerance(
                target=debt_target, tolerance_band=0.05
            ),
        },
        construction=ConstructionContext(construction_pipeline_run_id=f"cp_{model_id}"),
    )


def _model_with_l2_l3() -> ModelPortfolioObject:
    """Model with L2 and L3 targets for diff testing."""
    return ModelPortfolioObject(
        model_id="mp_with_l2_l3",
        bucket=Bucket.MOD_LT,
        version="1.0.0",
        firm_id="firm_test",
        created_at=datetime(2026, 4, 1, tzinfo=UTC),
        effective_at=datetime(2026, 4, 1, tzinfo=UTC),
        approved_by="cio_jane",
        approval_rationale="L2/L3 model",
        l1_targets={
            AssetClass.EQUITY: TargetWithTolerance(target=0.50, tolerance_band=0.05),
            AssetClass.DEBT: TargetWithTolerance(target=0.50, tolerance_band=0.05),
        },
        l2_targets={
            AssetClass.EQUITY: {
                VehicleType.MUTUAL_FUND: TargetWithTolerance(
                    target=0.70, tolerance_band=0.10
                ),
                VehicleType.PMS: TargetWithTolerance(
                    target=0.30, tolerance_band=0.10
                ),
            },
        },
        l3_targets={
            "equity.mutual_fund": {
                "large_cap": TargetWithTolerance(target=0.60, tolerance_band=0.15),
                "mid_cap": TargetWithTolerance(target=0.40, tolerance_band=0.15),
            },
        },
        construction=ConstructionContext(construction_pipeline_run_id="cp_l2_l3"),
    )


def _client_slice(
    *,
    client_id: str,
    bucket: Bucket = Bucket.MOD_LT,
    aum_inr: float = 10_000_000.0,
    equity_weight: float = 0.50,
    holdings: dict[str, float] | None = None,
) -> ClientPortfolioSlice:
    return ClientPortfolioSlice(
        client_id=client_id,
        firm_id="firm_test",
        bucket=bucket,
        aum_inr=aum_inr,
        current_l1_weights={
            "equity": equity_weight,
            "debt": 1.0 - equity_weight,
        },
        holdings_by_instrument_id=holdings or {},
    )


def _g3(*, permission: Permission = Permission.APPROVED) -> G3Evaluation:
    return G3Evaluation(
        case_id="construction_case_p16",
        timestamp=datetime(2026, 4, 29, tzinfo=UTC),
        permission=permission,
        g1_input_hash="hash_g1",
        g2_input_hash="hash_g2",
        input_hash="hash_g3",
    )


# ===========================================================================
# §5.13 Test 5 — version diff + blast radius
# ===========================================================================


class TestVersionDiff:
    def test_l1_target_change_surfaced(self):
        prior = _model(model_id="mp_v1", equity_target=0.50, equity_band=0.05)
        proposed = _model(
            model_id="mp_v2", version="2.0.0", equity_target=0.55, equity_band=0.05
        )
        diff = compute_version_diff(
            bucket=Bucket.MOD_LT, prior_model=prior, proposed_model=proposed
        )
        equity_changes = [c for c in diff.cell_changes if c.cell_key == "equity"]
        assert equity_changes
        c = equity_changes[0]
        assert c.level == "l1"
        assert c.prior_target == pytest.approx(0.50)
        assert c.proposed_target == pytest.approx(0.55)
        assert c.delta == pytest.approx(0.05)

    def test_l1_band_change_surfaced(self):
        prior = _model(model_id="mp_v1", equity_band=0.05)
        proposed = _model(model_id="mp_v2", version="2.0.0", equity_band=0.10)
        diff = compute_version_diff(
            bucket=Bucket.MOD_LT, prior_model=prior, proposed_model=proposed
        )
        equity_changes = [c for c in diff.cell_changes if c.cell_key == "equity"]
        assert equity_changes
        assert equity_changes[0].prior_band == pytest.approx(0.05)
        assert equity_changes[0].proposed_band == pytest.approx(0.10)

    def test_no_change_no_diff(self):
        prior = _model(model_id="mp_v1")
        proposed = _model(model_id="mp_v2", version="2.0.0")
        diff = compute_version_diff(
            bucket=Bucket.MOD_LT, prior_model=prior, proposed_model=proposed
        )
        assert diff.cell_changes_count == 0
        assert diff.cell_changes == []

    def test_no_prior_marks_all_as_new(self):
        proposed = _model(model_id="mp_v1")
        diff = compute_version_diff(
            bucket=Bucket.MOD_LT, prior_model=None, proposed_model=proposed
        )
        # Both equity and debt surface as new cells (no prior)
        assert diff.cell_changes_count == 2
        for c in diff.cell_changes:
            assert c.prior_target is None
            assert c.proposed_target is not None

    def test_l2_l3_diff_surfaced(self):
        prior_simple = _model(model_id="mp_v1")  # no L2/L3
        proposed = _model_with_l2_l3()
        diff = compute_version_diff(
            bucket=Bucket.MOD_LT,
            prior_model=prior_simple,
            proposed_model=proposed,
        )
        l2_changes = [c for c in diff.cell_changes if c.level == "l2"]
        l3_changes = [c for c in diff.cell_changes if c.level == "l3"]
        assert len(l2_changes) >= 2  # MF + PMS at L2
        assert len(l3_changes) >= 2  # large_cap + mid_cap at L3
        assert any("mutual_fund" in c.cell_key for c in l2_changes)
        assert any("large_cap" in c.cell_key for c in l3_changes)


class TestBlastRadius:
    def test_test_5_blast_radius_components(self):
        """Test 5 — blast radius surfaces all required dimensions."""
        prior = _model(model_id="mp_v1", equity_target=0.50, equity_band=0.05)
        proposed = _model(
            model_id="mp_v2", version="2.0.0",
            equity_target=0.65,  # +15pp shift
            equity_band=0.05,
        )
        # 5 clients in bucket, all currently at 50% equity (in tolerance for prior)
        # Proposed wants 65% ± 5%, so 50% breaches
        slices = [
            _client_slice(client_id=f"c{i}", equity_weight=0.50, aum_inr=10_000_000.0)
            for i in range(5)
        ]
        blast = compute_blast_radius(
            bucket=Bucket.MOD_LT,
            prior_model=prior,
            proposed_model=proposed,
            client_slices=slices,
        )
        assert blast.clients_in_bucket_count == 5
        assert blast.clients_in_tolerance_who_breach == 5  # all breach proposed
        assert blast.day_one_n0_alert_count == 5
        assert blast.blast_radius_share == pytest.approx(1.0)
        assert blast.total_aum_moved_inr > 0
        assert blast.estimated_txn_cost_inr > 0
        assert blast.estimated_tax_cost_inr > 0

    def test_clients_within_proposed_tolerance_dont_breach(self):
        prior = _model(model_id="mp_v1", equity_target=0.50, equity_band=0.05)
        proposed = _model(
            model_id="mp_v2", version="2.0.0", equity_target=0.52, equity_band=0.05
        )
        # Clients at 50% equity — within proposed band [47%, 57%]
        slices = [
            _client_slice(client_id=f"c{i}", equity_weight=0.50)
            for i in range(3)
        ]
        blast = compute_blast_radius(
            bucket=Bucket.MOD_LT,
            prior_model=prior,
            proposed_model=proposed,
            client_slices=slices,
        )
        assert blast.clients_in_tolerance_who_breach == 0
        assert blast.day_one_n0_alert_count == 0

    def test_clients_in_other_buckets_excluded(self):
        prior = _model(model_id="mp_v1", equity_target=0.50)
        proposed = _model(model_id="mp_v2", version="2.0.0", equity_target=0.65)
        # 3 in MOD_LT, 2 in CON_LT
        slices = (
            [_client_slice(client_id=f"mod{i}", bucket=Bucket.MOD_LT) for i in range(3)]
            + [_client_slice(client_id=f"con{i}", bucket=Bucket.CON_LT) for i in range(2)]
        )
        blast = compute_blast_radius(
            bucket=Bucket.MOD_LT,
            prior_model=prior,
            proposed_model=proposed,
            client_slices=slices,
        )
        assert blast.clients_in_bucket_count == 3
        assert blast.clients_in_tolerance_who_breach == 3  # only MOD_LT clients

    def test_empty_bucket(self):
        proposed = _model(model_id="mp_v1")
        blast = compute_blast_radius(
            bucket=Bucket.MOD_LT,
            prior_model=None,
            proposed_model=proposed,
            client_slices=[],
        )
        assert blast.clients_in_bucket_count == 0
        assert blast.blast_radius_share == 0.0


# ===========================================================================
# §5.13 Test 6 — shadow mode
# ===========================================================================


class TestShadowMode:
    def test_test_6_shadow_triggered_above_threshold(self):
        # 80% of clients breach → above 25% threshold → shadow
        blast = BlastRadius(
            bucket=Bucket.MOD_LT,
            clients_in_bucket_count=10,
            clients_in_tolerance_who_breach=8,
            blast_radius_share=0.80,
        )
        assert should_use_shadow_mode(blast_radius=blast, threshold=0.25) is True

    def test_test_6_shadow_not_triggered_below_threshold(self):
        # 10% of clients breach → below 25% threshold → immediate
        blast = BlastRadius(
            bucket=Bucket.MOD_LT,
            clients_in_bucket_count=10,
            clients_in_tolerance_who_breach=1,
            blast_radius_share=0.10,
        )
        assert should_use_shadow_mode(blast_radius=blast, threshold=0.25) is False

    def test_orchestrator_picks_shadow_mode_on_high_blast(self):
        prior = _model(model_id="mp_v1", equity_target=0.50, equity_band=0.05)
        proposed = _model(
            model_id="mp_v2", version="2.0.0",
            equity_target=0.70,  # large shift
        )
        # 10 clients, all at 50%, all will breach proposed
        slices = [
            _client_slice(client_id=f"c{i}", equity_weight=0.50) for i in range(10)
        ]
        orch = ConstructionOrchestrator()
        proposal = orch.propose_bucket(
            bucket=Bucket.MOD_LT,
            proposed_model=proposed,
            prior_model=prior,
            client_slices=slices,
            g3_evaluation=_g3(),
            shadow_blast_threshold=0.25,
        )
        assert proposal.rollout_mode is RolloutMode.SHADOW_30D

    def test_orchestrator_picks_immediate_on_low_blast(self):
        prior = _model(model_id="mp_v1", equity_target=0.50, equity_band=0.05)
        proposed = _model(
            model_id="mp_v2", version="2.0.0", equity_target=0.52, equity_band=0.05
        )
        slices = [_client_slice(client_id=f"c{i}", equity_weight=0.50) for i in range(10)]
        orch = ConstructionOrchestrator()
        proposal = orch.propose_bucket(
            bucket=Bucket.MOD_LT,
            proposed_model=proposed,
            prior_model=prior,
            client_slices=slices,
            g3_evaluation=_g3(),
        )
        assert proposal.rollout_mode is RolloutMode.IMMEDIATE


# ===========================================================================
# §5.13 Test 7 — L4 substitution cascade
# ===========================================================================


class TestL4Substitution:
    def test_test_7_substitution_identifies_affected_clients(self):
        # 3 clients hold Fund A, 2 don't
        slices = [
            _client_slice(
                client_id="c1", holdings={"FUND_A": 1_000_000.0, "FUND_X": 500_000.0}
            ),
            _client_slice(
                client_id="c2", holdings={"FUND_A": 2_000_000.0}
            ),
            _client_slice(
                client_id="c3", holdings={"FUND_A": 500_000.0}
            ),
            _client_slice(
                client_id="c4", holdings={"FUND_X": 1_000_000.0}
            ),
            _client_slice(
                client_id="c5", holdings={}
            ),
        ]
        impacts = compute_substitution_impacts(
            client_slices=slices,
            removed_instrument_ids=["FUND_A"],
            replacement_map={"FUND_A": "FUND_B"},
        )
        assert len(impacts) == 1
        impact = impacts[0]
        assert impact.removed_instrument_id == "FUND_A"
        assert impact.replacement_instrument_id == "FUND_B"
        assert impact.affected_client_ids == ["c1", "c2", "c3"]
        assert impact.total_aum_affected_inr == pytest.approx(3_500_000.0)

    def test_test_7_unmapped_replacement_marks_sentinel(self):
        slices = [_client_slice(client_id="c1", holdings={"FUND_A": 1_000_000.0})]
        impacts = compute_substitution_impacts(
            client_slices=slices,
            removed_instrument_ids=["FUND_A"],
            replacement_map={},  # no replacement specified
        )
        assert len(impacts) == 1
        assert impacts[0].replacement_instrument_id == "unmapped"

    def test_no_affected_clients_no_impact(self):
        slices = [_client_slice(client_id="c1", holdings={"FUND_X": 1_000_000.0})]
        impacts = compute_substitution_impacts(
            client_slices=slices,
            removed_instrument_ids=["FUND_A"],
            replacement_map={"FUND_A": "FUND_B"},
        )
        assert impacts == []

    def test_orchestrator_run_includes_l4_impacts(self):
        slices = [
            _client_slice(client_id="c1", holdings={"FUND_A": 1_000_000.0}),
            _client_slice(client_id="c2", holdings={"FUND_A": 500_000.0}),
        ]
        inputs = ConstructionInputs(
            firm_id="firm_test",
            initiated_by="cio_jane",
            trigger=ConstructionTrigger.FUND_UNIVERSE,
            scoped_buckets=[],
            client_slices=slices,
            l4_removed_instrument_ids=["FUND_A"],
            l4_replacement_map={"FUND_A": "FUND_B"},
        )
        orch = ConstructionOrchestrator()
        run = orch.run(inputs=inputs)
        assert len(run.l4_substitution_impacts) == 1
        assert run.l4_substitution_impacts[0].affected_client_ids == ["c1", "c2"]


# ===========================================================================
# §5.13 Test 8 — out-of-bucket / single-client construction
# ===========================================================================


class TestSingleClientConstruction:
    def test_test_8_single_client_proposal_requires_advisor_escalation(self):
        custom_model = _model(model_id="mp_custom_c1", version="1.0.0")
        orch = ConstructionOrchestrator()
        proposal = orch.propose_single_client(
            client_id="c1",
            firm_id="firm_test",
            proposed_model=custom_model,
            rationale="Out-of-bucket: incompatible with all 9 buckets.",
        )
        assert proposal.advisor_escalation_required is True
        assert proposal.proposed_model.model_id == "mp_custom_c1"
        assert "Out-of-bucket" in proposal.rationale

    def test_test_8_run_with_single_client_trigger(self):
        custom_model = _model(model_id="mp_custom_c1", version="1.0.0")
        inputs = ConstructionInputs(
            firm_id="firm_test",
            initiated_by="cio_jane",
            trigger=ConstructionTrigger.SINGLE_CLIENT,
            scoped_buckets=[],
            single_client_id="c1",
        )
        orch = ConstructionOrchestrator()
        run = orch.run(
            inputs=inputs,
            single_client_proposed_model=custom_model,
            single_client_artefacts={
                "rationale": "Out-of-bucket per §7.10 Test 10."
            },
        )
        assert run.trigger is ConstructionTrigger.SINGLE_CLIENT
        assert run.single_client_proposal is not None
        assert run.single_client_proposal.client_id == "c1"
        assert run.single_client_proposal.advisor_escalation_required is True

    def test_run_without_single_client_id_skips_proposal(self):
        custom_model = _model(model_id="mp_custom", version="1.0.0")
        inputs = ConstructionInputs(
            firm_id="firm_test",
            initiated_by="cio_jane",
            trigger=ConstructionTrigger.SINGLE_CLIENT,
            scoped_buckets=[],
            single_client_id=None,  # missing
        )
        orch = ConstructionOrchestrator()
        run = orch.run(inputs=inputs, single_client_proposed_model=custom_model)
        assert run.single_client_proposal is None


# ===========================================================================
# Run-level orchestration + envelope tests
# ===========================================================================


class TestConstructionRun:
    def test_bucket_run_with_g3_approved(self):
        prior = _model(model_id="mp_v1")
        proposed = _model(model_id="mp_v2", version="2.0.0", equity_target=0.55)
        slices = [_client_slice(client_id=f"c{i}", equity_weight=0.50) for i in range(5)]
        inputs = ConstructionInputs(
            firm_id="firm_test",
            initiated_by="cio_jane",
            trigger=ConstructionTrigger.SCHEDULED,
            scoped_buckets=[Bucket.MOD_LT],
            prior_models={Bucket.MOD_LT: prior},
            client_slices=slices,
        )
        orch = ConstructionOrchestrator()
        run = orch.run(
            inputs=inputs,
            bucket_proposed_models={Bucket.MOD_LT: proposed},
            bucket_artefacts={
                Bucket.MOD_LT: {"g3_evaluation": _g3(permission=Permission.APPROVED)},
            },
        )
        assert len(run.bucket_proposals) == 1
        bp = run.bucket_proposals[0]
        assert bp.bucket is Bucket.MOD_LT
        assert bp.approved_for_rollout is True

    def test_g3_blocked_marks_run_rejected(self):
        prior = _model(model_id="mp_v1")
        proposed = _model(model_id="mp_v2", version="2.0.0", equity_target=0.55)
        inputs = ConstructionInputs(
            firm_id="firm_test",
            initiated_by="cio_jane",
            trigger=ConstructionTrigger.SCHEDULED,
            scoped_buckets=[Bucket.MOD_LT],
            prior_models={Bucket.MOD_LT: prior},
        )
        orch = ConstructionOrchestrator()
        run = orch.run(
            inputs=inputs,
            bucket_proposed_models={Bucket.MOD_LT: proposed},
            bucket_artefacts={
                Bucket.MOD_LT: {"g3_evaluation": _g3(permission=Permission.BLOCKED)},
            },
        )
        assert run.status is ConstructionRunStatus.REJECTED
        assert run.bucket_proposals[0].approved_for_rollout is False
        assert "BLOCKED" in run.bucket_proposals[0].approval_rationale

    def test_shadow_mode_marks_run_shadow_active(self):
        prior = _model(model_id="mp_v1", equity_target=0.50, equity_band=0.05)
        proposed = _model(
            model_id="mp_v2", version="2.0.0", equity_target=0.70
        )
        # 10 clients all at 50%, all breach proposed
        slices = [_client_slice(client_id=f"c{i}", equity_weight=0.50) for i in range(10)]
        inputs = ConstructionInputs(
            firm_id="firm_test",
            initiated_by="cio_jane",
            trigger=ConstructionTrigger.MACRO_SHIFT,
            scoped_buckets=[Bucket.MOD_LT],
            prior_models={Bucket.MOD_LT: prior},
            client_slices=slices,
            shadow_blast_threshold=0.25,
        )
        orch = ConstructionOrchestrator()
        run = orch.run(
            inputs=inputs,
            bucket_proposed_models={Bucket.MOD_LT: proposed},
            bucket_artefacts={
                Bucket.MOD_LT: {"g3_evaluation": _g3()},
            },
        )
        assert run.status is ConstructionRunStatus.SHADOW_ACTIVE
        assert run.bucket_proposals[0].rollout_mode is RolloutMode.SHADOW_30D

    def test_run_determinism(self):
        prior = _model(model_id="mp_v1")
        proposed = _model(model_id="mp_v2", version="2.0.0", equity_target=0.55)
        inputs = ConstructionInputs(
            firm_id="firm_test",
            initiated_by="cio_jane",
            trigger=ConstructionTrigger.SCHEDULED,
            scoped_buckets=[Bucket.MOD_LT],
            prior_models={Bucket.MOD_LT: prior},
        )
        orch = ConstructionOrchestrator()
        run1 = orch.run(
            inputs=inputs,
            bucket_proposed_models={Bucket.MOD_LT: proposed},
            bucket_artefacts={Bucket.MOD_LT: {"g3_evaluation": _g3()}},
        )
        run2 = orch.run(
            inputs=inputs,
            bucket_proposed_models={Bucket.MOD_LT: proposed},
            bucket_artefacts={Bucket.MOD_LT: {"g3_evaluation": _g3()}},
        )
        assert run1.input_hash == run2.input_hash

    def test_round_trip_construction_run(self):
        prior = _model(model_id="mp_v1")
        proposed = _model(model_id="mp_v2", version="2.0.0", equity_target=0.55)
        inputs = ConstructionInputs(
            firm_id="firm_test",
            initiated_by="cio_jane",
            trigger=ConstructionTrigger.SCHEDULED,
            scoped_buckets=[Bucket.MOD_LT],
            prior_models={Bucket.MOD_LT: prior},
        )
        orch = ConstructionOrchestrator()
        run = orch.run(
            inputs=inputs,
            bucket_proposed_models={Bucket.MOD_LT: proposed},
            bucket_artefacts={Bucket.MOD_LT: {"g3_evaluation": _g3()}},
        )
        round_tripped = ConstructionRun.model_validate_json(run.model_dump_json())
        assert round_tripped == run

    def test_multi_bucket_scoped_run(self):
        prior_mod = _model(model_id="mp_mod_v1", bucket=Bucket.MOD_LT)
        prior_con = _model(model_id="mp_con_v1", bucket=Bucket.CON_LT)
        proposed_mod = _model(
            model_id="mp_mod_v2", version="2.0.0", bucket=Bucket.MOD_LT,
            equity_target=0.55,
        )
        proposed_con = _model(
            model_id="mp_con_v2", version="2.0.0", bucket=Bucket.CON_LT,
            equity_target=0.30,
        )
        inputs = ConstructionInputs(
            firm_id="firm_test",
            initiated_by="cio_jane",
            trigger=ConstructionTrigger.SCHEDULED,
            scoped_buckets=[Bucket.MOD_LT, Bucket.CON_LT],
            prior_models={Bucket.MOD_LT: prior_mod, Bucket.CON_LT: prior_con},
        )
        orch = ConstructionOrchestrator()
        run = orch.run(
            inputs=inputs,
            bucket_proposed_models={
                Bucket.MOD_LT: proposed_mod,
                Bucket.CON_LT: proposed_con,
            },
            bucket_artefacts={
                Bucket.MOD_LT: {"g3_evaluation": _g3()},
                Bucket.CON_LT: {"g3_evaluation": _g3()},
            },
        )
        assert len(run.bucket_proposals) == 2
        proposal_buckets = {bp.bucket for bp in run.bucket_proposals}
        assert proposal_buckets == {Bucket.MOD_LT, Bucket.CON_LT}


class TestPropose:
    def test_propose_bucket_returns_proposal(self):
        proposed = _model(model_id="mp_v1")
        orch = ConstructionOrchestrator()
        proposal = orch.propose_bucket(
            bucket=Bucket.MOD_LT,
            proposed_model=proposed,
            prior_model=None,
            client_slices=[],
            g3_evaluation=_g3(),
        )
        assert isinstance(proposal, BucketConstructionProposal)
        assert proposal.bucket is Bucket.MOD_LT
        assert proposal.proposed_model.model_id == "mp_v1"
        assert proposal.approved_for_rollout is True

    def test_round_trip_bucket_proposal(self):
        proposed = _model(model_id="mp_v1")
        orch = ConstructionOrchestrator()
        proposal = orch.propose_bucket(
            bucket=Bucket.MOD_LT,
            proposed_model=proposed,
            prior_model=None,
            client_slices=[],
            g3_evaluation=_g3(),
        )
        round_tripped = BucketConstructionProposal.model_validate_json(
            proposal.model_dump_json()
        )
        assert round_tripped == proposal

    def test_round_trip_blast_radius(self):
        blast = BlastRadius(
            bucket=Bucket.MOD_LT,
            clients_in_bucket_count=5,
            clients_in_tolerance_who_breach=2,
            total_aum_moved_inr=1_000_000.0,
            blast_radius_share=0.40,
        )
        round_tripped = BlastRadius.model_validate_json(blast.model_dump_json())
        assert round_tripped == blast

    def test_round_trip_version_diff(self):
        diff = BucketVersionDiff(
            bucket=Bucket.MOD_LT,
            prior_model_id="mp_v1",
            proposed_model_id="mp_v2",
            prior_version="1.0.0",
            proposed_version="2.0.0",
        )
        round_tripped = BucketVersionDiff.model_validate_json(diff.model_dump_json())
        assert round_tripped == diff

    def test_round_trip_l4_impact(self):
        impact = L4SubstitutionImpact(
            removed_instrument_id="FUND_A",
            replacement_instrument_id="FUND_B",
            affected_client_ids=["c1", "c2"],
            total_aum_affected_inr=2_000_000.0,
        )
        round_tripped = L4SubstitutionImpact.model_validate_json(
            impact.model_dump_json()
        )
        assert round_tripped == impact
