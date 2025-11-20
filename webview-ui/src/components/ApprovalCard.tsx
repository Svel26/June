import React, { useState } from 'react';

export type ApprovalCardProps = {
  proposedAction: string;
  onApprove?: () => void;
  onReject?: (feedback: string) => void;
  visible?: boolean;
};

const containerStyle: React.CSSProperties = {
  border: '1px solid #e6eef6',
  borderRadius: 6,
  padding: 12,
  background: '#ffffff',
  fontFamily: 'Inter,Segoe UI,Roboto,system-ui,-apple-system',
  boxShadow: '0 1px 2px rgba(16,24,40,0.04)',
  maxWidth: 560
};

const headerStyle: React.CSSProperties = {
  marginBottom: 8
};

const actionStyle: React.CSSProperties = {
  marginTop: 12,
  display: 'flex',
  gap: 8,
  alignItems: 'center'
};

const approveBtnStyle: React.CSSProperties = {
  background: '#10b981',
  color: '#fff',
  border: 'none',
  padding: '8px 12px',
  borderRadius: 6,
  cursor: 'pointer',
  fontWeight: 600
};

const rejectBtnStyle: React.CSSProperties = {
  background: '#ef4444',
  color: '#fff',
  border: 'none',
  padding: '8px 12px',
  borderRadius: 6,
  cursor: 'pointer',
  fontWeight: 600
};

const inputStyle: React.CSSProperties = {
  flex: 1,
  padding: 8,
  borderRadius: 6,
  border: '1px solid #e6eef6',
  fontSize: 13
};

export default function ApprovalCard({ proposedAction, onApprove, onReject, visible = true }: ApprovalCardProps) {
  const [feedback, setFeedback] = useState('');
  if (!visible) return null;

  const handleApprove = () => {
    if (onApprove) {
      onApprove();
    } else {
      // fallback: notify host via postMessage
      // App.tsx can wire this to call the real API
      window.postMessage({ type: 'approval:approve', data: { action: proposedAction } }, '*');
    }
  };

  const handleReject = () => {
    if (onReject) {
      onReject(feedback);
    } else {
      window.postMessage({ type: 'approval:reject', data: { action: proposedAction, feedback } }, '*');
    }
    setFeedback('');
  };

  return (
    <div style={containerStyle}>
      <div style={headerStyle}>
        <div style={{ fontSize: 13, color: '#0f172a', fontWeight: 600 }}>Agent paused for approval</div>
        <div style={{ marginTop: 6, fontSize: 13, color: '#475569' }}>{proposedAction}</div>
      </div>

      <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
        <input
          aria-label="Rejection feedback"
          placeholder="Optional rejection feedback"
          value={feedback}
          onChange={(e) => setFeedback(e.target.value)}
          style={inputStyle}
        />
      </div>

      <div style={actionStyle}>
        <button onClick={handleApprove} style={approveBtnStyle}>Approve</button>
        <button onClick={handleReject} style={rejectBtnStyle}>Reject</button>
      </div>
    </div>
  );
}