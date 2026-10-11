import React from "react";
import {
  Sparkles,
  ShieldAlert,
  CheckCircle,
  AlertOctagon,
  HelpCircle,
  ExternalLink,
  ChevronRight,
  Info,
  ShieldCheck,
} from "lucide-react";
import { HypothesisResponse, GroundednessStatus } from "../../types/investigation";

interface HypothesisCardProps {
  hypothesis: HypothesisResponse;
  onInspectEvidence?: (evidenceId: string) => void;
  onNavigateRemediations?: () => void;
}

export const HypothesisCard: React.FC<HypothesisCardProps> = ({
  hypothesis,
  onInspectEvidence,
  onNavigateRemediations,
}) => {
  const getGroundednessBadgeClass = (status?: GroundednessStatus | string | null) => {
    switch (status) {
      case "well_supported":
        return "grounded-badge-high";
      case "partially_supported":
        return "grounded-badge-medium";
      case "weakly_supported":
        return "grounded-badge-low";
      case "contested":
      case "rejected":
        return "grounded-badge-contested";
      default:
        return "grounded-badge-unknown";
    }
  };

  const formatGroundednessScore = (score?: number | null) => {
    if (score === null || score === undefined) return "Unassessed";
    return `${Math.round(score * 100)}% Grounded`;
  };

  return (
    <div
      className="hypothesis-card"
      data-testid={`hypothesis-card-${hypothesis.id}`}
    >
      {/* Header with Classification Badges */}
      <div className="hypothesis-header">
        <div className="hypothesis-badges-row">
          <span className="badge-hypothesis-type">
            <Sparkles size={13} />
            CANDIDATE HYPOTHESIS
          </span>
          <span className={`badge-confidence badge-confidence-${hypothesis.confidence}`}>
            MODEL CONFIDENCE: {hypothesis.confidence.toUpperCase()}
          </span>
          {hypothesis.groundedness_status && (
            <span
              className={`badge-groundedness ${getGroundednessBadgeClass(
                hypothesis.groundedness_status
              )}`}
              data-testid={`groundedness-badge-${hypothesis.id}`}
            >
              <ShieldCheck size={13} />
              SYSTEM GROUNDEDNESS: {String(hypothesis.groundedness_status).toUpperCase()}
            </span>
          )}
        </div>

        {hypothesis.groundedness_score !== undefined && hypothesis.groundedness_score !== null && (
          <div className="groundedness-score-chip" title="System Citation Entailment Ratio">
            {formatGroundednessScore(hypothesis.groundedness_score)}
          </div>
        )}
      </div>

      {/* Primary Hypothesis Statement / Claim */}
      <div className="hypothesis-claim-box">
        <h4 className="hypothesis-claim-text">{hypothesis.claim}</h4>
      </div>

      {/* Model Rationale */}
      <div className="hypothesis-section">
        <div className="section-label">Investigation Rationale</div>
        <p className="hypothesis-rationale-text">{hypothesis.rationale}</p>
      </div>

      {/* Model Confidence Uncalibrated Disclaimer */}
      <div className="uncalibrated-disclaimer-box">
        <Info size={13} style={{ flexShrink: 0 }} />
        <span>{hypothesis.confidence_note}</span>
      </div>

      {/* Groundedness Assessment Details (Milestone 4 Evidence) */}
      {hypothesis.assessment_details && (
        <div className="assessment-details-panel">
          <div className="section-label">System Groundedness Verification</div>
          <div className="assessment-metrics-grid">
            {hypothesis.system_confidence && (
              <div className="assessment-metric-item">
                <span className="metric-name">Calibrated Confidence</span>
                <span className="metric-val">{String(hypothesis.system_confidence).toUpperCase()}</span>
              </div>
            )}
            {hypothesis.assessment_details.support_score !== undefined && (
              <div className="assessment-metric-item">
                <span className="metric-name">Citation Entailment</span>
                <span className="metric-val">
                  {Math.round(Number(hypothesis.assessment_details.support_score) * 100)}%
                </span>
              </div>
            )}
            {hypothesis.assessment_details.contradiction_score !== undefined && (
              <div className="assessment-metric-item">
                <span className="metric-name">Contradiction Factor</span>
                <span className="metric-val">
                  {Math.round(Number(hypothesis.assessment_details.contradiction_score) * 100)}%
                </span>
              </div>
            )}
            {hypothesis.assessment_details.temporal_score !== undefined && (
              <div className="assessment-metric-item">
                <span className="metric-name">Temporal Consistency</span>
                <span className="metric-val">
                  {Math.round(Number(hypothesis.assessment_details.temporal_score) * 100)}%
                </span>
              </div>
            )}
            {hypothesis.assessment_details.diversity_score !== undefined && (
              <div className="assessment-metric-item">
                <span className="metric-name">Source Diversity</span>
                <span className="metric-val">
                  {Math.round(Number(hypothesis.assessment_details.diversity_score) * 100)}%
                </span>
              </div>
            )}
            {hypothesis.assessment_details.invalid_citation_count !== undefined &&
              Number(hypothesis.assessment_details.invalid_citation_count) > 0 && (
                <div className="assessment-metric-item border-danger">
                  <span className="metric-name text-danger">Invalid Citations</span>
                  <span className="metric-val text-danger">
                    {String(hypothesis.assessment_details.invalid_citation_count)} Rejected
                  </span>
                </div>
              )}
            {hypothesis.assessment_details.calibration_status && (
              <div className="assessment-metric-item">
                <span className="metric-name">Calibration Policy</span>
                <span className="metric-val" style={{ textTransform: "capitalize" }}>
                  {String(hypothesis.assessment_details.calibration_status)}
                </span>
              </div>
            )}
          </div>

          {hypothesis.assessment_details.assessment_reasons &&
            Array.isArray(hypothesis.assessment_details.assessment_reasons) &&
            hypothesis.assessment_details.assessment_reasons.length > 0 && (
              <div className="assessment-reasons-list">
                {hypothesis.assessment_details.assessment_reasons.map((reason, idx) => (
                  <div key={idx} className="assessment-reason-pill">
                    <CheckCircle size={12} color="#10b981" />
                    <span>{reason}</span>
                  </div>
                ))}
              </div>
            )}
        </div>
      )}

      {/* Supporting Evidence Citations */}
      <div className="hypothesis-section">
        <div className="section-label supporting-label">
          <CheckCircle size={13} color="#10b981" />
          Supporting Evidence ({hypothesis.supporting_evidence.length})
        </div>

        {hypothesis.supporting_evidence.length === 0 ? (
          <div className="evidence-citation-empty">
            <HelpCircle size={14} />
            <span>No supporting operational evidence citations linked by the engine.</span>
          </div>
        ) : (
          <div className="citations-list">
            {hypothesis.supporting_evidence.map((link) => (
              <div key={link.id} className="citation-item supporting">
                <div className="citation-header">
                  <span className="citation-pill supports">SUPPORTS</span>
                  <button
                    className="citation-link-btn"
                    onClick={() => onInspectEvidence?.(link.evidence_event_id)}
                    title="Inspect Evidence in Evidence tab"
                    data-testid={`citation-link-${link.evidence_event_id}`}
                  >
                    <span>Evidence #{link.evidence_event_id.substring(0, 12)}...</span>
                    <ExternalLink size={12} />
                  </button>
                </div>
                {link.excerpt && <p className="citation-excerpt">"{link.excerpt}"</p>}
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Contradicting Evidence Citations (Exposed Prominently) */}
      {hypothesis.contradicting_evidence.length > 0 && (
        <div className="hypothesis-section contradicting-section">
          <div className="section-label contradicting-label">
            <AlertOctagon size={13} color="#ef4444" />
            Contradicting Evidence ({hypothesis.contradicting_evidence.length})
          </div>
          <div className="citations-list">
            {hypothesis.contradicting_evidence.map((link) => (
              <div key={link.id} className="citation-item contradicts">
                <div className="citation-header">
                  <span className="citation-pill contradicts">CONTRADICTS</span>
                  <button
                    className="citation-link-btn"
                    onClick={() => onInspectEvidence?.(link.evidence_event_id)}
                    title="Inspect Contradicting Evidence in Evidence tab"
                    data-testid={`contradiction-link-${link.evidence_event_id}`}
                  >
                    <span>Evidence #{link.evidence_event_id.substring(0, 12)}...</span>
                    <ExternalLink size={12} />
                  </button>
                </div>
                {link.excerpt && <p className="citation-excerpt">"{link.excerpt}"</p>}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Path into Remediation Review */}
      {onNavigateRemediations && (
        <div className="hypothesis-footer-action">
          <button
            className="btn-next-remediation"
            onClick={onNavigateRemediations}
            data-testid={`remediation-path-btn-${hypothesis.id}`}
          >
            <ShieldAlert size={14} />
            Review Recommended Remediation Steps
            <ChevronRight size={14} />
          </button>
        </div>
      )}
    </div>
  );
};
