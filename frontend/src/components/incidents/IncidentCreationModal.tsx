import React, { useState } from "react";
import { AlertCircle, X, ShieldAlert, Loader2 } from "lucide-react";
import { Incident, IncidentCreatePayload, IncidentSeverity } from "../../types/incident";
import { IncidentsApi } from "../../api/incidents";

interface IncidentCreationModalProps {
  isOpen: boolean;
  onClose: () => void;
  onCreated: (incident: Incident) => void;
}

export const IncidentCreationModal: React.FC<IncidentCreationModalProps> = ({
  isOpen,
  onClose,
  onCreated,
}) => {
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [severity, setSeverity] = useState<IncidentSeverity>("medium");
  const [serviceName, setServiceName] = useState("");
  const [environment, setEnvironment] = useState("production");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  if (!isOpen) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    const trimmedTitle = title.trim();
    if (!trimmedTitle) {
      setError("Incident title is required.");
      return;
    }

    setIsSubmitting(true);
    setError(null);

    const payload: IncidentCreatePayload = {
      title: trimmedTitle,
      description: description.trim() || null,
      severity,
      service_name: serviceName.trim() || null,
      environment: environment.trim() || "production",
    };

    try {
      const created = await IncidentsApi.create(payload);
      // Reset form
      setTitle("");
      setDescription("");
      setSeverity("medium");
      setServiceName("");
      setEnvironment("production");
      setError(null);
      onCreated(created);
      onClose();
    } catch (err: unknown) {
      const msg =
        err && typeof err === "object" && "message" in err
          ? String((err as { message: unknown }).message)
          : "Failed to create incident. Please try again.";
      setError(msg);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="modal-overlay" role="dialog" aria-modal="true" data-testid="incident-creation-modal">
      <div className="modal-content">
        <div className="modal-header">
          <h3>
            <ShieldAlert size={20} color="var(--accent-primary)" />
            Create Incident
          </h3>
          <button
            onClick={onClose}
            disabled={isSubmitting}
            style={{
              background: "none",
              border: "none",
              cursor: isSubmitting ? "not-allowed" : "pointer",
              color: "var(--text-muted)",
              padding: 4,
              display: "flex",
              alignItems: "center",
            }}
            aria-label="Close modal"
          >
            <X size={18} />
          </button>
        </div>

        <form onSubmit={handleSubmit}>
          <div className="modal-body">
            {error && (
              <div
                style={{
                  background: "rgba(239, 68, 68, 0.1)",
                  border: "1px solid rgba(239, 68, 68, 0.3)",
                  borderRadius: "var(--radius-md)",
                  padding: "10px 14px",
                  color: "#ef4444",
                  fontSize: "0.85rem",
                  display: "flex",
                  alignItems: "center",
                  gap: "8px",
                }}
                data-testid="creation-error-banner"
              >
                <AlertCircle size={16} style={{ flexShrink: 0 }} />
                <span>{error}</span>
              </div>
            )}

            <div className="form-group">
              <label htmlFor="incident-title" className="form-label">
                Incident Title <span className="required">*</span>
              </label>
              <input
                id="incident-title"
                data-testid="incident-title-input"
                className="form-input"
                type="text"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="e.g., Payment Gateway 502 Bad Gateway Spike"
                maxLength={255}
                disabled={isSubmitting}
                autoFocus
              />
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "12px" }}>
              <div className="form-group">
                <label htmlFor="incident-severity" className="form-label">
                  Severity Level
                </label>
                <select
                  id="incident-severity"
                  data-testid="incident-severity-select"
                  className="form-select"
                  value={severity}
                  onChange={(e) => setSeverity(e.target.value as IncidentSeverity)}
                  disabled={isSubmitting}
                >
                  <option value="critical">Critical (SEV1)</option>
                  <option value="high">High (SEV2)</option>
                  <option value="medium">Medium (SEV3)</option>
                  <option value="low">Low (SEV4)</option>
                  <option value="info">Info</option>
                </select>
              </div>

              <div className="form-group">
                <label htmlFor="incident-service" className="form-label">
                  Affected Service
                </label>
                <input
                  id="incident-service"
                  data-testid="incident-service-input"
                  className="form-input"
                  type="text"
                  value={serviceName}
                  onChange={(e) => setServiceName(e.target.value)}
                  placeholder="e.g., checkout-service"
                  maxLength={100}
                  disabled={isSubmitting}
                />
              </div>
            </div>

            <div className="form-group">
              <label htmlFor="incident-env" className="form-label">
                Environment
              </label>
              <select
                id="incident-env"
                data-testid="incident-env-select"
                className="form-select"
                value={environment}
                onChange={(e) => setEnvironment(e.target.value)}
                disabled={isSubmitting}
              >
                <option value="production">Production</option>
                <option value="staging">Staging</option>
                <option value="development">Development</option>
              </select>
            </div>

            <div className="form-group">
              <label htmlFor="incident-desc" className="form-label">
                Description / Initial Symptoms
              </label>
              <textarea
                id="incident-desc"
                data-testid="incident-description-input"
                className="form-textarea"
                rows={3}
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="Observed error rates, alert notifications, or operational context..."
                disabled={isSubmitting}
              />
            </div>
          </div>

          <div className="modal-footer">
            <button
              type="button"
              className="btn-secondary-incident"
              onClick={onClose}
              disabled={isSubmitting}
            >
              Cancel
            </button>
            <button
              type="submit"
              className="btn-primary-incident"
              disabled={isSubmitting}
              data-testid="submit-incident-btn"
            >
              {isSubmitting ? (
                <>
                  <Loader2 size={15} className="spin" />
                  Creating...
                </>
              ) : (
                "Create Incident"
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};
