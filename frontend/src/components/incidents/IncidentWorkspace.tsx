import React, { useState } from "react";
import {
  ArrowLeft,
  Clock,
  Database,
  Sparkles,
  ShieldAlert,
  Activity,
  Copy,
  Check,
  BookOpen,
  PlusCircle,
} from "lucide-react";
import { Incident } from "../../types/incident";
import { IncidentOverview } from "./IncidentOverview";
import { IncidentTimeline } from "./IncidentTimeline";
import { EvidencePanel } from "./EvidencePanel";
import { InvestigationPanel } from "./InvestigationPanel";
import { IncidentRemediationTab } from "./IncidentRemediationTab";
import { RunbooksPanel } from "./RunbooksPanel";
import { AddEvidenceModal } from "./AddEvidenceModal";

export type IncidentWorkspaceTab =
  | "overview"
  | "timeline"
  | "evidence"
  | "runbooks"
  | "investigation"
  | "remediation";

interface IncidentWorkspaceProps {
  incident: Incident;
  onBack: () => void;
  onNavigateRemediations?: (incidentId?: string) => void;
  initialTab?: IncidentWorkspaceTab;
  onOpenDocument?: (documentId: string) => void;
}

export const IncidentWorkspace: React.FC<IncidentWorkspaceProps> = ({
  incident,
  onBack,
  onNavigateRemediations,
  initialTab = "overview",
  onOpenDocument,
}) => {
  const [activeTab, setActiveTab] = useState<IncidentWorkspaceTab>(initialTab);
  const [selectedEvidenceId, setSelectedEvidenceId] = useState<string | null>(null);
  const [copiedId, setCopiedId] = useState<boolean>(false);
  const [isAddEvidenceOpen, setIsAddEvidenceOpen] = useState<boolean>(false);
  const [evidenceRefreshToken, setEvidenceRefreshToken] = useState<number>(0);

  // Switch to Evidence tab and select the specific evidence item (from Timeline or Hypothesis citation)
  const handleInspectEvidence = (evidenceId: string) => {
    setSelectedEvidenceId(evidenceId);
    setActiveTab("evidence");
  };

  const handleCopyId = () => {
    navigator.clipboard.writeText(incident.id).catch(() => {});
    setCopiedId(true);
    setTimeout(() => setCopiedId(false), 2000);
  };

  const formatDate = (dateStr: string) => {
    try {
      const d = new Date(dateStr);
      return isNaN(d.getTime()) ? dateStr : d.toLocaleString();
    } catch {
      return dateStr;
    }
  };

  return (
    <div
      className="incident-workspace-container incident-detail-panel"
      data-testid="incident-workspace"
    >
      {/* Workspace Header */}
      <div className="workspace-header">
        <button
          className="workspace-back-btn"
          onClick={onBack}
          data-testid="back-to-incidents-btn"
        >
          <ArrowLeft size={16} />
          Back to Incidents
        </button>

        <div className="workspace-header-headline">
          <div className="headline-left">
            <div className="workspace-badges-row">
              <span className={`badge-severity badge-severity-${incident.severity}`}>
                {incident.severity}
              </span>
              <span className="badge-status">{incident.status}</span>
              {incident.service_name && (
                <span className="badge-service">{incident.service_name}</span>
              )}
              <span className="badge-environment">ENV: {incident.environment.toUpperCase()}</span>
            </div>

            <h2 className="workspace-title" data-testid="workspace-incident-title">
              {incident.title}
            </h2>
          </div>

          <div className="headline-right">
            <div className="flex items-center gap-2">
              <button
                type="button"
                className="btn-primary-incident"
                onClick={() => setIsAddEvidenceOpen(true)}
                data-testid="workspace-add-evidence-btn"
              >
                <PlusCircle size={12} />
                Add Evidence
              </button>
              <div className="workspace-id-chip">
                <span className="id-label">INCIDENT ID:</span>
                <code className="id-val">{incident.id}</code>
                <button
                  className="btn-copy-id"
                  onClick={handleCopyId}
                  title="Copy Incident ID"
                  data-testid="copy-incident-id-btn"
                >
                  {copiedId ? <Check size={12} color="#10b981" /> : <Copy size={12} />}
                </button>
              </div>
            </div>
            <span className="workspace-created-time">
              Created: {formatDate(incident.created_at)}
            </span>
          </div>
        </div>

        {/* Tab Navigation Bar */}
        <div className="workspace-tabs-bar" role="tablist">
          <button
            role="tab"
            aria-selected={activeTab === "overview"}
            className={`workspace-tab-btn ${activeTab === "overview" ? "active" : ""}`}
            onClick={() => setActiveTab("overview")}
            data-testid="tab-overview"
          >
            <Activity size={14} />
            Overview
          </button>
          <button
            role="tab"
            aria-selected={activeTab === "timeline"}
            className={`workspace-tab-btn ${activeTab === "timeline" ? "active" : ""}`}
            onClick={() => setActiveTab("timeline")}
            data-testid="tab-timeline"
          >
            <Clock size={14} />
            Timeline
          </button>
          <button
            role="tab"
            aria-selected={activeTab === "evidence"}
            className={`workspace-tab-btn ${activeTab === "evidence" ? "active" : ""}`}
            onClick={() => setActiveTab("evidence")}
            data-testid="tab-evidence"
          >
            <Database size={14} />
            Evidence
          </button>
          <button
            role="tab"
            aria-selected={activeTab === "runbooks"}
            className={`workspace-tab-btn ${activeTab === "runbooks" ? "active" : ""}`}
            onClick={() => setActiveTab("runbooks")}
            data-testid="tab-runbooks"
          >
            <BookOpen size={14} />
            Runbooks
          </button>
          <button
            role="tab"
            aria-selected={activeTab === "investigation"}
            className={`workspace-tab-btn ${activeTab === "investigation" ? "active" : ""}`}
            onClick={() => setActiveTab("investigation")}
            data-testid="tab-investigation"
          >
            <Sparkles size={14} />
            Investigation
          </button>
          <button
            role="tab"
            aria-selected={activeTab === "remediation"}
            className={`workspace-tab-btn ${activeTab === "remediation" ? "active" : ""}`}
            onClick={() => setActiveTab("remediation")}
            data-testid="tab-remediation"
          >
            <ShieldAlert size={14} />
            Remediation
          </button>
        </div>
      </div>

      {/* Tab Panels Content */}
      <div className="workspace-tab-content" data-testid="workspace-tab-content">
        {activeTab === "overview" && (
          <IncidentOverview
            key={evidenceRefreshToken}
            incident={incident}
            onNavigateTab={setActiveTab}
            onNavigateRemediations={onNavigateRemediations}
          />
        )}

        {activeTab === "timeline" && (
          <IncidentTimeline
            key={evidenceRefreshToken}
            incidentId={incident.id}
            onInspectEvidence={handleInspectEvidence}
          />
        )}

        {activeTab === "evidence" && (
          <EvidencePanel
            key={evidenceRefreshToken}
            incidentId={incident.id}
            selectedEvidenceId={selectedEvidenceId}
            onSelectEvidence={setSelectedEvidenceId}
            onAddEvidenceClick={() => setIsAddEvidenceOpen(true)}
          />
        )}

        {activeTab === "runbooks" && (
          <RunbooksPanel
            incident={incident}
            onOpenDocument={onOpenDocument}
          />
        )}

        {activeTab === "investigation" && (
          <InvestigationPanel
            incidentId={incident.id}
            onInspectEvidence={handleInspectEvidence}
            onNavigateRemediations={() => setActiveTab("remediation")}
          />
        )}

        {activeTab === "remediation" && (
          <IncidentRemediationTab
            incidentId={incident.id}
            onOpenReviewCenter={onNavigateRemediations}
            onNavigateInvestigation={() => setActiveTab("investigation")}
          />
        )}
      </div>

      {/* Add Evidence Modal */}
      <AddEvidenceModal
        incident={incident}
        isOpen={isAddEvidenceOpen}
        onClose={() => setIsAddEvidenceOpen(false)}
        onEvidenceAdded={() => {
          setEvidenceRefreshToken((c) => c + 1);
        }}
      />
    </div>
  );
};
