import React from 'react';
import { CheckCircle, Loader, Circle } from 'lucide-react';
import './App.css';

type Props = {
  plan: string[];
  currentStepIndex: number;
  isReflecting?: boolean;
  currentStepRetry?: boolean;
};

export default function PlanViewer({ plan, currentStepIndex, isReflecting, currentStepRetry }: Props) {
  return (
    <div className="plan-viewer">
      {/* Reflecting banner */}
      {isReflecting && (
        <div
          className="reflecting"
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            marginBottom: 8,
            color: '#ff9800',
            fontWeight: 600,
            fontSize: 13,
          }}
        >
          <Loader className="icon" />
          <span>Reflecting...</span>
        </div>
      )}

      <ol className="plan-list">
        {plan.length === 0 ? (
          <li className="empty">No steps</li>
        ) : (
          plan.map((step, idx) => {
            const status =
              idx < currentStepIndex ? 'completed' : idx === currentStepIndex ? 'in-progress' : 'pending';
            const isCurrent = idx === currentStepIndex;
            return (
              <li key={idx} className={`plan-step ${status} ${isCurrent && currentStepRetry ? 'retrying' : ''}`}>
                <div className="step-marker">
                  {status === 'completed' && <CheckCircle className="icon completed" />}
                  {status === 'in-progress' && <Loader className="icon spinning" />}
                  {status === 'pending' && <Circle className="icon pending" />}
                </div>
                <div className="step-content" style={{ display: 'flex', alignItems: 'center' }}>
                  <div className="step-title">{step}</div>

                  {/* Orange retry badge shown next to the current step when it's being retried */}
                  {isCurrent && currentStepRetry && (
                    <span
                      className="retry-badge"
                      style={{
                        background: '#ff9800',
                        color: '#fff',
                        borderRadius: 12,
                        padding: '2px 8px',
                        marginLeft: 8,
                        fontSize: 12,
                        fontWeight: 600,
                      }}
                      aria-label="Retrying"
                    >
                      Retrying
                    </span>
                  )}

                  <div className="step-meta" style={{ marginLeft: 'auto', opacity: 0.8 }}>
                    {status === 'completed' ? 'Completed' : status === 'in-progress' ? 'In progress' : 'Pending'}
                  </div>
                </div>
              </li>
            );
          })
        )}
      </ol>
    </div>
  );
}