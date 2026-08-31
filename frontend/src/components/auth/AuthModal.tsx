import React, { useState } from "react";
import { Bot, LogIn, UserPlus } from "lucide-react";
import { AuthApi } from "../../api/auth";
import { ApiClient } from "../../api/client";
import { User, Organization } from "../../types";

interface AuthModalProps {
  isOpen: boolean;
  onSuccess: (user: User, org: Organization | null) => void;
}

export const AuthModal: React.FC<AuthModalProps> = ({ isOpen, onSuccess }) => {
  const [isLogin, setIsLogin] = useState(true);
  const [email, setEmail] = useState("researcher@ragforge.ai");
  const [password, setPassword] = useState("ProductionRAG2026!");
  const [fullName, setFullName] = useState("AI Researcher");
  const [orgName, setOrgName] = useState("RAGForge Labs");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  if (!isOpen) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setLoading(true);

    try {
      if (isLogin) {
        const resp = await AuthApi.login({ email, password });
        ApiClient.setToken(resp.access_token);
        const memberships = await AuthApi.getUserOrganizations();
        const primaryOrg = memberships[0]?.organization || (memberships[0] ? {
          id: memberships[0].organization_id,
          name: "Workspace",
          slug: "workspace",
        } : null);
        if (primaryOrg) {
          ApiClient.setOrganizationId(primaryOrg.id);
        }
        onSuccess(resp.user, primaryOrg);
      } else {
        const resp = await AuthApi.register({
          email,
          password,
          full_name: fullName,
          organization_name: orgName,
        });
        ApiClient.setToken(resp.access_token);
        ApiClient.setOrganizationId(resp.organization.id);
        onSuccess(resp.user, resp.organization);
      }
    } catch (err: unknown) {
      const apiErr = err as { message?: string; detail?: string };
      setError(apiErr.message || apiErr.detail || "Authentication failed. Please check credentials.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="modal-overlay">
      <div className="modal-card">
        <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
          <div className="logo-icon">
            <Bot size={18} color="white" />
          </div>
          <div>
            <h2 style={{ fontSize: "1.15rem", fontWeight: 700 }}>
              {isLogin ? "Welcome to RAGForge" : "Create RAGForge Account"}
            </h2>
            <p style={{ fontSize: "0.8rem", color: "var(--text-muted)" }}>
              {isLogin ? "Sign in to access your knowledge bases" : "Get started with grounded AI research"}
            </p>
          </div>
        </div>

        {error && (
          <div style={{ padding: "10px 14px", backgroundColor: "var(--danger-bg)", border: "1px solid var(--danger-border)", borderRadius: "var(--radius-md)", color: "var(--danger-text)", fontSize: "0.85rem" }}>
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: "14px" }}>
          {!isLogin && (
            <>
              <div>
                <label className="control-label" style={{ display: "block", marginBottom: "6px" }}>Full Name</label>
                <input
                  type="text"
                  className="form-input"
                  value={fullName}
                  onChange={(e) => setFullName(e.target.value)}
                  required
                />
              </div>
              <div>
                <label className="control-label" style={{ display: "block", marginBottom: "6px" }}>Organization Name</label>
                <input
                  type="text"
                  className="form-input"
                  value={orgName}
                  onChange={(e) => setOrgName(e.target.value)}
                  required
                />
              </div>
            </>
          )}

          <div>
            <label className="control-label" style={{ display: "block", marginBottom: "6px" }}>Email</label>
            <input
              type="email"
              className="form-input"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />
          </div>

          <div>
            <label className="control-label" style={{ display: "block", marginBottom: "6px" }}>Password</label>
            <input
              type="password"
              className="form-input"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </div>

          <button type="submit" className="btn-primary" disabled={loading} style={{ marginTop: "6px", display: "flex", alignItems: "center", justifyContent: "center", gap: "8px" }}>
            {isLogin ? <LogIn size={16} /> : <UserPlus size={16} />}
            <span>{loading ? "Processing..." : isLogin ? "Sign In" : "Register"}</span>
          </button>
        </form>

        <div style={{ textAlign: "center", fontSize: "0.85rem", color: "var(--text-muted)" }}>
          {isLogin ? "Don't have an account? " : "Already have an account? "}
          <button
            type="button"
            onClick={() => { setIsLogin(!isLogin); setError(null); }}
            style={{ background: "transparent", border: "none", color: "var(--accent-primary)", fontWeight: 600, cursor: "pointer" }}
          >
            {isLogin ? "Sign up" : "Sign in"}
          </button>
        </div>
      </div>
    </div>
  );
};
